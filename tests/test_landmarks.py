"""Тесты перевода ориентиров.

Главный тест здесь — прогон всего корпуса из tests/fixtures/landmarks.txt:
он показывает, что словарь покрывает реальные формулировки, а не выдуманные.
Корпус снят с 27 аптек Тбилиси 2026-08-07.
"""

from pathlib import Path

import re

import pytest

from misbot import i18n, landmarks
from misbot.landmarks import has_georgian, translate_landmark

CORPUS = [
    line
    for line in (Path(__file__).parent / "fixtures" / "landmarks.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]


class TestCorpus:
    def test_corpus_is_not_empty(self):
        assert len(CORPUS) >= 20

    @pytest.mark.parametrize("landmark", CORPUS)
    def test_nothing_is_left_untranslated(self, landmark):
        # Грузинские буквы в переводе означают дырку в словаре.
        assert not has_georgian(translate_landmark(landmark))

    @pytest.mark.parametrize("landmark", CORPUS)
    def test_translation_is_never_empty(self, landmark):
        assert translate_landmark(landmark).strip()


class TestWordOrder:
    def test_place_word_moves_to_the_front(self):
        # По-грузински слово места последнее, по-русски — первое.
        assert translate_landmark("არქივის პირდაპირ") == "напротив архива"

    def test_common_noun_goes_before_the_name(self):
        assert translate_landmark("ხეჩინაშვილის კლინიკის გვერდით") == "возле клиники Хечинашвили"

    def test_nested_nouns_are_reversed(self):
        # «урологии института» → «института урологии»
        assert translate_landmark("უროლოგიის ინსტიტუტის გვერდით") == "возле института урологии"

    def test_adjective_stays_before_its_noun(self):
        assert "клинической больницы" in translate_landmark("კლინიკური საავადმყოფოს ეზოში")

    def test_ordinal_stays_before_the_noun(self):
        assert translate_landmark("მე-9 საავადმყოფოს ეზოში") == "во дворе 9-й больницы"

    def test_imeni_goes_after_the_noun(self):
        result = translate_landmark("ი.ჟორდანიას სახელობის სამედიცინო ცენტრი")
        assert result.index("центра") < result.index("имени") < result.index("Жорданиа")


class TestProperNouns:
    def test_genitive_ending_is_dropped(self):
        # Без обрезки выходило бы «Хечинашвилис».
        assert "Хечинашвили" in translate_landmark("ხეჩინაშვილის კლინიკის გვერდით")

    def test_vowel_stem_keeps_its_shape(self):
        assert "Гагуа" in translate_landmark("გაგუას კლინიკის ფოიე")

    def test_known_names_use_their_russian_form(self):
        assert "банка Грузии" in translate_landmark("საქართველოს ბანკის გვერდით")

    def test_quotes_are_preserved(self):
        assert translate_landmark('"ნიკორას" მაღაზიის პირდაპირ') == 'напротив магазина "Никора"'

    def test_capital_after_a_dot(self):
        assert "И.Жорданиа" in translate_landmark("ი.ჟორდანიას სახელობის ცენტრი")

    def test_latin_text_is_left_alone(self):
        assert "TBC" in translate_landmark("TBC ბანკთან")


class TestStructure:
    def test_clauses_are_translated_separately(self):
        result = translate_landmark("გამოფენის წინ, სამტრედიის ქუჩის მოპირდაპირე მხარეს")
        assert result == "у выставки, напротив улицы Самтреди"

    def test_parentheses_survive(self):
        result = translate_landmark("კლინიკური საავადმყოფოს ეზოში (უროლოგიის ინსტიტუტის გვერდით)")
        assert result.endswith("(возле института урологии)")

    def test_attached_place_suffix_is_understood(self):
        # «-თან» приклеен к слову, а не стоит отдельным словом.
        assert translate_landmark("დინამოს სტადიონთან") == "возле стадиона Динамо"

    def test_pharmacy_word_is_dropped(self):
        # «Аптека» в ориентире аптеки — тавтология.
        assert translate_landmark("კრედო ბანკის გვერდით აფთიაქი") == "возле банка Кредо"

    def test_empty_input(self):
        assert translate_landmark("") == ""
        assert translate_landmark("   ") == ""

    def test_unknown_words_become_transliterated_names(self):
        # Словарь неполон по определению — незнакомое должно проходить насквозь.
        assert translate_landmark("ზაზაძის ქოხი") == "Зазадзи Кохи"


class TestEnglish:
    """Ориентир по-английски: порядок слов другой, не только словарь."""

    def test_dictionaries_have_the_same_keys(self):
        assert set(landmarks.PLACE_WORDS) == set(landmarks.PLACE_WORDS_EN)
        assert set(landmarks.NOUNS) == set(landmarks.NOUNS_EN)
        assert set(landmarks.ADJECTIVES) == set(landmarks.ADJECTIVES_EN)

    @pytest.mark.parametrize(
        "georgian, english",
        [
            ("არქივის პირდაპირ", "opposite archive"),
            ("ნიუ-ვიჟენის კლინიკის ფოიე", "in the lobby of Niu-Vizheni clinic"),
        ],
    )
    def test_simple_landmarks(self, georgian, english):
        assert translate_landmark(georgian, i18n.EN) == english

    def test_the_name_goes_before_the_noun(self):
        # По-русски «клиники Хечинашвили», по-английски наоборот.
        text = translate_landmark("ხეჩინაშვილის კლინიკის გვერდით", i18n.EN)
        assert text == "next to Khechinashvili clinic"

    def test_named_after_keeps_the_name_last(self):
        text = translate_landmark("ი.ჟორდანიას სახელობის სამედიცინო ცენტრი", i18n.EN)
        assert text == "medical centre named after I.Zhordania"

    def test_numbers_go_after_the_noun(self):
        text = translate_landmark("მე-9 საავადმყოფოს ეზოში", i18n.EN)
        assert text == "in the courtyard of hospital No. 9"

    def test_no_russian_leaks_into_english(self):
        cyrillic = re.compile(r"[а-яА-Я]")
        for text in CORPUS:
            assert not cyrillic.search(translate_landmark(text, i18n.EN)), text

    def test_russian_is_untouched(self):
        assert translate_landmark("არქივის პირდაპირ") == "напротив архива"
