"""Каркас телеграм-бота на aiogram 3.

Запуск:
    python -m misbot.bot

Состояние пользователя (выбранный город и последняя выдача) лежит в памяти
процесса: при перезапуске теряется. На шаге 5 переедет в SQLite вместе с кешем.
"""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Sequence, Set  # noqa: F401

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from . import formatting as fmt
from . import stats as counters
from .alerts import Alerter
from .cache import PharmacyCache
from .config import Config, ConfigError
from .locations import EVERYWHERE, CityDirectory
from .mis_client import MisClient, MisUnavailable
from .models import Medicine
from .parser import ParseError, QueryTooShort, parse_pharmacies
from .pharmacies import cached_only, resolve
from .search import find_medicines
from .stats import Stats, count
from .user_store import UserStore

log = logging.getLogger(__name__)

CITY_KEY = "city"
RESULTS_KEY = "results"
"""Последняя выдача: список [хеш, название] — чтобы листать без нового запроса."""

MEDICINE_PREFIX = "m"
CITY_PREFIX = "c"
PAGE_PREFIX = "p"

CITY_COLUMNS = 2

_busy: Set[int] = set()
"""Кто уже ждёт ответа. Один пользователь — один запрос к mis.ge за раз."""

_city_fallback: Dict[int, int] = {}
"""Выбранный город, когда база не подключена (тесты и запуск без хранилища)."""


# --- клавиатуры ------------------------------------------------------------

def medicines_keyboard(buttons: Sequence, offset: int, total: int) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    row: List[InlineKeyboardButton] = []
    for label, medicine_hash in buttons:
        row.append(
            InlineKeyboardButton(text=label, callback_data=f"{MEDICINE_PREFIX}:{medicine_hash}")
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    navigation: List[InlineKeyboardButton] = []
    if offset:
        previous = max(0, offset - fmt.MEDICINES_PER_PAGE)
        navigation.append(
            InlineKeyboardButton(text="← назад", callback_data=f"{PAGE_PREFIX}:{previous}")
        )
    if offset + fmt.MEDICINES_PER_PAGE < total:
        following = offset + fmt.MEDICINES_PER_PAGE
        navigation.append(
            InlineKeyboardButton(text="ещё →", callback_data=f"{PAGE_PREFIX}:{following}")
        )
    if navigation:
        rows.append(navigation)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def cities_keyboard(directory: CityDirectory) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [[
        InlineKeyboardButton(
            text="Вся Грузия", callback_data=f"{CITY_PREFIX}:{EVERYWHERE}"
        )
    ]]

    row: List[InlineKeyboardButton] = []
    for city in directory.all():
        row.append(
            InlineKeyboardButton(text=city.name, callback_data=f"{CITY_PREFIX}:{city.id}")
        )
        if len(row) == CITY_COLUMNS:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- команды ---------------------------------------------------------------

async def handle_start(message: Message, stats: Optional[Stats] = None) -> None:
    await count(stats, counters.START, _user_id(message.from_user))
    await message.answer(fmt.greeting(), disable_web_page_preview=True)


async def handle_help(message: Message) -> None:
    await message.answer(fmt.help_text(), disable_web_page_preview=True)


async def handle_about(message: Message, config: Config) -> None:
    await message.answer(fmt.about_text(config.contact), disable_web_page_preview=True)


async def handle_stats(
    message: Message,
    config: Config,
    stats: Optional[Stats] = None,
) -> None:
    """Счётчики — только владельцу. Остальным команды как будто нет.

    Молчим, а не отвечаем «нельзя»: иначе существование команды видно любому,
    кто её наберёт.
    """
    if not config.admin_id or _user_id(message.from_user) != config.admin_id:
        return
    if stats is None:
        return
    await message.answer(fmt.stats_text(await stats.report()))


async def handle_id(message: Message) -> None:
    """Свой telegram id — чтобы было что положить в MISGE_ADMIN_ID."""
    await message.answer(fmt.chat_id(_user_id(message.from_user)))


async def handle_city(
    message: Message,
    cities: CityDirectory,
    config: Config,
    users: Optional[UserStore] = None,
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    current = await _current_city(user_id, users, config)
    await message.answer(
        fmt.choose_city(cities.name(current)),
        reply_markup=cities_keyboard(cities),
    )


async def handle_city_chosen(
    callback: CallbackQuery,
    cities: CityDirectory,
    users: Optional[UserStore] = None,
) -> None:
    city_id = _int(callback.data.split(":", 1)[1])
    if city_id is None or not cities.known(city_id):
        await callback.answer("Такого города не знаю")
        return

    user_id = callback.from_user.id if callback.from_user else 0
    if users is not None:
        await users.set_city(user_id, city_id)
    else:
        _city_fallback[user_id] = city_id

    await callback.answer()
    if callback.message:
        await callback.message.edit_text(fmt.city_chosen(cities.name(city_id)))


# --- поиск -----------------------------------------------------------------

async def handle_query(
    message: Message,
    state: FSMContext,
    client: MisClient,
    cities: CityDirectory,
    config: Config,
    stats: Optional[Stats] = None,
    users: Optional[UserStore] = None,
    alerts: Optional[Alerter] = None,
) -> None:
    user_id = _user_id(message.from_user)
    if user_id in _busy:
        await message.answer(fmt.busy())
        return

    query = (message.text or "").strip()
    _busy.add(user_id)
    try:
        notice = await message.answer(fmt.searching(query))
        await count(stats, counters.SEARCH, user_id)
        try:
            outcome = await find_medicines(client, query)
        except QueryTooShort:
            await count(stats, counters.TOO_SHORT)
            await notice.edit_text(fmt.too_short())
            return
        except MisUnavailable:
            await count(stats, counters.UNAVAILABLE)
            await notice.edit_text(fmt.site_unavailable())
            return
        except ParseError as exc:
            await count(stats, counters.UNAVAILABLE)
            log.error("парсер сломался на выдаче поиска: %s", exc)
            if alerts is not None:
                await alerts.parser_broken("поиск препарата", str(exc))
            await notice.edit_text(fmt.parser_broken())
            return

        if not outcome.found:
            await count(stats, counters.NOTHING)
            await notice.edit_text(fmt.nothing_found(query))
            return

        await count(stats, counters.FOUND)

        await _remember(state, outcome.medicines)
        city = await _current_city(user_id, users, config)
        text, buttons = fmt.medicines_page(outcome.medicines, 0, cities.name(city))
        await notice.edit_text(
            text, reply_markup=medicines_keyboard(buttons, 0, len(outcome.medicines))
        )
    finally:
        _busy.discard(user_id)


async def handle_page(
    callback: CallbackQuery,
    state: FSMContext,
    cities: CityDirectory,
    config: Config,
    users: Optional[UserStore] = None,
) -> None:
    offset = _int(callback.data.split(":", 1)[1]) or 0
    medicines = await _recall(state)
    await callback.answer()

    if not medicines or not callback.message:
        return

    city = await _current_city(_user_id(callback.from_user), users, config)
    text, buttons = fmt.medicines_page(medicines, offset, cities.name(city))
    await callback.message.edit_text(
        text, reply_markup=medicines_keyboard(buttons, offset, len(medicines))
    )


async def handle_medicine_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    client: MisClient,
    cities: CityDirectory,
    config: Config,
    cache: Optional[PharmacyCache] = None,
    stats: Optional[Stats] = None,
    users: Optional[UserStore] = None,
    alerts: Optional[Alerter] = None,
) -> None:
    medicine_hash = callback.data.split(":", 1)[1]
    user_id = _user_id(callback.from_user)

    if user_id in _busy:
        await callback.answer(fmt.busy())
        return
    await callback.answer()

    if callback.message is None:
        return

    city = await _current_city(user_id, users, config)
    _busy.add(user_id)
    try:
        stocks = parse_pharmacies(await client.pharmacies([medicine_hash], city=city))
    except MisUnavailable:
        await count(stats, counters.UNAVAILABLE)
        await callback.message.answer(fmt.site_unavailable())
        return
    except ParseError as exc:
        await count(stats, counters.UNAVAILABLE)
        log.error("парсер сломался на выдаче аптек: %s", exc)
        if alerts is not None:
            await alerts.parser_broken("наличие в аптеках", str(exc))
        await callback.message.answer(fmt.parser_broken())
        return
    finally:
        _busy.discard(user_id)

    await count(stats, counters.STOCKS, user_id)

    await _answer_with_addresses(callback.message, stocks, cities.name(city), client, cache)


async def _answer_with_addresses(
    message: Message,
    stocks: Sequence,
    city_name: str,
    client: MisClient,
    cache: Optional[PharmacyCache],
) -> None:
    """Сначала цены, потом адреса.

    Карточка аптеки — отдельный запрос к сайту, то есть секунда ожидания на
    каждую. Поэтому сообщение уходит сразу с тем, что есть в кеше, и правится,
    когда недостающие карточки доедут. Со второго раза кеш уже полон и правки
    не будет вовсе.
    """
    shown = fmt.shown_stocks(stocks)
    wanted = [stock.pharmacy_id for stock in shown if stock.pharmacy_id is not None]

    cached = await cache.get_many(wanted) if cache is not None else {}
    sent = await message.answer(
        fmt.stocks_message(stocks, city_name, cached),
        disable_web_page_preview=True,
    )

    if not wanted or cached_only(cached, wanted):
        return

    resolved = await resolve(client, cache, wanted)
    if resolved.keys() == cached.keys():
        return

    try:
        await sent.edit_text(
            fmt.stocks_message(stocks, city_name, resolved),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        # Текст не изменился или сообщение уже недоступно — не повод падать.
        log.debug("не удалось дописать адреса в сообщение")


# --- состояние -------------------------------------------------------------

async def _current_city(
    user_id: int,
    users: Optional[UserStore],
    config: Config,
) -> int:
    if users is not None:
        chosen = await users.get_city(user_id)
        if chosen is not None:
            return chosen
        return config.default_city
    return _city_fallback.get(user_id, config.default_city)


async def _remember(state: FSMContext, medicines: Sequence[Medicine]) -> None:
    """Кладём только то, что нужно для листания: хранилище может стать внешним."""
    await state.update_data(**{RESULTS_KEY: [
        {
            "hash": medicine.hash,
            "name": medicine.name,
            "company": medicine.company,
            "country": medicine.country,
            "dispensing": medicine.dispensing,
        }
        for medicine in medicines
    ]})


async def _recall(state: FSMContext) -> List[Medicine]:
    data = await state.get_data()
    return [
        Medicine(
            hash=row["hash"],
            name=row["name"],
            generic="",
            generic_hash=None,
            country=row["country"],
            company=row["company"],
            registration="",
            dispensing=row["dispensing"],
        )
        for row in data.get(RESULTS_KEY, [])
    ]


def _user_id(user) -> int:
    """0 — сообщение без отправителя: так приходят посты из каналов."""
    return user.id if user else 0


def _int(raw: str) -> Optional[int]:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# --- сборка ----------------------------------------------------------------

def build_router() -> Router:
    """Регистрация хендлеров списком.

    Не декораторами: декоратор привязывает функции к одному общему Router на весь
    модуль, а такой Router нельзя подключить к двум диспетчерам — тесты начинают
    мешать друг другу. Заодно весь набор обработчиков виден в одном месте.
    """
    router = Router()

    router.message.register(handle_start, CommandStart())
    router.message.register(handle_help, Command("help"))
    router.message.register(handle_about, Command("about"))
    router.message.register(handle_city, Command("city"))
    router.message.register(handle_stats, Command("stats"))
    router.message.register(handle_id, Command("id"))
    router.message.register(handle_query, F.text & ~F.text.startswith("/"))

    router.callback_query.register(handle_city_chosen, F.data.startswith(f"{CITY_PREFIX}:"))
    router.callback_query.register(handle_page, F.data.startswith(f"{PAGE_PREFIX}:"))
    router.callback_query.register(
        handle_medicine_chosen, F.data.startswith(f"{MEDICINE_PREFIX}:")
    )

    return router


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router())
    return dispatcher


# --- запуск ----------------------------------------------------------------

async def run(config: Config) -> None:
    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()

    # Владелец один и тот же и для /stats, и для сообщений о поломке: в личной
    # переписке telegram id пользователя совпадает с id чата.
    alerts = Alerter(bot, config.admin_id or None)

    async with MisClient(contact=config.contact) as client:
        async with PharmacyCache(config.database) as cache:
            async with Stats(config.database) as stats, UserStore(config.database) as users:
                cities = await CityDirectory.load(client)
                log.info(
                    "бот запускается, город по умолчанию: %s, карточек аптек в кеше: %d, "
                    "пользователей: %d, владелец: %s",
                    cities.name(config.default_city),
                    await cache.count(),
                    await users.count(),
                    f"{config.admin_id} (/stats и алерты)" if config.admin_id
                    else "не задан, /stats и алерты выключены",
                )
                try:
                    await dispatcher.start_polling(
                        bot,
                        client=client,
                        cities=cities,
                        config=config,
                        cache=cache,
                        stats=stats,
                        users=users,
                        alerts=alerts,
                    )
                finally:
                    await bot.session.close()


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        log.error("%s", exc)
        return 2

    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if config.log_file is not None:
        # Под автозапуском бот работает без консоли, поэтому пишем ещё и в файл.
        # Пять файлов по мегабайту — этого хватает на несколько недель.
        config.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                config.log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
            )
        )

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )
    # httpx на INFO печатает URL целиком, а там лежит user_name — то есть
    # то самое название препарата, которое мы обещали не логировать.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        asyncio.run(run(config))
    except (KeyboardInterrupt, SystemExit):
        log.info("остановлен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
