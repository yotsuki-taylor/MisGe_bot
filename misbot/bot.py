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
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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
from .analogues import find_analogues
from .cache import PharmacyCache
from .config import Config, ConfigError
from .locations import EVERYWHERE, CityDirectory
from .mis_client import MisClient, MisUnavailable
from .models import Medicine
from .parser import ParseError, QueryTooShort
from .pharmacies import cached_only, resolve
from .search import find_medicines
from .stats import Stats, count
from .stock_cache import StockCache
from .stocks import find_stocks
from .user_store import UserStore
from .watcher import best_price, run_forever
from .watches import MAX_PER_USER, WatchStore

log = logging.getLogger(__name__)

CITY_KEY = "city"
RESULTS_KEY = "results"
"""Последняя выдача: список [хеш, название] — чтобы листать без нового запроса."""

MEDICINE_PREFIX = "m"
CITY_PREFIX = "c"
PAGE_PREFIX = "p"
WATCH_PREFIX = "w"
UNWATCH_PREFIX = "u"
ANALOGUE_PREFIX = "a"

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


def stock_keyboard(
    medicine_hash: str,
    city: int,
    *,
    watching: bool,
    generic_hash: str = "",
) -> Optional[InlineKeyboardMarkup]:
    """Кнопки под списком аптек: следить и посмотреть аналоги."""
    rows: List[List[InlineKeyboardButton]] = []

    if watching:
        rows.append([InlineKeyboardButton(
            text="🔔 Следить за препаратом",
            callback_data=f"{WATCH_PREFIX}:{medicine_hash}:{city}",
        )])
    if generic_hash:
        # Не «подешевле»: список не отсортирован по цене и не проверен на
        # наличие, обещать выгоду нечестно.
        rows.append([InlineKeyboardButton(
            text="🧬 Тот же состав",
            callback_data=f"{ANALOGUE_PREFIX}:{generic_hash}",
        )])

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def watches_keyboard(watches: Sequence) -> InlineKeyboardMarkup:
    """Номера подписок — нажатие отписывает."""
    row: List[InlineKeyboardButton] = []
    rows: List[List[InlineKeyboardButton]] = []

    for number, watch in enumerate(watches, start=1):
        row.append(
            InlineKeyboardButton(
                text=str(number),
                callback_data=f"{UNWATCH_PREFIX}:{watch.medicine}:{watch.city}",
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
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


async def handle_watching(
    message: Message,
    cities: CityDirectory,
    watches: Optional[WatchStore] = None,
) -> None:
    if watches is None:
        return
    mine = await watches.for_user(_user_id(message.from_user))
    await message.answer(
        fmt.watch_list(mine, cities.name),
        reply_markup=watches_keyboard(mine) if mine else None,
    )


async def handle_watch(
    callback: CallbackQuery,
    client: MisClient,
    cities: CityDirectory,
    watches: Optional[WatchStore] = None,
    stock_cache: Optional[StockCache] = None,
) -> None:
    """Подписаться. Текущее наличие берём из кеша — он только что заполнен."""
    if watches is None or callback.message is None:
        await callback.answer()
        return

    _, medicine_hash, raw_city = callback.data.split(":", 2)
    city = _int(raw_city) or 0
    user_id = _user_id(callback.from_user)

    try:
        stocks = await find_stocks(client, stock_cache, medicine_hash, city=city)
    except (MisUnavailable, ParseError):
        await callback.answer("Сейчас не получилось, попробуйте позже")
        return

    name = stocks[0].medicine_name if stocks else ""
    added = await watches.add(
        user_id, medicine_hash, city,
        name=name,
        available=bool(stocks),
        best_price=best_price(stocks),
    )

    if not added:
        await callback.answer()
        await callback.message.answer(fmt.watch_limit(MAX_PER_USER))
        return

    await callback.answer("Слежу")
    await callback.message.answer(fmt.watch_added(name, cities.name(city)))


async def handle_unwatch(
    callback: CallbackQuery,
    cities: CityDirectory,
    watches: Optional[WatchStore] = None,
) -> None:
    if watches is None or callback.message is None:
        await callback.answer()
        return

    _, medicine_hash, raw_city = callback.data.split(":", 2)
    user_id = _user_id(callback.from_user)
    await watches.remove(user_id, medicine_hash, _int(raw_city) or 0)
    await callback.answer("Больше не слежу")

    mine = await watches.for_user(user_id)
    await callback.message.edit_text(
        fmt.watch_list(mine, cities.name),
        reply_markup=watches_keyboard(mine) if mine else None,
    )


async def handle_analogues(
    callback: CallbackQuery,
    state: FSMContext,
    client: MisClient,
    cities: CityDirectory,
    config: Config,
    users: Optional[UserStore] = None,
    alerts: Optional[Alerter] = None,
) -> None:
    """Препараты с тем же действующим веществом.

    Дальше работает обычная выдача поиска: те же кнопки, то же листание, и по
    нажатию на аналог сразу видно его цены в аптеках.
    """
    generic_hash = callback.data.split(":", 1)[1]
    user_id = _user_id(callback.from_user)

    if user_id in _busy:
        await callback.answer(fmt.busy())
        return
    await callback.answer()

    if callback.message is None:
        return

    _busy.add(user_id)
    try:
        generic, medicines = await find_analogues(client, generic_hash)
    except MisUnavailable:
        await callback.message.answer(fmt.site_unavailable())
        return
    except ParseError as exc:
        log.error("парсер сломался на списке аналогов: %s", exc)
        if alerts is not None:
            await alerts.parser_broken("список аналогов", str(exc))
        await callback.message.answer(fmt.analogues_unavailable())
        return
    finally:
        _busy.discard(user_id)

    if not medicines:
        await callback.message.answer(fmt.no_analogues())
        return

    await _remember(state, medicines)
    city = await _current_city(user_id, users, config)
    text, buttons = fmt.medicines_page(
        medicines, 0, cities.name(city),
        title=fmt.analogues_title(generic, len(medicines)),
    )
    await callback.message.answer(
        text, reply_markup=medicines_keyboard(buttons, 0, len(medicines))
    )


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
    stock_cache: Optional[StockCache] = None,
    watches: Optional[WatchStore] = None,
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
        stocks = await find_stocks(client, stock_cache, medicine_hash, city=city)
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

    await _answer_with_addresses(
        callback.message, stocks, cities.name(city), client, cache,
        # Кнопки нужны и когда препарата нет: как раз тогда и хочется
        # подписаться или поискать аналог.
        buttons=stock_keyboard(
            medicine_hash, city,
            watching=watches is not None,
            generic_hash=await _generic_of(state, medicine_hash),
        ),
    )


async def _answer_with_addresses(
    message: Message,
    stocks: Sequence,
    city_name: str,
    client: MisClient,
    cache: Optional[PharmacyCache],
    buttons: Optional[InlineKeyboardMarkup] = None,
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
        reply_markup=buttons,
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
            reply_markup=buttons,
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
            "generic_hash": medicine.generic_hash or "",
        }
        for medicine in medicines
    ]})


async def _generic_of(state: FSMContext, medicine_hash: str) -> str:
    """Хеш действующего вещества для препарата из последней выдачи.

    Пустая строка — выдача уже забылась; тогда кнопки «аналоги» просто не будет.
    Само нажатие потом работает и на старых сообщениях: хеш вещества уезжает в
    callback_data, состояние для него не нужно.
    """
    data = await state.get_data()
    for row in data.get(RESULTS_KEY, []):
        if row.get("hash") == medicine_hash:
            return row.get("generic_hash") or ""
    return ""


async def _recall(state: FSMContext) -> List[Medicine]:
    data = await state.get_data()
    return [
        Medicine(
            hash=row["hash"],
            name=row["name"],
            generic="",
            generic_hash=row.get("generic_hash") or None,
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
    router.message.register(handle_watching, Command("watching"))
    router.message.register(handle_query, F.text & ~F.text.startswith("/"))

    router.callback_query.register(handle_city_chosen, F.data.startswith(f"{CITY_PREFIX}:"))
    router.callback_query.register(handle_page, F.data.startswith(f"{PAGE_PREFIX}:"))
    router.callback_query.register(handle_watch, F.data.startswith(f"{WATCH_PREFIX}:"))
    router.callback_query.register(handle_unwatch, F.data.startswith(f"{UNWATCH_PREFIX}:"))
    router.callback_query.register(handle_analogues, F.data.startswith(f"{ANALOGUE_PREFIX}:"))
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
            async with Stats(config.database) as stats, \
                    UserStore(config.database) as users, \
                    StockCache(config.database) as stock_cache, \
                    WatchStore(config.database) as watches:
                cities = await CityDirectory.load(client)
                dropped = await stock_cache.prune()
                log.info(
                    "бот запускается, город по умолчанию: %s, карточек аптек в кеше: %d, "
                    "остатков в кеше: %d (выброшено протухших: %d), "
                    "пользователей: %d, подписок: %d, владелец: %s",
                    cities.name(config.default_city),
                    await cache.count(),
                    await stock_cache.count(),
                    dropped,
                    await users.count(),
                    await watches.count(),
                    f"{config.admin_id} (/stats и алерты)" if config.admin_id
                    else "не задан, /stats и алерты выключены",
                )

                worker = asyncio.create_task(
                    run_forever(
                        client, stock_cache, watches,
                        _notifier(bot, cities),
                    )
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
                        stock_cache=stock_cache,
                        watches=watches,
                    )
                finally:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                    await bot.session.close()


def _notifier(bot: Bot, cities: CityDirectory):
    """Отправка уведомления по подписке.

    Заблокировавший бота пользователь — обычное дело, а не повод остановить
    обход остальных подписок.
    """
    async def notify(watch, reason: str, stocks) -> None:
        try:
            await bot.send_message(
                watch.user_id,
                fmt.watch_news(watch, reason, stocks, cities.name(watch.city)),
                disable_web_page_preview=True,
            )
        except TelegramForbiddenError:
            log.info("подписчик %s заблокировал бота", watch.user_id)
        except TelegramBadRequest as exc:
            log.warning("не доставил уведомление: %s", exc)

    return notify


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
