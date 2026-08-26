"""Тесты подбора запроса. Вместо сайта — заглушка, сети не требуют."""

from pathlib import Path
from typing import Dict, List

import pytest

from misbot.parser import QueryTooShort
from misbot.search import AS_IS, BRAND, INN, PREFIX, TRANSLIT, find_medicines

FIXTURES = Path(__file__).parent / "fixtures"
FOUND = (FIXTURES / "search_nurofen.html").read_text(encoding="utf-8")
EMPTY = (FIXTURES / "search_empty.html").read_text(encoding="utf-8")


class FakeClient:
    """Отвечает выдачей только на заранее оговорённые запросы."""

    def __init__(self, answers: Dict[str, str]) -> None:
        self.answers = answers
        self.calls: List[tuple] = []

    async def search(self, query, *, starts_with=True, by_generic=False):
        self.calls.append((query, by_generic))
        key = f"{query}!inn" if by_generic else query
        return self.answers.get(key, EMPTY)

    @property
    def queries(self) -> List[str]:
        return [query for query, _ in self.calls]


class TestFindMedicines:
    async def test_latin_goes_as_is(self):
        client = FakeClient({"nurofen": FOUND})
        outcome = await find_medicines(client, "nurofen")
        assert outcome.found
        assert outcome.strategy == AS_IS
        assert client.queries == ["nurofen"]

    async def test_georgian_goes_as_is(self):
        client = FakeClient({"ნუროფენი": FOUND})
        outcome = await find_medicines(client, "ნუროფენი")
        assert outcome.strategy == AS_IS
        assert client.queries == ["ნუროფენი"]

    async def test_cyrillic_is_transliterated(self):
        client = FakeClient({"nurofen": FOUND})
        outcome = await find_medicines(client, "нурофен")
        assert outcome.found
        assert outcome.query == "nurofen"
        assert outcome.strategy == TRANSLIT

    async def test_stops_at_the_first_hit(self):
        client = FakeClient({"diclofenac": FOUND})
        await find_medicines(client, "диклофенак")
        assert client.queries == ["diclofenac"]

    async def test_walks_candidates_until_something_matches(self):
        # Верное написание — второй кандидат, первый должен быть отброшен.
        client = FakeClient({"heparin": FOUND})
        outcome = await find_medicines(client, "гепарин")
        assert outcome.query == "heparin"
        assert client.queries[0] == "geparin"

    async def test_falls_back_to_a_truncated_prefix(self):
        # Хвост латинского названия не совпал с русским — выручает префикс.
        client = FakeClient({"ceftri": FOUND})
        outcome = await find_medicines(client, "цефтриаксон")
        assert outcome.found
        assert outcome.strategy == PREFIX
        assert outcome.query == "ceftri"

    async def test_falls_back_to_inn(self):
        client = FakeClient({"ibuprofen!inn": FOUND})
        outcome = await find_medicines(client, "ибупрофен")
        assert outcome.found
        assert outcome.strategy == INN
        assert client.calls[-1] == ("ibuprofen", True)

    async def test_respects_the_attempt_budget(self):
        client = FakeClient({})
        outcome = await find_medicines(client, "хлоргексидин", max_attempts=4)
        assert not outcome.found
        assert len(client.calls) <= 4

    async def test_never_repeats_a_request(self):
        # Одна строка может уйти дважды — по названию и по МНН, это разные
        # запросы. Повторяться не должна именно пара «строка + режим».
        client = FakeClient({})
        await find_medicines(client, "аспирин")
        assert len(client.calls) == len(set(client.calls))
        assert client.queries.count("aspirin") == 2

    async def test_short_query_is_rejected_without_a_request(self):
        client = FakeClient({})
        with pytest.raises(QueryTooShort):
            await find_medicines(client, "но")
        assert client.calls == []


class TestKnownBrands:
    async def test_the_known_spelling_goes_first(self):
        # Побуквенно вышло бы zirtec: «и» через y подбор считает экзотикой.
        client = FakeClient({"zyrtec": FOUND})
        outcome = await find_medicines(client, "зиртек")
        assert outcome.found
        assert outcome.strategy == BRAND
        assert client.queries == ["zyrtec"]

    async def test_case_and_spaces_do_not_matter(self):
        client = FakeClient({"zyrtec": FOUND})
        outcome = await find_medicines(client, "  Зиртек ")
        assert outcome.strategy == BRAND

    async def test_falls_back_to_the_generic(self):
        # Бренда в аптеках нет — по МНН найдутся аналоги.
        client = FakeClient({"cetirizin!inn": FOUND})
        outcome = await find_medicines(client, "зиртек")
        assert outcome.found
        assert outcome.strategy == INN
        assert client.queries[:2] == ["zyrtec", "cetirizin"]

    async def test_the_letter_by_letter_plan_still_runs_after(self):
        client = FakeClient({"zirtek": FOUND})
        outcome = await find_medicines(client, "зиртек")
        assert outcome.found
        assert outcome.strategy == TRANSLIT

    async def test_the_known_spelling_is_not_asked_twice(self):
        # zyrtec есть и в словаре, и среди подобранных вариантов.
        client = FakeClient({})
        await find_medicines(client, "зиртек")
        assert client.queries.count("zyrtec") == 1

    async def test_unknown_names_are_unaffected(self):
        client = FakeClient({"nurofen": FOUND})
        outcome = await find_medicines(client, "нурофен")
        assert outcome.strategy == TRANSLIT
        assert client.queries == ["nurofen"]
