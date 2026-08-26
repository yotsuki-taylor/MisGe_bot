"""Тесты словаря особых правил."""

from misbot.brands import KNOWN, lookup, normalise


class TestLookup:
    def test_finds_a_known_name(self):
        brand = lookup("зиртек")
        assert brand is not None
        assert brand.names == ("zyrtec",)

    def test_case_is_ignored(self):
        assert lookup("ЗИРТЕК") == lookup("зиртек")

    def test_spaces_are_trimmed(self):
        assert lookup("  зиртек  ") == lookup("зиртек")

    def test_unknown_name_is_none(self):
        assert lookup("нурофен") is None

    def test_empty_is_none(self):
        assert lookup("") is None


class TestNormalise:
    def test_collapses_inner_spaces(self):
        assert normalise("но   шпа") == "но шпа"

    def test_yo_reads_as_ye(self):
        # «Зелёный» и «зеленый» — одно и то же слово для словаря.
        assert normalise("зелёный") == "зеленый"


class TestDictionary:
    def test_keys_are_normalised(self):
        # Ключ, записанный с заглавной или с «ё», никогда бы не нашёлся.
        assert all(key == normalise(key) for key in KNOWN)

    def test_every_entry_has_a_spelling(self):
        assert all(brand.names for brand in KNOWN.values())

    def test_spellings_are_latin_and_lowercase(self):
        for brand in KNOWN.values():
            for name in brand.names:
                assert name == name.lower()
                assert name.isascii()
            assert brand.generic == brand.generic.lower()
            assert brand.generic.isascii()
