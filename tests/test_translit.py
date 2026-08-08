"""Тесты транслитерации. Сети не требуют.

Ожидания по латинице сверены с живым сайтом скриптом tools/check_translit.py
(45 из 45 названий, 2026-08-07).
"""

import pytest

from misbot.translit import (
    is_cyrillic,
    is_georgian,
    is_latin,
    ka_to_latin,
    ka_to_ru,
    ru_to_latin,
    ru_to_latin_candidates,
    shorten,
)


class TestAlphabetDetection:
    def test_georgian(self):
        assert is_georgian("ნუროფენი")
        assert not is_georgian("nurofen")

    def test_cyrillic(self):
        assert is_cyrillic("нурофен")
        assert not is_cyrillic("ნუროფენი")

    def test_latin(self):
        assert is_latin("nurofen")
        assert not is_latin("нурофен")


class TestKaToRu:
    @pytest.mark.parametrize(
        "georgian, russian",
        [
            ("ნუროფენი", "нурофени"),
            ("იბუპროფენი", "ибупрофени"),
            ("ასპირინი", "аспирини"),
            ("აბი", "аби"),
        ],
    )
    def test_letter_by_letter(self, georgian, russian):
        assert ka_to_ru(georgian) == russian

    def test_known_names_come_from_the_dictionary(self):
        # Побуквенно вышло бы «тбилиси» и «поти» — эти имена ведём вручную.
        assert ka_to_ru("თბილისი") == "Тбилиси"
        assert ka_to_ru("ფოთი") == "Поти"
        assert ka_to_ru("საბურთალო") == "Сабуртало"

    def test_mixed_text_keeps_digits_and_latin(self):
        assert ka_to_ru("ასპირინი 100მგ აბი - #20") == "аспирини 100мг аби - #20"

    def test_dictionary_applies_per_word(self):
        assert ka_to_ru("აფთიაქი 581 სადღეღამისო") == "аптека 581 круглосуточно"

    def test_schedule_words_are_translated_not_transliterated(self):
        # «ковелдгхе» вместо «ежедневно» читалось бы как шум.
        assert ka_to_ru("9.00-21.30 ყოველდღე") == "9.00-21.30 ежедневно"

    def test_dictionary_works_inside_a_token(self):
        # В расписании сосед справа — слеш, а не пробел.
        assert ka_to_ru("შაბ/9.00-15.00; კვ/დასვენება") == "сб/9.00-15.00; вс/выходной"

    def test_short_keys_do_not_eat_longer_words(self):
        # «კვ» (вс) не должно срабатывать внутри «კვირა» (воскресенье).
        assert ka_to_ru("კვირა") == "воскресенье"
        assert ka_to_ru("კვერცხი") == "кверцхи"

    def test_empty(self):
        assert ka_to_ru("") == ""


class TestKaToLatin:
    @pytest.mark.parametrize(
        "georgian, latin",
        [
            ("გეა", "Gea"),
            ("ნუროფენი", "Nuropeni"),
            ("ბათუმი", "Batumi"),
            ("ჯანმრთელობა", "Janmrteloba"),
            ("ღვინო", "Ghvino"),
        ],
    )
    def test_letter_by_letter(self, georgian, latin):
        assert ka_to_latin(georgian) == latin

    def test_known_names_come_from_the_dictionary(self):
        # По системе ფ — это p, вышло бы «Parmagidi».
        assert ka_to_latin("ფარმაგიდი") == "Pharmagidi"
        assert ka_to_latin("პსპ") == "PSP"

    def test_legal_form_is_spelled_out(self):
        # «Shps Gea» в начале строки читается как шум.
        assert ka_to_latin('შპს "გეა"') == 'LLC "Gea"'

    def test_every_word_is_capitalised(self):
        assert ka_to_latin("ფარმაგიდი გეა") == "Pharmagidi Gea"

    def test_digits_and_latin_are_kept(self):
        assert ka_to_latin("აფთიაქი 334 PSP") == "Aptiaqi 334 PSP"

    def test_empty(self):
        assert ka_to_latin("") == ""


class TestRuToLatin:
    @pytest.mark.parametrize(
        "russian, expected",
        [
            ("диклофенак", "diclofenac"),
            ("кетонал", "ketonal"),
            ("цитрамон", "citramon"),
            ("цефазолин", "cefazolin"),
            ("парацетамол", "paracetamol"),
            ("ибупрофен", "ibuprofen"),
            ("амоксиклав", "amoxiclav"),
            ("метформин", "metformin"),
            ("трамадол", "tramadol"),
        ],
    )
    def test_best_candidate_is_the_real_spelling(self, russian, expected):
        assert ru_to_latin(russian) == expected

    @pytest.mark.parametrize(
        "russian, expected",
        [
            ("гепарин", "heparin"),      # г → h
            ("морфин", "morphin"),       # ф → ph
            ("хлоргексидин", "chlorhexidin"),  # х → ch в начале перед согласной
            ("варфарин", "warfarin"),    # в → w
            ("мезим", "mezym"),          # и → y
            ("амоксиклав", "amoxiclav"),  # кс → x
        ],
    )
    def test_alternative_spellings_stay_within_budget(self, russian, expected):
        # Перебор упирается в лимит обращений к сайту: 1 запрос в секунду.
        assert expected in ru_to_latin_candidates(russian)[:5]

    def test_rare_spellings_are_left_to_the_prefix_fallback(self):
        # «дексаметазон» → dexamethason стоит слишком дорого (th плюс з→s),
        # в бюджет он не влезает. Такие случаи вытягивает обрубленный префикс:
        # dexamet находит Dexamethason на сайте.
        assert "dexamethason" not in ru_to_latin_candidates("дексаметазон")[:5]
        assert shorten("dexametazon") == "dexamet"

    def test_final_k_can_become_c(self):
        # Регрессия: пустая «следующая буква» считалась гласной переднего ряда,
        # и конечная «к» всегда получала k — «диклофенак» не находился.
        assert ru_to_latin_candidates("диклофенак")[0].endswith("c")

    def test_k_before_front_vowel_is_never_c(self):
        # «ce», «ci» читаются как «це», «ци» — для «ке», «ки» годится только k.
        assert all(c.startswith("ke") for c in ru_to_latin_candidates("кетонал"))

    def test_candidates_are_unique_and_capped(self):
        candidates = ru_to_latin_candidates("хлоргексидин", limit=5)
        assert len(candidates) == 5
        assert len(set(candidates)) == 5

    def test_latin_and_digits_pass_through(self):
        assert ru_to_latin("но-шпа 40") == "no-shpa 40"

    def test_empty(self):
        assert ru_to_latin_candidates("") == []


class TestShorten:
    def test_cuts_the_tail(self):
        assert shorten("ceftriakson") == "ceftria"

    def test_never_goes_below_the_site_minimum(self):
        assert len(shorten("abc")) == 3
        assert len(shorten("abcd")) == 3
