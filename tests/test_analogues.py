"""Тесты аналогов: разбор карточки вещества и сбор списка препаратов."""

from pathlib import Path
from typing import List

import pytest

from misbot.analogues import find_analogues
from misbot.mis_client import MisUnavailable
from misbot.parser import ParseError, parse_generic_name, parse_medicine_card

FIXTURES = Path(__file__).parent / "fixtures"
CARD = (FIXTURES / "generic_card_ibuprofen.html").read_text(encoding="utf-8")
LIST = (FIXTURES / "generic_medicines_ibuprofen.html").read_text(encoding="utf-8")

GENERIC_HASH = "4EE68ED70E9E6CBB078403F849E5BB8E"


class FakeClient:
    def __init__(self, card: str = CARD, listing: str = LIST) -> None:
        self.card = card
        self.listing = listing
        self.cards: List[str] = []
        self.listings: List[str] = []
        self.fail: Exception = None

    async def generic_card(self, generic_hash: str) -> str:
        self.cards.append(generic_hash)
        if self.fail is not None:
            raise self.fail
        return self.card

    async def medicines_by_generic(self, latin_name: str) -> str:
        self.listings.append(latin_name)
        return self.listing


class TestParseGenericName:
    def test_takes_the_latin_name(self):
        assert parse_generic_name(CARD) == "Ibuprofen"

    def test_reads_the_link_not_the_text(self):
        # Текст ссылки бывает грузинским, а ручке нужна именно латиница.
        html = '<a href="./mis_genmed.mis?g=Paracetamol">პარაცეტამოლი</a>'
        assert parse_generic_name(html) == "Paracetamol"

    def test_percent_encoding_is_decoded(self):
        html = '<a href="./mis_genmed.mis?g=Acetylsalicylic%20acid">x</a>'
        assert parse_generic_name(html) == "Acetylsalicylic acid"

    def test_plus_is_a_space(self):
        html = '<a href="./mis_genmed.mis?g=Ibuprofen+Codeine">x</a>'
        assert parse_generic_name(html) == "Ibuprofen Codeine"

    def test_missing_link_raises(self):
        with pytest.raises(ParseError):
            parse_generic_name("<html><body>ничего похожего</body></html>")


class TestParseMedicineCard:
    CARD = (FIXTURES / "medicine_card_cytarabine.html").read_text(encoding="utf-8")
    SEARCH_NAME = (
        "ციტარაბინი LKM 1000მგ ლიოფილიზატი "
        "საინექციო ხსნარის მოსამზადებლად ფლაკონი #1"
    )

    def test_assembles_the_name_from_the_fields(self):
        assert parse_medicine_card(self.CARD) == self.SEARCH_NAME

    def test_matches_the_search_result_exactly(self):
        # Иначе название подписки поменялось бы после первой фоновой проверки.
        assert parse_medicine_card(self.CARD) == self.SEARCH_NAME

    def test_empty_card_raises(self):
        with pytest.raises(ParseError):
            parse_medicine_card("<html><body>ничего</body></html>")

    def test_missing_count_is_not_a_problem(self):
        html = (
            "<table>"
            "<tr><td><b>დასახელება:</b></td><td>ასპირინი</td></tr>"
            "<tr><td><b>დოზა:</b></td><td>100მგ</td></tr>"
            "</table>"
        )
        assert parse_medicine_card(html) == "ასპირინი 100მგ"


class TestFindAnalogues:
    async def test_two_requests_and_a_list(self):
        client = FakeClient()
        generic, medicines = await find_analogues(client, GENERIC_HASH)

        assert generic == "Ibuprofen"
        assert client.cards == [GENERIC_HASH]
        assert client.listings == ["Ibuprofen"], "название взято из карточки"
        assert len(medicines) == 208

    async def test_analogues_are_real_medicines(self):
        _generic, medicines = await find_analogues(FakeClient(), GENERIC_HASH)
        first = medicines[0]

        assert first.hash
        assert first.name

    async def test_hashes_are_unique(self):
        _generic, medicines = await find_analogues(FakeClient(), GENERIC_HASH)
        assert len({m.hash for m in medicines}) == len(medicines)

    async def test_site_failure_propagates(self):
        client = FakeClient()
        client.fail = MisUnavailable("нет связи")

        with pytest.raises(MisUnavailable):
            await find_analogues(client, GENERIC_HASH)

    async def test_broken_card_raises_before_the_second_request(self):
        client = FakeClient(card="<html><body>всё поменялось</body></html>")

        with pytest.raises(ParseError):
            await find_analogues(client, GENERIC_HASH)
        assert client.listings == [], "за списком идти незачем, названия нет"
