"""Тесты карточек аптек: разбор, кеш и добор недостающего."""

from datetime import timedelta
from pathlib import Path
from typing import Dict, List

import pytest

from misbot.cache import PharmacyCache
from misbot.mis_client import MisUnavailable
from misbot.models import Pharmacy
from misbot.parser import ParseError, parse_pharmacy_card
from misbot.pharmacies import resolve

FIXTURES = Path(__file__).parent / "fixtures"
CARD_334 = (FIXTURES / "pharmacy_card_334.html").read_text(encoding="utf-8")
CARD_581 = (FIXTURES / "pharmacy_card_581.html").read_text(encoding="utf-8")


class FakeClient:
    def __init__(self, html: str = CARD_334) -> None:
        self.html = html
        self.calls: List[int] = []
        self.fail: Exception = None

    async def pharmacy_card(self, pharmacy_id: int) -> str:
        self.calls.append(pharmacy_id)
        if self.fail is not None:
            raise self.fail
        return self.html


@pytest.fixture
async def cache(tmp_path):
    store = await PharmacyCache(tmp_path / "test.sqlite3").open()
    yield store
    await store.close()


class TestParseCard:
    def test_reads_every_field(self):
        card = parse_pharmacy_card(CARD_334, 334)

        assert card.id == 334
        assert card.legal_name == 'შპს "გეა"'
        assert card.brand == "ფარმაგიდი გეა"
        assert card.address.endswith("ვაჟა-ფშაველას გამზ. 6")
        assert card.landmark == "არქივის პირდაპირ"
        assert card.hours == "9.00-21.30 ყოველდღე"
        assert card.phone == "032 2 387646"

    def test_extracts_coordinates_from_the_map_link(self):
        latitude, longitude = parse_pharmacy_card(CARD_334, 334).coordinates
        assert 41 < latitude < 42
        assert 44 < longitude < 45

    def test_missing_brand_falls_back_to_the_legal_name(self):
        card = parse_pharmacy_card(CARD_581, 581)
        assert card.brand == ""
        assert card.display_name == card.legal_name

    def test_round_the_clock_pharmacy_has_hours(self):
        assert parse_pharmacy_card(CARD_581, 581).hours == "სადღეღამისო"

    def test_broken_markup_raises(self):
        with pytest.raises(ParseError):
            parse_pharmacy_card("<html><body>ничего</body></html>", 1)

    def test_labels_are_matched_not_positions(self):
        # Строки в карточке переставлены — разбор не должен сломаться.
        html = (
            "<table>"
            "<tr><td><b>ტელეფონი :</b></td><td></td><td>555</td></tr>"
            "<tr><td><b>მისამართი:</b></td><td></td><td>თბილისი ქუჩა 1</td></tr>"
            "</table>"
        )
        card = parse_pharmacy_card(html, 7)
        assert card.address == "თბილისი ქუჩა 1"
        assert card.phone == "555"


class TestCache:
    async def test_roundtrip(self, cache):
        card = parse_pharmacy_card(CARD_334, 334)
        await cache.put(card)

        assert (await cache.get_many([334]))[334] == card

    async def test_unknown_ids_are_absent(self, cache):
        assert await cache.get_many([999]) == {}

    async def test_survives_reopening(self, tmp_path):
        path = tmp_path / "reopen.sqlite3"
        async with PharmacyCache(path) as first:
            await first.put(parse_pharmacy_card(CARD_334, 334))

        async with PharmacyCache(path) as second:
            assert 334 in await second.get_many([334])
            assert await second.count() == 1

    async def test_stale_rows_are_ignored(self, tmp_path):
        path = tmp_path / "stale.sqlite3"
        async with PharmacyCache(path) as fresh:
            await fresh.put(parse_pharmacy_card(CARD_334, 334))

        async with PharmacyCache(path, ttl=timedelta(seconds=-1)) as expired:
            assert await expired.get_many([334]) == {}

    async def test_put_overwrites(self, cache):
        await cache.put(parse_pharmacy_card(CARD_334, 334))
        await cache.put(Pharmacy(
            id=334, legal_name="новое", brand="", address="адрес",
            landmark="", hours="", phone="", map_url="",
        ))

        assert (await cache.get_many([334]))[334].legal_name == "новое"
        assert await cache.count() == 1


class TestResolve:
    async def test_fetches_what_is_missing(self, cache):
        client = FakeClient()
        result = await resolve(client, cache, [334])

        assert client.calls == [334]
        assert result[334].brand == "ფარმაგიდი გეა"

    async def test_second_call_takes_it_from_the_cache(self, cache):
        client = FakeClient()
        await resolve(client, cache, [334])
        await resolve(client, cache, [334])

        assert client.calls == [334], "второй раз к сайту ходить не должны"

    async def test_duplicates_are_asked_once(self, cache):
        client = FakeClient()
        await resolve(client, cache, [334, 334, 334])
        assert client.calls == [334]

    async def test_respects_the_fetch_budget(self, cache):
        client = FakeClient()
        await resolve(client, cache, list(range(100, 120)), max_fetches=3)
        assert len(client.calls) == 3

    async def test_site_failure_stops_the_walk(self, cache):
        client = FakeClient()
        client.fail = MisUnavailable("нет связи")
        result = await resolve(client, cache, [1, 2, 3])

        assert result == {}
        assert len(client.calls) == 1, "если сайт лёг, остальные карточки не тянем"

    async def test_works_without_a_cache(self):
        client = FakeClient()
        result = await resolve(client, None, [334])
        assert result[334].id == 334

    async def test_empty_request_does_not_touch_anything(self, cache):
        client = FakeClient()
        assert await resolve(client, cache, []) == {}
        assert client.calls == []
