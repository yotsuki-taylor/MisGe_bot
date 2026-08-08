"""Тесты текстов бота. Ни сети, ни телеграма."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from misbot import formatting as fmt
from misbot.models import Medicine, Stock
from misbot.parser import parse_pharmacies, parse_pharmacy_card, parse_search

FIXTURES = Path(__file__).parent / "fixtures"

TELEGRAM_MESSAGE_LIMIT = 4096


def stock(**overrides) -> Stock:
    defaults = dict(
        medicine_name="ნუროფენი",
        country="ნიდერლანდები",
        company="რექით ბენქაიზერ",
        price=Decimal("7.85"),
        expiry=date(2028, 1, 1),
        pharmacy_id=334,
        pharmacy_name="აფთიაქი 334",
        round_the_clock=False,
        updated=date.today(),
        city="თბილისი",
        district="საბურთალო",
        subdistrict="",
    )
    defaults.update(overrides)
    return Stock(**defaults)


@pytest.fixture(scope="module")
def medicines():
    return parse_search((FIXTURES / "search_nurofen.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def stocks():
    return parse_pharmacies(
        (FIXTURES / "pharmacies_nurofen_tbilisi.html").read_text(encoding="utf-8")
    )


class TestMedicinesPage:
    def test_numbering_continues_across_pages(self, medicines):
        text, buttons = fmt.medicines_page(medicines, fmt.MEDICINES_PER_PAGE, "Тбилиси")
        assert "<b>9.</b>" in text
        assert buttons[0][0] == "9"

    def test_buttons_carry_the_medicine_hash(self, medicines):
        _, buttons = fmt.medicines_page(medicines, 0, "Тбилиси")
        assert buttons[0][1] == medicines[0].hash

    def test_last_page_is_not_padded(self, medicines):
        offset = len(medicines) - 2
        _, buttons = fmt.medicines_page(medicines, offset, "Тбилиси")
        assert len(buttons) == 2

    def test_names_are_shown_in_cyrillic(self, medicines):
        text, _ = fmt.medicines_page(medicines, 0, "Тбилиси")
        assert "Нурофен" in text
        assert "ნურ" not in text

    def test_dosage_form_is_translated_not_transliterated(self, medicines):
        text, _ = fmt.medicines_page(medicines, 0, "Тбилиси")
        assert "таблетки в оболочке" in text
        assert "шемогарсули аби" not in text

    def test_pack_size_is_readable(self, medicines):
        text, _ = fmt.medicines_page(medicines, 0, "Тбилиси")
        assert "16 шт." in text

    def test_fits_the_telegram_limit(self, medicines):
        text, _ = fmt.medicines_page(medicines, 0, "Тбилиси")
        assert len(text) < TELEGRAM_MESSAGE_LIMIT

    def test_prescription_only_is_marked(self):
        by_prescription = Medicine(
            hash="A" * 32, name="ტესტი", generic="", generic_hash=None,
            country="", company="", registration="",
            dispensing="II ჯგუფი, გაიცემა ფორმა №3 რეცეპტით",
        )
        text, _ = fmt.medicines_page([by_prescription], 0, "Тбилиси")
        assert "по рецепту" in text

    def test_over_the_counter_is_not_marked(self):
        otc = Medicine(
            hash="A" * 32, name="ტესტი", generic="", generic_hash=None,
            country="", company="", registration="",
            dispensing="III ჯგუფი, გაიცემა რეცეპტის გარეშე",
        )
        text, _ = fmt.medicines_page([otc], 0, "Тбилиси")
        assert "по рецепту" not in text


class TestStocksMessage:
    def test_cheapest_comes_first(self, stocks):
        text = fmt.stocks_message(stocks, "Тбилиси")
        assert text.index("7.85") < text.index("8.40")

    def test_batches_of_one_pharmacy_are_merged(self, stocks):
        # В фикстуре аптека 334 отдаёт две строки по 7.85 — разные партии.
        text = fmt.stocks_message(stocks, "Тбилиси")
        assert text.count("7.85") == 1

    def test_missing_price_is_not_shown_as_zero(self, stocks):
        text = fmt.stocks_message(stocks, "Тбилиси")
        assert "0.00" not in text

    def test_update_date_is_always_present(self, stocks):
        text = fmt.stocks_message(stocks, "Тбилиси")
        assert text.count("обновлено") >= 1

    def test_stale_stock_is_flagged(self):
        old = stock(updated=date.today() - timedelta(days=400))
        assert "⚠️" in fmt.stocks_message([old], "Тбилиси")

    def test_fresh_stock_is_not_flagged(self):
        assert "⚠️" not in fmt.stocks_message([stock()], "Тбилиси")

    def test_round_the_clock_is_shown(self):
        assert "круглосуточно" in fmt.stocks_message([stock(round_the_clock=True)], "Тбилиси")

    def test_empty_result_suggests_another_city(self):
        text = fmt.stocks_message([], "Батуми")
        assert "Батуми" in text
        assert "/city" in text

    def test_disclaimer_and_source_are_attached(self, stocks):
        text = fmt.stocks_message(stocks, "Тбилиси")
        assert fmt.DISCLAIMER in text
        assert "mis.ge" in text

    def test_fits_the_telegram_limit(self, stocks):
        assert len(fmt.stocks_message(stocks * 20, "Тбилиси")) < TELEGRAM_MESSAGE_LIMIT

    def test_html_from_the_site_is_escaped(self):
        injected = stock(pharmacy_name="<b>аптека</b> & co")
        text = fmt.stocks_message([injected], "Тбилиси")
        assert "&lt;b&gt;" in text
        assert "&amp;" in text


class TestAddresses:
    @staticmethod
    def card(**overrides):
        pharmacy = parse_pharmacy_card(
            (FIXTURES / "pharmacy_card_334.html").read_text(encoding="utf-8"), 334
        )
        return replace(pharmacy, **overrides) if overrides else pharmacy

    def test_street_is_shown_in_the_original_script(self):
        # Улицу сличают с табличкой на доме — транслит и латиница тут мешают.
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert "ვაჟა-ფშაველას გამზ. 6" in text
        assert "важа-фшавелас" not in text

    def test_district_next_to_the_street_stays_in_cyrillic(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert "Сабуртало" in text

    def test_city_and_district_are_not_repeated_in_the_address(self):
        # Сайт склеивает адрес как «თბილისი საბურთალო … ვაჟა-ფშაველას გამზ. 6».
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert "თბილისი" not in text
        assert text.count("Сабуртало") == 1

    def test_address_links_to_the_map(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert 'href="https://maps.google.com/?q=41.7' in text

    def test_landmark_stays_in_the_original_script(self):
        # Ориентир показывают прохожему или таксисту — транслит тут бесполезен.
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert "არქივის პირდაპირ" in text
        assert "аркивис" not in text

    def test_hours_and_phone_are_shown(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert "9.00-21.30 ежедневно" in text
        assert "032 2 387646" in text

    def test_weekday_shorthands_are_translated(self):
        # «შაბ/9.00-15.00» — словарь должен сработать внутри токена со слешем.
        card = self.card(hours="9.00-18.00; შაბ/9.00-15.00; კვ/დასვენება")
        text = fmt.stocks_message([stock()], "Тбилиси", {334: card})
        assert "сб/9.00-15.00" in text
        assert "вс/выходной" in text

    def test_brand_is_shown_in_latin_with_the_sign_in_brackets(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card()})
        assert "Pharmagidi Gea (ფარმაგიდი გეა)" in text
        assert "фармагиди" not in text

    def test_without_a_brand_the_legal_name_is_used(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card(brand="")})
        assert "გეა" in text

    def test_numbered_pharmacy_label_is_romanised_too(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {})
        assert "Aptiaqi 334 (აფთიაქი 334)" in text

    def test_falls_back_to_the_district_when_the_card_is_missing(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {})
        assert "Сабуртало" in text
        assert "გამზ." not in text

    def test_empty_address_falls_back_too(self):
        text = fmt.stocks_message([stock()], "Тбилиси", {334: self.card(address="")})
        assert "Сабуртало" in text

    def test_map_url_is_escaped(self):
        bad = self.card(map_url='" onclick="alert(1)')
        assert 'onclick="alert' not in fmt.stocks_message([stock()], "Тбилиси", {334: bad})

    def test_fits_the_telegram_limit_with_addresses(self, stocks):
        cards = {stock_.pharmacy_id: self.card(id=stock_.pharmacy_id) for stock_ in stocks}
        assert len(fmt.stocks_message(stocks, "Тбилиси", cards)) < TELEGRAM_MESSAGE_LIMIT


class TestPharmacyLabel:
    def test_latin_first_original_in_brackets(self):
        assert fmt.pharmacy_label("ავერსი") == "Aversi (ავერსი)"

    def test_latin_names_are_left_alone(self):
        # Скобки повторили бы ровно то же самое.
        assert fmt.pharmacy_label("PSP") == "PSP"

    def test_digits_survive(self):
        assert fmt.pharmacy_label("აფთიაქი 334") == "Aptiaqi 334 (აფთიაქი 334)"

    def test_empty_name(self):
        assert fmt.pharmacy_label("") == ""

    def test_romanisation_can_be_switched_off(self):
        assert fmt.pharmacy_label("ავერსი", lambda text: text) == "ავერსი"


class TestShownStocks:
    def test_matches_what_the_message_shows(self, stocks):
        shown = fmt.shown_stocks(stocks)
        text = fmt.stocks_message(stocks, "Тбилиси")

        assert len(shown) <= fmt.STOCKS_SHOWN
        for item in shown:
            assert str(item.price or "") in text or item.price is None

    def test_is_sorted_by_price(self, stocks):
        prices = [s.price for s in fmt.shown_stocks(stocks) if s.price is not None]
        assert prices == sorted(prices)


class TestStaticTexts:
    @pytest.mark.parametrize(
        "text",
        [fmt.greeting(), fmt.help_text(), fmt.about_text("https://t.me/bot")],
    )
    def test_mention_the_disclaimer(self, text):
        assert fmt.DISCLAIMER in text

    def test_about_warns_about_stale_data_and_privacy(self):
        text = fmt.about_text("https://t.me/bot")
        assert "Дату обновления" in text
        assert "не сохраняются" in text

    def test_user_query_is_escaped(self):
        assert "<script>" not in fmt.nothing_found("<script>")
