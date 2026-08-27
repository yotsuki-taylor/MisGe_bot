"""Тесты перевода названий препаратов.

Главный тест — прогон корпуса из tests/fixtures/medicine_names.txt: 337 живых
названий, снятых с сайта 2026-08-07 по десяти препаратам. Он ловит дырки в
словаре форм выпуска — по следам вроде «аби» или «саинекцио» в переводе.
"""

import re
from pathlib import Path

import pytest

from misbot import i18n
from misbot import forms
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
    "цветеби", "шушхуна", "сацуцни", "рбили", "мкари", "дражe", "колофи",
    "пластикис", "зетхснари", "витамини",
)


class TestCorpus:
    def test_corpus_is_big_enough(self):
        assert len(CORPUS) > 300

    @pytest.mark.parametrize("name", CORPUS)
    def test_no_georgian_letters_survive(self, name):
        assert not has_georgian(translate_medicine(name))

    def test_no_form_words_are_left_transliterated(self):
        # По границам слова, а не по подстроке: иначе «капецитабин» ловится
        # на «аби», а «мосамзадеблад» — на «аби» внутри себя.
        artifacts = re.compile(
            r"\b(?:" + "|".join(ARTIFACTS) + r")\b", re.IGNORECASE
        )
        missed = [
            (name, translated)
            for name in CORPUS
            if artifacts.search(translated := translate_medicine(name))
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
            ("შუშხუნა აბი", "Шипучие таблетки"),
            ("საწუწნი აბი", "Таблетки для рассасывания"),
            ("რბილი კაფსულა", "Мягкие капсулы"),
            ("მყარი კაფსულა", "Твёрдые капсулы"),
            ("ზეთხსნარი", "Масляный раствор"),
            ("დრაჟე", "Драже"),
            ("კოლოფი", "Коробка"),
            ("პლასტიკის ფლაკონი", "Пластиковый флакон"),
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


class TestEnglish:
    """Контент по-английски: словари те же, слой другой."""

    @pytest.mark.parametrize(
        "russian, english",
        [
            ("FORM_PHRASES", "FORM_PHRASES_EN"),
            ("COUNTRIES", "COUNTRIES_EN"),
            ("CHEMICALS", "CHEMICALS_EN"),
            ("DISPENSING_PHRASES", "DISPENSING_PHRASES_EN"),
            ("UNITS", "UNITS_EN"),
        ],
    )
    def test_dictionaries_have_the_same_keys(self, russian, english):
        # Разъехавшиеся ключи — это дырка, которая проявится на живом названии.
        assert set(getattr(forms, russian)) == set(getattr(forms, english))

    def test_english_values_are_not_russian(self):
        cyrillic = re.compile(r"[а-яА-Я]")
        for name in (
            "FORM_PHRASES_EN", "COUNTRIES_EN", "CHEMICALS_EN", "DISPENSING_PHRASES_EN",
        ):
            leftovers = [v for v in getattr(forms, name).values() if cyrillic.search(v)]
            assert leftovers == [], name

    @pytest.mark.parametrize(
        "georgian, english",
        [
            ("ნუროფენ ექსპრესი 200მგ შემოგარსული აბი - #16",
             "Nurofen Expres 200 mg coated tablets, 16 pcs."),
            ("პარაცეტამოლი 500მგ აბი - #10", "Paracetamol 500 mg tablets, 10 pcs."),
            ("ციტრამონი", "Citramon"),
        ],
    )
    def test_medicine_names(self, georgian, english):
        assert translate_medicine(georgian, i18n.EN) == english

    def test_countries(self):
        assert translate_country("ნიდერლანდები", i18n.EN) == "Netherlands"
        assert translate_country("დიდი ბრიტანეთი", i18n.EN) == "United Kingdom"

    def test_dispensing(self):
        text = translate_dispensing("III ჯგუფი, გაიცემა რეცეპტის გარეშე", i18n.EN)
        assert text == "III group, without prescription"

    def test_generic(self):
        assert translate_generic("იბუპროფენი", i18n.EN) == "Ibuprofen"
        assert translate_generic("ასკორბინის მჟავა", i18n.EN) == "Ascorbic acid"

    def test_brands_use_the_international_spelling(self):
        # Романизация вывесок дала бы «Nuropen»: там ფ — это p.
        assert "Nurofen" in translate_medicine("ნუროფენი", i18n.EN)

    def test_georgian_keeps_the_original(self):
        # Сайт грузинский — переводить его обратно незачем.
        name = "ნუროფენ ექსპრესი 200მგ შემოგარსული აბი"
        assert translate_medicine(name, i18n.KA) == name
        assert translate_country("ნიდერლანდები", i18n.KA) == "ნიდერლანდები"

    def test_russian_is_untouched(self):
        assert translate_medicine("ნუროფენი") == "Нурофен"
        assert translate_country("ნიდერლანდები") == "Нидерланды"
