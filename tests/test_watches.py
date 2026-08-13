"""Тесты подписок: хранилище и решение, о чём писать пользователю."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest

from misbot.mis_client import MisUnavailable
from misbot.parser import parse_pharmacies
from misbot.stock_cache import StockCache
from misbot.watcher import APPEARED, CHEAPER, best_price, check_once, decide
from misbot.watches import MAX_PER_USER, Watch, WatchStore

FIXTURES = Path(__file__).parent / "fixtures"
PHARMACIES = (FIXTURES / "pharmacies_nurofen_tbilisi.html").read_text(encoding="utf-8")
NO_PHARMACIES = (FIXTURES / "pharmacies_empty.html").read_text(encoding="utf-8")

STOCKS = parse_pharmacies(PHARMACIES)
HASH = "8D04DC19D9A1E25F51B8F06BE3B2E0EE"


def watch(**overrides) -> Watch:
    defaults = dict(
        user_id=1,
        medicine=HASH,
        city=1,
        name="ნუროფენი",
        available=False,
        best_price=None,
        checked_at=None,
    )
    defaults.update(overrides)
    return Watch(**defaults)


class FakeClient:
    def __init__(self, html: str = PHARMACIES) -> None:
        self.html = html
        self.calls: List[tuple] = []
        self.fail: Exception = None

    async def pharmacies(self, hashes, *, city=0, district=0, subdistrict=0) -> str:
        self.calls.append((tuple(hashes), city))
        if self.fail is not None:
            raise self.fail
        return self.html


@pytest.fixture
async def store(tmp_path):
    async with WatchStore(tmp_path / "watches.sqlite3") as opened:
        yield opened


class TestStore:
    async def test_add_and_list(self, store):
        await store.add(1, HASH, 1, name="ნუროფენი", available=False, best_price=None)
        mine = await store.for_user(1)

        assert len(mine) == 1
        assert mine[0].medicine == HASH
        assert mine[0].available is False

    async def test_price_survives_the_roundtrip(self, store):
        await store.add(1, HASH, 1, name="", available=True, best_price=Decimal("7.85"))
        assert (await store.for_user(1))[0].best_price == Decimal("7.85")

    async def test_same_medicine_in_another_city_is_a_separate_watch(self, store):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        await store.add(1, HASH, 5, name="", available=False, best_price=None)
        assert len(await store.for_user(1)) == 2

    async def test_subscribing_twice_does_not_duplicate(self, store):
        for _ in range(2):
            await store.add(1, HASH, 1, name="", available=False, best_price=None)
        assert await store.count_for(1) == 1

    async def test_limit_per_user(self, store):
        for number in range(MAX_PER_USER):
            await store.add(1, f"{number:032X}", 1, name="", available=False, best_price=None)

        added = await store.add(1, "F" * 32, 1, name="", available=False, best_price=None)
        assert added is False
        assert await store.count_for(1) == MAX_PER_USER

    async def test_limit_is_per_user_not_global(self, store):
        for number in range(MAX_PER_USER):
            await store.add(1, f"{number:032X}", 1, name="", available=False, best_price=None)

        assert await store.add(2, HASH, 1, name="", available=False, best_price=None)

    async def test_resubscribing_at_the_limit_is_allowed(self, store):
        # Обновление существующей подписки не должно упираться в лимит.
        for number in range(MAX_PER_USER):
            await store.add(1, f"{number:032X}", 1, name="", available=False, best_price=None)

        assert await store.add(1, "0" * 32, 1, name="", available=True, best_price=None)

    async def test_remove(self, store):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)

        assert await store.remove(1, HASH, 1) is True
        assert await store.for_user(1) == []

    async def test_removing_someone_elses_watch_does_nothing(self, store):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)

        assert await store.remove(2, HASH, 1) is False
        assert await store.count_for(1) == 1

    async def test_fresh_watch_is_not_due(self, store):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        assert await store.due() == []

    async def test_old_watch_is_due(self, store):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        assert len(await store.due(every=timedelta(seconds=-1))) == 1

    async def test_touch_marks_the_attempt(self, store):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        [pending] = await store.due(every=timedelta(seconds=-1))

        await store.touch(pending)
        assert await store.due() == []

    async def test_survives_reopening(self, tmp_path):
        path = tmp_path / "reopen.sqlite3"
        async with WatchStore(path) as first:
            await first.add(1, HASH, 1, name="ნუროფენი", available=True,
                            best_price=Decimal("7.85"))

        async with WatchStore(path) as second:
            assert (await second.for_user(1))[0].best_price == Decimal("7.85")


class TestDecide:
    def test_appeared(self):
        assert decide(watch(available=False), STOCKS) == APPEARED

    def test_still_absent_is_silent(self):
        assert decide(watch(available=False), []) is None

    def test_still_available_at_the_same_price_is_silent(self):
        assert decide(watch(available=True, best_price=Decimal("7.85")), STOCKS) is None

    def test_cheaper(self):
        before = watch(available=True, best_price=Decimal("9.00"))
        assert decide(before, STOCKS) == CHEAPER

    def test_more_expensive_is_silent(self):
        # Про подорожание молчим: обрадовать нечем, а сообщение раздражает.
        before = watch(available=True, best_price=Decimal("1.00"))
        assert decide(before, STOCKS) is None

    def test_disappearing_is_silent(self):
        # С этим человек всё равно ничего не сделает.
        assert decide(watch(available=True, best_price=Decimal("7.85")), []) is None

    def test_appeared_wins_even_without_prices(self):
        # Наличие важнее цены: препарат есть, хоть цена и не указана.
        priceless = [s for s in STOCKS if s.price is None]
        assert priceless, "в фикстуре есть строка без цены"
        assert decide(watch(available=False), priceless) == APPEARED

    def test_best_price_ignores_missing_prices(self):
        assert best_price(STOCKS) == Decimal("7.85")

    def test_best_price_of_nothing(self):
        assert best_price([]) is None


NOW = timedelta(seconds=-1)
"""Порог «просрочено сразу»: иначе свежая подписка не попадёт в выборку."""


class TestCheckOnce:
    async def test_notifies_once_and_remembers(self, store, tmp_path):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        client = FakeClient()

        async with StockCache(tmp_path / "s.sqlite3") as cache:
            news = await check_once(client, cache, store, every=NOW)
            assert [reason for _w, reason, _s in news] == [APPEARED]

            # Второй обход по тем же данным писать уже не должен.
            assert await check_once(client, cache, store, every=NOW) == []

    async def test_price_drop_is_reported_after_the_first_check(self, store, tmp_path):
        await store.add(1, HASH, 1, name="", available=True, best_price=Decimal("9.00"))

        async with StockCache(tmp_path / "s.sqlite3") as cache:
            news = await check_once(FakeClient(), cache, store, every=NOW)

        assert [reason for _w, reason, _s in news] == [CHEAPER]

    async def test_site_failure_does_not_lose_the_watch(self, store, tmp_path):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        client = FakeClient()
        client.fail = MisUnavailable("нет связи")

        async with StockCache(tmp_path / "s.sqlite3") as cache:
            assert await check_once(client, cache, store, every=NOW) == []

        assert await store.count() == 1, "подписка должна остаться"

    async def test_failed_check_is_not_retried_immediately(self, store, tmp_path):
        # Иначе лежащий сайт будет долбиться по кругу каждые десять минут.
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        client = FakeClient()
        client.fail = MisUnavailable("нет связи")

        async with StockCache(tmp_path / "s.sqlite3") as cache:
            await check_once(client, cache, store, every=NOW)
            await check_once(client, cache, store)

        assert len(client.calls) == 1

    async def test_nothing_due_means_no_requests(self, store, tmp_path):
        await store.add(1, HASH, 1, name="", available=False, best_price=None)
        client = FakeClient()

        async with StockCache(tmp_path / "s.sqlite3") as cache:
            assert await check_once(client, cache, store) == []
        assert client.calls == []

    async def test_batch_limits_the_walk(self, store, tmp_path):
        for number in range(5):
            await store.add(1, f"{number:032X}", 1, name="", available=False, best_price=None)

        async with StockCache(tmp_path / "s.sqlite3") as cache:
            client = FakeClient()
            await check_once(client, cache, store, batch=2, every=NOW)

        assert len(client.calls) == 2
