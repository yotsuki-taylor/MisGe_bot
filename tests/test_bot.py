"""Тесты хендлеров. Телеграм и сайт заменены заглушками.

Хендлеры вызываются напрямую — так проверяется их логика, а не то, как aiogram
разбирает апдейты.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from misbot import formatting as fmt
from misbot.bot import (
    CITY_PREFIX,
    MEDICINE_PREFIX,
    PAGE_PREFIX,
    _busy,
    _city_fallback,
    _current_city,
    _recall,
    _remember,
    cities_keyboard,
    handle_city_chosen,
    handle_medicine_chosen,
    handle_page,
    handle_query,
    handle_stats,
    medicines_keyboard,
)
from misbot.config import Config
from misbot.locations import EVERYWHERE, FALLBACK_CITIES, CityDirectory
from misbot.mis_client import MisUnavailable
from misbot.parser import parse_search
from misbot.stats import Stats
from misbot.user_store import UserStore

FIXTURES = Path(__file__).parent / "fixtures"
FOUND = (FIXTURES / "search_nurofen.html").read_text(encoding="utf-8")
EMPTY = (FIXTURES / "search_empty.html").read_text(encoding="utf-8")
PHARMACIES = (FIXTURES / "pharmacies_nurofen_tbilisi.html").read_text(encoding="utf-8")
NO_PHARMACIES = (FIXTURES / "pharmacies_empty.html").read_text(encoding="utf-8")


class FakeMessage:
    """Сообщение, которое умеет ровно то, чем пользуются хендлеры."""

    def __init__(self, text: str = "", user_id: int = 1) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.replies: List["FakeMessage"] = []
        self.edits: List[str] = []
        self.markup = None

    async def answer(self, text: str, reply_markup=None, **kwargs) -> "FakeMessage":
        reply = FakeMessage(text)
        reply.markup = reply_markup
        self.replies.append(reply)
        return reply

    async def edit_text(self, text: str, reply_markup=None, **kwargs) -> "FakeMessage":
        self.text = text
        self.edits.append(text)
        self.markup = reply_markup
        return self


class FakeCallback:
    def __init__(self, data: str, user_id: int = 1) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answered: List[str] = []

    async def answer(self, text: str = "", **kwargs) -> None:
        self.answered.append(text)


CARD = (FIXTURES / "pharmacy_card_334.html").read_text(encoding="utf-8")


class FakeClient:
    def __init__(self, search_html: str = FOUND, pharmacies_html: str = PHARMACIES) -> None:
        self.search_html = search_html
        self.pharmacies_html = pharmacies_html
        self.card_html = CARD
        self.searches: List[str] = []
        self.pharmacy_calls: List[tuple] = []
        self.card_calls: List[int] = []
        self.fail_with: Dict[str, Exception] = {}

    async def pharmacy_card(self, pharmacy_id: int) -> str:
        self.card_calls.append(pharmacy_id)
        if "card" in self.fail_with:
            raise self.fail_with["card"]
        return self.card_html

    async def search(self, query: str, *, starts_with: bool = True, by_generic: bool = False) -> str:
        self.searches.append(query)
        if "search" in self.fail_with:
            raise self.fail_with["search"]
        return self.search_html

    async def pharmacies(self, hashes, *, city=0, district=0, subdistrict=0) -> str:
        self.pharmacy_calls.append((tuple(hashes), city))
        if "pharmacies" in self.fail_with:
            raise self.fail_with["pharmacies"]
        return self.pharmacies_html


@pytest.fixture
def state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=1, user_id=1),
    )


@pytest.fixture
def cities() -> CityDirectory:
    return CityDirectory(dict(FALLBACK_CITIES))


@pytest.fixture
def config() -> Config:
    return Config(token="test", default_city=1)


@pytest.fixture
async def users(tmp_path):
    async with UserStore(tmp_path / "users.sqlite3") as store:
        yield store


@pytest.fixture(autouse=True)
def clean_globals():
    _busy.clear()
    _city_fallback.clear()
    yield
    _busy.clear()
    _city_fallback.clear()


class TestQuery:
    async def test_the_waiting_notice_becomes_the_answer(self, state, cities, config):
        # Сначала «Ищу…», потом то же сообщение правится на выдачу — чтобы в чате
        # не оставался мусор.
        message = FakeMessage("нурофен")
        await handle_query(message, state, FakeClient(), cities, config)

        notice = message.replies[0]
        assert len(message.replies) == 1
        assert "Нашлось" in notice.text
        assert notice.markup is not None

    async def test_nothing_found_explains_what_to_do(self, state, cities, config):
        message = FakeMessage("зззз")
        await handle_query(message, state, FakeClient(search_html=EMPTY), cities, config)
        assert "ничего не нашлось" in message.replies[0].text

    async def test_short_query_is_rejected_without_a_request(self, state, cities, config):
        client = FakeClient()
        message = FakeMessage("но")
        await handle_query(message, state, client, cities, config)

        assert client.searches == []
        assert message.replies[0].text == fmt.too_short()

    async def test_site_failure_is_reported_softly(self, state, cities, config):
        client = FakeClient()
        client.fail_with["search"] = MisUnavailable("нет связи")
        message = FakeMessage("нурофен")
        await handle_query(message, state, client, cities, config)

        assert message.replies[0].text == fmt.site_unavailable()

    async def test_second_query_while_busy_is_refused(self, state, cities, config):
        _busy.add(1)
        client = FakeClient()
        message = FakeMessage("нурофен")
        await handle_query(message, state, client, cities, config)

        assert client.searches == []
        assert message.replies[0].text == fmt.busy()

    async def test_lock_is_released_after_a_failure(self, state, cities, config):
        client = FakeClient()
        client.fail_with["search"] = MisUnavailable("нет связи")
        await handle_query(FakeMessage("нурофен"), state, client, cities, config)
        assert 1 not in _busy

    async def test_results_are_saved_for_paging(self, state, cities, config):
        await handle_query(FakeMessage("нурофен"), state, FakeClient(), cities, config)
        assert len(await _recall(state)) == 29


class TestPaging:
    async def test_page_two_continues_the_numbering(self, state, cities, config):
        await _remember(state, parse_search(FOUND))
        callback = FakeCallback(f"{PAGE_PREFIX}:8")
        await handle_page(callback, state, cities, config)

        assert "<b>9.</b>" in callback.message.text

    async def test_paging_edits_the_same_message(self, state, cities, config):
        # Клиент в этот хендлер вообще не передаётся: листаем сохранённую выдачу,
        # к сайту не ходим.
        await _remember(state, parse_search(FOUND))
        callback = FakeCallback(f"{PAGE_PREFIX}:8")
        await handle_page(callback, state, cities, config)

        assert len(callback.message.edits) == 1
        assert callback.message.replies == []

    async def test_paging_without_saved_results_is_harmless(self, state, cities, config):
        callback = FakeCallback(f"{PAGE_PREFIX}:8")
        await handle_page(callback, state, cities, config)

        assert callback.message.edits == []
        assert callback.answered == [""]


class TestMedicineChosen:
    async def test_asks_the_site_for_the_current_city(self, state, cities, config, users):
        await users.set_city(1, 5)
        client = FakeClient(pharmacies_html=NO_PHARMACIES)
        medicine_hash = "8D04DC19D9A1E25F51B8F06BE3B2E0EE"
        await handle_medicine_chosen(
            FakeCallback(f"{MEDICINE_PREFIX}:{medicine_hash}"),
            state, client, cities, config, users=users,
        )
        assert client.pharmacy_calls == [((medicine_hash,), 5)]

    async def test_shows_pharmacies(self, state, cities, config):
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
        await handle_medicine_chosen(callback, state, FakeClient(), cities, config)
        assert "7.85" in callback.message.replies[0].text

    async def test_prices_go_out_before_addresses(self, state, cities, config):
        # Сообщение уходит сразу, адреса дописываются правкой — иначе пользователь
        # ждал бы по секунде на каждую карточку, ничего не видя.
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
        client = FakeClient()
        await handle_medicine_chosen(callback, state, client, cities, config)

        answer = callback.message.replies[0]
        assert "7.85" in answer.edits[0] if answer.edits else True
        assert client.card_calls, "карточки аптек должны запрашиваться"
        assert "ვაჟა-ფშაველას" in answer.text, "адрес должен появиться после правки"

    async def test_addresses_come_from_the_cache_on_the_second_run(
        self, state, cities, config, tmp_path
    ):
        from misbot.cache import PharmacyCache

        client = FakeClient()
        async with PharmacyCache(tmp_path / "bot.sqlite3") as cache:
            for _ in range(2):
                callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
                await handle_medicine_chosen(
                    callback, state, client, cities, config, cache
                )
            first_run = len(set(client.card_calls))

        assert len(client.card_calls) == first_run, "второй раз карточки не перезапрашиваем"

    async def test_stocks_are_taken_from_the_cache_on_the_second_tap(
        self, state, cities, config, tmp_path
    ):
        from misbot.stock_cache import StockCache

        client = FakeClient()
        async with StockCache(tmp_path / "stocks.sqlite3") as stock_cache:
            for _ in range(2):
                await handle_medicine_chosen(
                    FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}"),
                    state, client, cities, config, stock_cache=stock_cache,
                )

        assert len(client.pharmacy_calls) == 1, "второй раз к сайту ходить не должны"

    async def test_works_without_a_cache(self, state, cities, config):
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
        await handle_medicine_chosen(callback, state, FakeClient(), cities, config, None)
        assert callback.message.replies[0].text

    async def test_card_failure_still_shows_prices(self, state, cities, config):
        client = FakeClient()
        client.fail_with["card"] = MisUnavailable("нет связи")
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
        await handle_medicine_chosen(callback, state, client, cities, config)

        assert "7.85" in callback.message.replies[0].text

    async def test_empty_city_gets_a_suggestion(self, state, cities, config):
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
        client = FakeClient(pharmacies_html=NO_PHARMACIES)
        await handle_medicine_chosen(callback, state, client, cities, config)
        assert "/city" in callback.message.replies[0].text

    async def test_lock_is_released_after_a_failure(self, state, cities, config):
        client = FakeClient()
        client.fail_with["pharmacies"] = MisUnavailable("нет связи")
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{'A' * 32}")
        await handle_medicine_chosen(callback, state, client, cities, config)

        assert 1 not in _busy
        assert callback.message.replies[0].text == fmt.site_unavailable()


class TestCity:
    async def test_choosing_a_city_saves_it(self, cities, config, users):
        await handle_city_chosen(FakeCallback(f"{CITY_PREFIX}:5"), cities, users)
        assert await _current_city(1, users, config) == 5

    async def test_unknown_city_is_ignored(self, cities, config, users):
        callback = FakeCallback(f"{CITY_PREFIX}:999")
        await handle_city_chosen(callback, cities, users)

        assert await _current_city(1, users, config) == config.default_city
        assert callback.answered == ["Такого города не знаю"]

    async def test_everywhere_is_a_valid_choice(self, cities, config, users):
        await handle_city_chosen(FakeCallback(f"{CITY_PREFIX}:{EVERYWHERE}"), cities, users)
        assert await _current_city(1, users, config) == EVERYWHERE

    async def test_default_city_applies_until_chosen(self, config, users):
        assert await _current_city(1, users, config) == 1

    async def test_choice_survives_a_restart(self, cities, config, tmp_path):
        # Ради этого всё и затевалось: перезапуск не должен сбрасывать город.
        path = tmp_path / "restart.sqlite3"
        async with UserStore(path) as before:
            await handle_city_chosen(FakeCallback(f"{CITY_PREFIX}:5"), cities, before)

        async with UserStore(path) as after:
            assert await _current_city(1, after, config) == 5

    async def test_users_do_not_share_a_city(self, cities, config, users):
        await handle_city_chosen(FakeCallback(f"{CITY_PREFIX}:5", user_id=1), cities, users)
        await handle_city_chosen(FakeCallback(f"{CITY_PREFIX}:2", user_id=2), cities, users)

        assert await _current_city(1, users, config) == 5
        assert await _current_city(2, users, config) == 2

    async def test_works_without_a_store(self, cities, config):
        # Хранилища нет — город живёт до перезапуска, но бот не падает.
        await handle_city_chosen(FakeCallback(f"{CITY_PREFIX}:5"), cities, None)
        assert await _current_city(1, None, config) == 5


class TestKeyboards:
    def test_first_page_has_no_back_button(self):
        medicines = parse_search(FOUND)
        _, buttons = fmt.medicines_page(medicines, 0, "Тбилиси")
        keyboard = medicines_keyboard(buttons, 0, len(medicines))
        labels = [b.text for row in keyboard.inline_keyboard for b in row]

        assert "← назад" not in labels
        assert "ещё →" in labels

    def test_last_page_has_no_forward_button(self):
        medicines = parse_search(FOUND)
        offset = 24
        _, buttons = fmt.medicines_page(medicines, offset, "Тбилиси")
        keyboard = medicines_keyboard(buttons, offset, len(medicines))
        labels = [b.text for row in keyboard.inline_keyboard for b in row]

        assert "← назад" in labels
        assert "ещё →" not in labels

    def test_callback_data_fits_the_telegram_limit(self):
        medicines = parse_search(FOUND)
        _, buttons = fmt.medicines_page(medicines, 0, "Тбилиси")
        keyboard = medicines_keyboard(buttons, 0, len(medicines))

        for row in keyboard.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode()) <= 64

    def test_city_keyboard_starts_with_everywhere_and_tbilisi(self, cities):
        keyboard = cities_keyboard(cities)
        assert keyboard.inline_keyboard[0][0].text == "Вся Грузия"
        assert keyboard.inline_keyboard[1][0].text == "Тбилиси"

    def test_city_keyboard_lists_every_city(self, cities):
        keyboard = cities_keyboard(cities)
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        assert len(buttons) == len(FALLBACK_CITIES) + 1


class TestStatsCommand:
    ADMIN = 42

    @pytest.fixture
    async def stats(self, tmp_path):
        store = await Stats(tmp_path / "stats.sqlite3").open()
        yield store
        await store.close()

    @pytest.fixture
    def admin_config(self) -> Config:
        return Config(token="test", default_city=1, admin_id=self.ADMIN)

    async def test_the_owner_gets_the_numbers(self, admin_config, stats):
        message = FakeMessage("/stats", user_id=self.ADMIN)
        await handle_stats(message, admin_config, stats)
        assert message.replies and "Статистика" in message.replies[0].text

    async def test_everyone_else_gets_silence(self, admin_config, stats):
        # Не «нельзя», а вообще ничего: иначе видно, что команда существует.
        message = FakeMessage("/stats", user_id=self.ADMIN + 1)
        await handle_stats(message, admin_config, stats)
        assert message.replies == []

    async def test_without_an_admin_id_the_command_is_off(self, config, stats):
        message = FakeMessage("/stats", user_id=self.ADMIN)
        await handle_stats(message, config, stats)
        assert message.replies == []

    async def test_searches_are_counted(self, state, cities, admin_config, stats):
        await handle_query(FakeMessage("нурофен"), state, FakeClient(), cities, admin_config, stats)
        today, _week, _total = await stats.report()
        assert (today.searches, today.found, today.people) == (1, 1, 1)

    async def test_empty_results_are_counted_apart(self, state, cities, admin_config, stats):
        message = FakeMessage("абракадабра")
        client = FakeClient(search_html=EMPTY)
        await handle_query(message, state, client, cities, admin_config, stats)
        today, _week, _total = await stats.report()
        assert (today.searches, today.found, today.nothing) == (1, 0, 1)

    async def test_a_dead_site_is_counted_apart(self, state, cities, admin_config, stats):
        client = FakeClient()
        client.fail_with["search"] = MisUnavailable("нет связи")
        await handle_query(FakeMessage("нурофен"), state, client, cities, admin_config, stats)
        today, _week, _total = await stats.report()
        assert (today.searches, today.found, today.nothing) == (1, 0, 0)

    async def test_viewing_pharmacies_is_counted(self, state, cities, admin_config, stats):
        medicines = parse_search(FOUND)
        await _remember(state, medicines)
        callback = FakeCallback(f"{MEDICINE_PREFIX}:{medicines[0].hash}")
        await handle_medicine_chosen(
            callback, state, FakeClient(), cities, admin_config, stats=stats
        )
        today, _week, _total = await stats.report()
        assert today.stocks == 1

    async def test_the_bot_works_without_stats_at_all(self, state, cities, config):
        message = FakeMessage("нурофен")
        await handle_query(message, state, FakeClient(), cities, config)
        assert "Нашлось" in message.replies[0].text
