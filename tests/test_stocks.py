"""Тесты кеша остатков и выбора «кеш или сайт»."""

from datetime import timedelta
from pathlib import Path
from typing import List

import pytest

import httpx

from misbot.mis_client import MisBlocked, MisUnavailable, _failure
from misbot.parser import ParseError, parse_pharmacies, parse_search
from misbot.stock_cache import StockCache
from misbot.stocks import MAX_COUNTED, count_all, count_by_medicine, find_stocks, in_stock_first

FIXTURES = Path(__file__).parent / "fixtures"
PHARMACIES = (FIXTURES / "pharmacies_nurofen_tbilisi.html").read_text(encoding="utf-8")
NO_PHARMACIES = (FIXTURES / "pharmacies_empty.html").read_text(encoding="utf-8")

HASH = "8D04DC19D9A1E25F51B8F06BE3B2E0EE"


class FakeClient:
    def __init__(self, html: str = PHARMACIES) -> None:
        self.html = html
        self.calls: List[tuple] = []
        self.fail: Exception = None

    async def pharmacies(self, hashes, *, city=0, district=0, subdistrict=0) -> str:
        self.calls.append((tuple(hashes), city, district, subdistrict))
        if self.fail is not None:
            raise self.fail
        return self.html


@pytest.fixture
async def cache(tmp_path):
    async with StockCache(tmp_path / "stocks.sqlite3") as opened:
        yield opened


class TestStockCache:
    async def test_roundtrip(self, cache):
        await cache.put(HASH, PHARMACIES, city=1)
        cached = await cache.get(HASH, city=1)

        assert cached is not None
        assert cached.fresh
        assert cached.html == PHARMACIES

    async def test_unknown_key_is_empty(self, cache):
        assert await cache.get(HASH, city=1) is None

    async def test_cities_do_not_share_a_record(self, cache):
        await cache.put(HASH, PHARMACIES, city=1)
        assert await cache.get(HASH, city=5) is None

    async def test_districts_do_not_share_a_record(self, cache):
        await cache.put(HASH, PHARMACIES, city=1, district=75)
        assert await cache.get(HASH, city=1) is None

    async def test_expired_record_is_returned_but_marked(self, tmp_path):
        path = tmp_path / "expired.sqlite3"
        async with StockCache(path) as fresh:
            await fresh.put(HASH, PHARMACIES, city=1)

        async with StockCache(path, ttl=timedelta(seconds=-1)) as expired:
            cached = await expired.get(HASH, city=1)
            assert cached is not None
            assert cached.fresh is False

    async def test_put_replaces(self, cache):
        await cache.put(HASH, PHARMACIES, city=1)
        await cache.put(HASH, NO_PHARMACIES, city=1)

        assert (await cache.get(HASH, city=1)).html == NO_PHARMACIES
        assert await cache.count() == 1

    async def test_prune_drops_only_the_very_old(self, cache):
        await cache.put(HASH, PHARMACIES, city=1)

        assert await cache.prune() == 0, "свежее трогать нельзя"
        assert await cache.prune(keep=timedelta(seconds=-1)) == 1
        assert await cache.count() == 0

    async def test_survives_reopening(self, tmp_path):
        path = tmp_path / "reopen.sqlite3"
        async with StockCache(path) as first:
            await first.put(HASH, PHARMACIES, city=1)

        async with StockCache(path) as second:
            assert (await second.get(HASH, city=1)).html == PHARMACIES

    async def test_closed_cache_does_not_raise(self, tmp_path):
        cache = StockCache(tmp_path / "closed.sqlite3")
        assert await cache.get(HASH) is None
        await cache.put(HASH, PHARMACIES)
        assert await cache.count() == 0


class TestCountByMedicine:
    @staticmethod
    def medicines():
        return parse_search((FIXTURES / "search_nurofen.html").read_text(encoding="utf-8"))

    async def test_counts_distinct_pharmacies(self, cache):
        # Строк в фикстуре 11, но аптеки 334 и 406 отдают по две партии одного
        # препарата. Считаем аптеки, а не строки: их 9.
        [first] = [m for m in self.medicines() if m.hash == HASH]
        counts = await count_by_medicine(FakeClient(), cache, [first], city=1)

        assert counts[HASH] == 9
        assert len(parse_pharmacies(PHARMACIES)) == 11, "строк действительно больше"

    async def test_medicines_without_stock_get_zero(self, cache):
        page = self.medicines()[:8]
        counts = await count_by_medicine(FakeClient(), cache, page, city=1)

        assert set(counts) == {m.hash for m in page}
        assert counts[page[1].hash] == 0, "у этой формы выпуска наличия нет"

    async def test_one_request_for_the_whole_page(self, cache):
        client = FakeClient()
        await count_by_medicine(client, cache, self.medicines()[:8], city=1)

        assert len(client.calls) == 1
        assert len(client.calls[0][0]) == 8

    async def test_never_asks_for_more_than_the_site_accepts(self, cache):
        client = FakeClient()
        await count_by_medicine(client, cache, self.medicines(), city=1)

        assert len(client.calls[0][0]) <= 13, "на 14-м хеше сайт молча отдаёт пустоту"

    async def test_second_page_view_is_free(self, cache):
        client = FakeClient()
        page = self.medicines()[:8]
        await count_by_medicine(client, cache, page, city=1)
        await count_by_medicine(client, cache, page, city=1)

        assert len(client.calls) == 1

    async def test_another_city_is_counted_separately(self, cache):
        client = FakeClient()
        page = self.medicines()[:8]
        await count_by_medicine(client, cache, page, city=1)
        await count_by_medicine(client, cache, page, city=5)

        assert len(client.calls) == 2

    async def test_empty_page_asks_nothing(self, cache):
        client = FakeClient()
        assert await count_by_medicine(client, cache, [], city=1) == {}
        assert client.calls == []

    async def test_works_without_a_cache(self):
        counts = await count_by_medicine(FakeClient(), None, self.medicines()[:2], city=1)
        assert counts[HASH] == 9


class TestFindStocks:
    async def test_first_call_goes_to_the_site(self, cache):
        client = FakeClient()
        stocks = await find_stocks(client, cache, HASH, city=1)

        assert len(stocks) == 11
        assert client.calls == [((HASH,), 1, 0, 0)]

    async def test_second_call_is_served_from_the_cache(self, cache):
        client = FakeClient()
        await find_stocks(client, cache, HASH, city=1)
        stocks = await find_stocks(client, cache, HASH, city=1)

        assert len(stocks) == 11
        assert len(client.calls) == 1, "второй раз на сайт ходить не должны"

    async def test_another_city_is_fetched_separately(self, cache):
        client = FakeClient()
        await find_stocks(client, cache, HASH, city=1)
        await find_stocks(client, cache, HASH, city=5)

        assert len(client.calls) == 2

    async def test_expired_cache_is_refetched(self, tmp_path):
        client = FakeClient()
        path = tmp_path / "stale.sqlite3"
        async with StockCache(path) as fresh:
            await find_stocks(client, fresh, HASH, city=1)

        async with StockCache(path, ttl=timedelta(seconds=-1)) as expired:
            await find_stocks(client, expired, HASH, city=1)

        assert len(client.calls) == 2

    async def test_stale_cache_saves_the_answer_when_the_site_is_down(self, tmp_path):
        # Цена получасовой давности полезнее, чем «попробуйте позже».
        path = tmp_path / "fallback.sqlite3"
        async with StockCache(path) as fresh:
            await find_stocks(FakeClient(), fresh, HASH, city=1)

        broken = FakeClient()
        broken.fail = MisUnavailable("нет связи")
        async with StockCache(path, ttl=timedelta(seconds=-1)) as expired:
            stocks = await find_stocks(broken, expired, HASH, city=1)

        assert len(stocks) == 11

    async def test_site_failure_without_a_cache_still_raises(self, cache):
        client = FakeClient()
        client.fail = MisUnavailable("нет связи")

        with pytest.raises(MisUnavailable):
            await find_stocks(client, cache, HASH, city=1)

    async def test_unparsable_answer_is_not_cached(self, cache):
        # Иначе поломка сайта застряла бы в кеше на полчаса.
        client = FakeClient(html="<html><body>всё поменялось</body></html>")

        with pytest.raises(ParseError):
            await find_stocks(client, cache, HASH, city=1)
        assert await cache.count() == 0

    async def test_empty_result_is_cached_too(self, cache):
        # «Нигде нет» — тоже ответ, за ним не надо ходить дважды.
        client = FakeClient(html=NO_PHARMACIES)
        assert await find_stocks(client, cache, HASH, city=5) == []
        assert await find_stocks(client, cache, HASH, city=5) == []
        assert len(client.calls) == 1

    async def test_works_without_a_cache(self):
        client = FakeClient()
        assert len(await find_stocks(client, None, HASH, city=1)) == 11


class TestCountAll:
    @staticmethod
    def medicines():
        return parse_search((FIXTURES / "search_nurofen.html").read_text(encoding="utf-8"))

    async def test_covers_every_medicine(self, cache):
        all_of_them = self.medicines()
        counts = await count_all(FakeClient(), cache, all_of_them, city=1)

        assert set(counts) == {m.hash for m in all_of_them}

    async def test_asks_in_batches_the_site_accepts(self, cache):
        client = FakeClient()
        await count_all(client, cache, self.medicines(), city=1)

        # 29 препаратов — три пакета по тринадцать и меньше.
        assert len(client.calls) == 3
        assert all(len(call[0]) <= 13 for call in client.calls)

    async def test_a_second_run_is_free(self, cache):
        client = FakeClient()
        await count_all(client, cache, self.medicines(), city=1)
        await count_all(client, cache, self.medicines(), city=1)

        assert len(client.calls) == 3, "второй проход должен идти из кеша"

    async def test_empty_list_asks_nothing(self, cache):
        client = FakeClient()
        assert await count_all(client, cache, [], city=1) == {}
        assert client.calls == []


class TestInStockFirst:
    @staticmethod
    def medicines():
        return parse_search((FIXTURES / "search_nurofen.html").read_text(encoding="utf-8"))

    def test_available_go_up(self):
        first, second, third = self.medicines()[:3]
        counts = {first.hash: 0, second.hash: 4, third.hash: 0}

        order = in_stock_first([first, second, third], counts)

        assert order[0] is second
        assert [m.hash for m in order[1:]] == [first.hash, third.hash]

    def test_the_site_order_survives_inside_the_groups(self):
        # Рядом стоят разные фасовки одного препарата — порядок не случайный.
        page = self.medicines()[:6]
        counts = {m.hash: (2 if index % 2 else 0) for index, m in enumerate(page)}

        order = in_stock_first(page, counts)

        assert [m.hash for m in order[:3]] == [page[1].hash, page[3].hash, page[5].hash]
        assert [m.hash for m in order[3:]] == [page[0].hash, page[2].hash, page[4].hash]

    def test_without_counts_the_order_is_untouched(self):
        page = self.medicines()[:5]
        assert in_stock_first(page, None) == page
        assert in_stock_first(page, {}) == page

    def test_unknown_medicines_go_last(self):
        first, second = self.medicines()[:2]
        assert in_stock_first([first, second], {second.hash: 1})[0] is second

    def test_the_budget_is_three_requests(self):
        assert MAX_COUNTED == 39


class TestFailureKind:
    """«Не отвечает» и «не пускает» — разные поломки и лечатся по-разному."""

    @staticmethod
    def error(status: int) -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "http://www.mis.ge/mis_mobiluri.mis")
        response = httpx.Response(status, request=request)
        return httpx.HTTPStatusError("нет", request=request, response=response)

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_refusals_are_blocks(self, status):
        assert isinstance(_failure(self.error(status), "не удался"), MisBlocked)

    @pytest.mark.parametrize("status", [500, 502, 404])
    def test_other_codes_are_plain_unavailability(self, status):
        failure = _failure(self.error(status), "не удался")
        assert isinstance(failure, MisUnavailable)
        assert not isinstance(failure, MisBlocked)

    def test_network_errors_are_plain_unavailability(self):
        # У таймаута нет ответа, а значит и кода — по нему судить не о чем.
        failure = _failure(httpx.ConnectTimeout("вышло время"), "не удался")
        assert not isinstance(failure, MisBlocked)

    def test_no_error_at_all(self):
        assert isinstance(_failure(None, "не удался"), MisUnavailable)

    def test_a_block_is_still_caught_as_unavailable(self):
        # Всё, что ловит MisUnavailable, должно продолжать работать.
        assert isinstance(MisBlocked("403"), MisUnavailable)

    def test_the_status_is_kept_in_the_message(self):
        assert "403" in str(_failure(self.error(403), "не удался"))
