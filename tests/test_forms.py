"""Тесты перевода названий препаратов.

Главный тест — прогон корпуса из tests/fixtures/medicine_names.txt: 337 живых
названий, снятых с сайта 2026-08-07 по десяти препаратам. Он ловит дырки в
словаре форм выпуска — по следам вроде «аби» или «саинекцио» в переводе.
"""

from pathlib import Path

import pytest

from misbot.forms import (
    translate_company,
    translate_country,
    translate_dispensing,
    translate_generic,
    translate_medicine,
)

FIXTURES = Path(__file__).parent / "fixtures"


def corpus(name: str):
    return [
        line
        for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


CORPUS = corpus("medicine_names.txt")
COUNTRIES = corpus("countries.txt")
COMPANIES = corpus("companies.txt")
GENERICS = corpus("generics.txt")
DISPENSING = corpus("dispensing.txt")


def has_georgian(text: str) -> bool:
    return any("Ⴀ" <= char <= "ჿ" for char in text)

ARTIFACTS = (
    # Транслит этих слов означает, что форма выпуска не попала в словарь.
    "аби", "кафсула", "фхвнили", "хснари", "мосамзадеблад", "саинекцио",
    "саинфузио", "флакони", "шемогарсули", "гастрорезистентули", "сантели",
    "цветеби",
)


class TestCorpus:
    def test_corpus_is_big_enough(self):
        assert len(CORPUS) > 300

    @pytest.mark.parametrize("name", CORPUS)
    def test_no_georgian_letters_survive(self, name):
        assert not has_georgian(translate_medicine(name))

    def test_no_form_words_are_left_transliterated(self):
        missed = [
            (name, translate_medicine(name))
            for name in CORPUS
            if any(artifact in translate_medicine(name).lower() for artifact in ARTIFACTS)
        ]
        assert not missed, f"словарь форм неполон: {missed[:3]}"


class TestForms:
    @pytest.mark.parametrize(
        "georgian, expected",
        [
            ("შემოგარსული აბი", "Таблетки в оболочке"),
            ("გასტრორეზისტენტული კაფსულა", "Гастрорезистентные капсулы"),
            ("რექტალური სანთელი", "Ректальные свечи"),
            ("თვალის წვეთები", "Глазные капли"),
            ("საინექციო ხსნარი", "Раствор для инъекций"),
            ("შაქრით დაფარული აბი", "Таблетки, покрытые сахаром"),
            ("ორალური სუსპენზია", "Оральная суспензия"),
        ],
    )
    def test_common_forms(self, georgian, expected):
        assert translate_medicine(georgian) == expected

    def test_longer_phrase_wins(self):
        # «ხსნარის მოსამზადებლად» не должно съесть более длинную формулировку.
        assert translate_medicine("ფხვნილი საინექციო ხსნარის მოსამზადებლად") == (
            "Порошок для приготовления раствора для инъекций"
        )


class TestUnits:
    def test_unit_is_separated_from_the_number(self):
        assert translate_medicine("400მგ აბი").startswith("400 мг")

    def test_unit_after_a_slash_keeps_no_space(self):
        assert "100 МЕ/мл" in translate_medicine("ინსულინი 100სე/მლ საინექციო ხსნარი")

    def test_international_units(self):
        assert "40 МЕ" in translate_medicine("ინსულინი 40სე")

    def test_grams(self):
        assert "3 г" in translate_medicine("გრანულა 3გ პაკეტი")


class TestPackAndBrand:
    def test_pack_count_becomes_readable(self):
        assert translate_medicine("აბი - #48").endswith(", 48 шт.")

    def test_pack_count_without_a_dash(self):
        assert translate_medicine("ფლაკონი #1").endswith(", 1 шт.")

    def test_georgian_nominative_ending_is_dropped_from_brands(self):
        # Иначе выходит «Парацетамоли».
        assert translate_medicine("პარაცეტამოლი 500მგ აბი").startswith("Парацетамол ")

    def test_brand_words_are_capitalised(self):
        assert translate_medicine("პარაცეტამოლი ნორმონი 500მგ აბი").startswith(
            "Парацетамол Нормон"
        )

    def test_short_words_keep_their_ending(self):
        assert translate_medicine("ლეკი") == "Лек"

    def test_latin_parts_are_left_alone(self):
        assert "DF" in translate_medicine("ლიდოკაინი-DF 10% აეროზოლი")

    def test_full_name(self):
        assert translate_medicine("ნუროფენ ფორტე 400მგ შემოგარსული აბი - #48") == (
            "Нурофен форте 400 мг таблетки в оболочке, 48 шт."
        )

    def test_empty(self):
        assert translate_medicine("") == ""
        assert translate_medicine("   ") == ""


class TestCountries:
    @pytest.mark.parametrize("country", COUNTRIES)
    def test_every_country_in_the_corpus_is_translated(self, country):
        assert not has_georgian(translate_country(country))

    @pytest.mark.parametrize(
        "georgian, russian",
        [
            ("ინდოეთი", "Индия"),
            ("საქართველო", "Грузия"),
            ("დიდი ბრიტანეთი", "Великобритания"),
            ("აშშ", "США"),
            ("ნიდერლანდები", "Нидерланды"),
        ],
    )
    def test_names_are_the_usual_russian_ones(self, georgian, russian):
        assert translate_country(georgian) == russian

    def test_missing_data_becomes_empty(self):
        assert translate_country("-") == ""
        assert translate_country("") == ""


class TestDispensing:
    @pytest.mark.parametrize("mode", DISPENSING)
    def test_every_mode_in_the_corpus_is_translated(self, mode):
        assert not has_georgian(translate_dispensing(mode))

    def test_over_the_counter(self):
        assert translate_dispensing("III ჯგუფი, გაიცემა რეცეპტის გარეშე") == (
            "III группа, без рецепта"
        )

    def test_prescription_form(self):
        assert translate_dispensing("II ჯგუფი, გაიცემა ფორმა №3 რეცეპტით") == (
            "II группа, по рецепту, форма №3"
        )

    def test_emergency_exception_is_kept(self):
        result = translate_dispensing(
            "II ჯგუფი, გაიცემა ფორმა №3 რეცეპტით "
            "(გადაუდებელი დახმარებისას გაიცემა ურეცეპტოდ)"
        )
        assert result.endswith("(при неотложной помощи — без рецепта)")


class TestCompaniesAndGenerics:
    @pytest.mark.parametrize("company", COMPANIES)
    def test_companies_lose_their_georgian_letters(self, company):
        assert not has_georgian(translate_company(company))

    @pytest.mark.parametrize("generic", GENERICS)
    def test_generics_lose_their_georgian_letters(self, generic):
        assert not has_georgian(translate_generic(generic))

    def test_company_words_are_capitalised(self):
        assert translate_company("ავერსი-რაციონალი") == "Аверс-Рационал"

    def test_generic_keeps_only_the_first_capital(self):
        # Это описание, а не имя собственное.
        assert translate_generic("ხსნადი ინსულინი (ღორის მონოკომპონენტური)") == (
            "Растворимый инсулин (свиной монокомпонентный)"
        )

    def test_chemistry_is_translated_not_transliterated(self):
        # Побуквенно вышло бы «Хидроклоротиазид» и «Клорхексидин».
        assert translate_generic("ჰიდროქლოროთიაზიდი") == "Гидрохлоротиазид"
        assert translate_generic("ქლორჰექსიდინი") == "Хлоргексидин"

    def test_genitive_ending_is_dropped(self):
        assert translate_generic("ვარფარინის ნატრიუმი") == "Варфарин натрия"

    def test_chemistry_also_works_inside_a_medicine_name(self):
        assert translate_medicine("ლიდოკაინის ჰიდროქლორიდი 20მგ").startswith(
            "Лидокаин гидрохлорид 20 мг"
        )

    def test_missing_data_becomes_empty(self):
        assert translate_company("-") == ""
        assert translate_generic("-") == ""
