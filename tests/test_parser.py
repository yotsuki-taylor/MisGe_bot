"""Тесты парсера на сохранённых страницах mis.ge.

Фикстуры сняты 2026-08-07 командой
    python -m misbot.cli nurofen --pick 1 --city 1 --save-html tests/fixtures
Если сайт поменяет вёрстку, снимите их заново и посмотрите, что отвалилось.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from misbot.parser import ParseError, parse_locations, parse_pharmacies, parse_search

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def search_html() -> str:
    return fixture("search_nurofen.html")


@pytest.fixture(scope="module")
def pharmacies_html() -> str:
    return fixture("pharmacies_nurofen_tbilisi.html")


class TestParseSearch:
    def test_finds_every_row(self, search_html):
        assert len(parse_search(search_html)) == 29

    def test_reads_all_columns(self, search_html):
        first = parse_search(search_html)[0]
        assert first.hash == "8D04DC19D9A1E25F51B8F06BE3B2E0EE"
        assert first.name == "ნუროფენ ექსპრესი 200მგ შემოგარსული აბი - #16"
        assert first.generic == "იბუპროფენი"
        assert first.generic_hash == "4EE68ED70E9E6CBB078403F849E5BB8E"
        assert first.country == "ნიდერლანდები"
        assert first.company == "რექით ბენქაიზერ"
        assert "რ-045770" in first.registration
        assert "რეცეპტის გარეშე" in first.dispensing

    def test_hashes_are_unique(self, search_html):
        medicines = parse_search(search_html)
        assert len({m.hash for m in medicines}) == len(medicines)

    def test_empty_result_is_not_an_error(self):
        assert parse_search(fixture("search_empty.html")) == []

    def test_broken_markup_raises(self):
        with pytest.raises(ParseError):
            parse_search("<html><body><p>привет</p></body></html>")

    def test_empty_table_raises(self):
        html = '<table id="table_medikamentebi"><tbody></tbody></table>'
        with pytest.raises(ParseError):
            parse_search(html)


class TestParsePharmacies:
    def test_finds_every_row(self, pharmacies_html):
        assert len(parse_pharmacies(pharmacies_html)) == 11

    def test_reads_all_columns(self, pharmacies_html):
        first = parse_pharmacies(pharmacies_html)[0]
        assert first.medicine_name == "ნუროფენ ექსპრესი 200მგ შემოგარსული აბი - #16"
        assert first.price == Decimal("7.85")
        assert first.expiry == date(2026, 1, 11)
        assert first.pharmacy_id == 334
        assert first.pharmacy_name == "აფთიაქი 334"
        assert first.round_the_clock is False
        assert first.updated == date(2026, 8, 4)
        assert first.city == "თბილისი"
        assert first.district == "საბურთალო"
        assert first.subdistrict == "M სამედიცინო ინსტიტუტი"

    def test_zero_price_means_unknown(self, pharmacies_html):
        prices = [s.price for s in parse_pharmacies(pharmacies_html)]
        assert None in prices, "строка с 0.00 должна давать None"
        assert all(p is None or p > 0 for p in prices)

    def test_placeholder_expiry_is_dropped(self, pharmacies_html):
        # У части строк срок годности стоит как 1900-01-01 — это «нет данных».
        stocks = parse_pharmacies(pharmacies_html)
        assert all(s.expiry is None or s.expiry.year > 1900 for s in stocks)

    def test_round_the_clock_flag(self, pharmacies_html):
        night = [s for s in parse_pharmacies(pharmacies_html) if s.round_the_clock]
        assert night, "в Тбилиси есть круглосуточные аптеки"
        assert all("სადღეღამისო" not in s.pharmacy_name for s in night)

    def test_empty_result_is_not_an_error(self):
        # Если в городе препарата нет, сайт рисует таблицу с пустым tbody
        # и подписывает «მოიძებნა 0 აფთიაქი».
        assert parse_pharmacies(fixture("pharmacies_empty.html")) == []

    def test_empty_table_without_the_counter_raises(self):
        html = '<table id="table_medikamentebi"><tbody></tbody></table>'
        with pytest.raises(ParseError):
            parse_pharmacies(html)

    def test_medicine_counter_is_not_mistaken_for_the_pharmacy_one(self):
        # На странице аптек две подписи: сколько наименований и сколько аптек.
        # Ноль аптек при ненулевых наименованиях — всё ещё пустой ответ.
        html = ('<div>მოიძებნა 1 დასახელება.</div>'
                '<table id="table_medikamentebi"><tbody></tbody></table>'
                '<div>მოიძებნა 0 აფთიაქი.</div>')
        assert parse_pharmacies(html) == []

    def test_broken_markup_raises(self):
        with pytest.raises(ParseError):
            parse_pharmacies("<html><body></body></html>")


class TestParseLocations:
    def test_reads_all_three_dictionaries(self, search_html):
        locations = parse_locations(search_html)
        assert len(locations.cities) == 21
        assert len(locations.districts) > 40
        assert len(locations.subdistricts) > 30

    def test_tbilisi_is_city_one(self, search_html):
        cities = {c.name: c.id for c in parse_locations(search_html).cities}
        assert cities["თბილისი"] == 1
        assert cities["ქუთაისი"] == 2
        assert cities["ბათუმი"] == 5

    def test_everywhere_option_is_dropped(self, search_html):
        locations = parse_locations(search_html)
        assert all(c.id != 0 for c in locations.cities)

    def test_missing_selects_raise(self):
        with pytest.raises(ParseError):
            parse_locations("<html><body></body></html>")
