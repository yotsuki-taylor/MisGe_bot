"""Тесты словаря языков.

Главное здесь — не переводы (их проверяет человек), а то, что словарь нельзя
использовать неправильно: пропущенный ключ, разъехавшиеся подстановки, забытый
язык. Ошибка в подстановке проявилась бы только в проде и уронила бы ответ.
"""

import re
import string

import pytest

from misbot import formatting as fmt
from misbot import i18n

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(text: str) -> set:
    return set(_PLACEHOLDER.findall(text))


class TestDictionary:
    def test_every_key_has_the_default_language(self):
        # На него откатывается text(), так что дырка тут — это пустота в ответе.
        missing = [key for key, row in i18n.STRINGS.items() if i18n.DEFAULT not in row]
        assert missing == []

    def test_every_key_is_translated_to_every_supported_language(self):
        missing = [
            (key, lang)
            for key, row in i18n.STRINGS.items()
            for lang in i18n.SUPPORTED
            if not row.get(lang)
        ]
        assert missing == []

    @pytest.mark.parametrize("key", sorted(i18n.STRINGS))
    def test_placeholders_match_across_languages(self, key):
        # «{count}», написанное в переводе как «{сount}» с русской «с», уронило бы
        # format() уже у пользователя.
        row = i18n.STRINGS[key]
        expected = placeholders(row[i18n.DEFAULT])
        for lang, translation in row.items():
            assert placeholders(translation) == expected, f"{key} / {lang}"

    @pytest.mark.parametrize("key", sorted(i18n.STRINGS))
    def test_no_stray_braces(self, key):
        # Одиночная фигурная скобка — тоже отказ format().
        for lang, translation in i18n.STRINGS[key].items():
            formatter = string.Formatter()
            list(formatter.parse(translation)), f"{key} / {lang}"

    def test_translations_are_not_copies_of_russian(self):
        # Забытый перевод виден как совпадающая строка. Исключения — то, что
        # переводить нечего: одинаковые для всех надписи.
        same_on_purpose = {"choose_language"}
        copied = [
            (key, lang)
            for key, row in i18n.STRINGS.items()
            for lang in i18n.SUPPORTED
            if key not in same_on_purpose and lang != i18n.RU and row.get(lang) == row[i18n.RU]
        ]
        assert copied == []

    def test_georgian_translations_are_in_georgian(self):
        # Кириллица в грузинском переводе — почти наверняка недоперевод.
        # Кроме экрана выбора языка: его видят до того, как язык выбран, поэтому
        # он двуязычный нарочно — человек должен узнать свой, не зная чужого.
        bilingual = {"choose_language"}
        cyrillic = re.compile(r"[а-яА-Я]")
        suspicious = [
            key for key, row in i18n.STRINGS.items()
            if key not in bilingual
            and i18n.KA in row and cyrillic.search(_without_examples(row[i18n.KA]))
        ]
        assert suspicious == []


def _without_examples(text: str) -> str:
    """Убрать <code>…</code>: там нарочно стоят примеры запросов на трёх языках."""
    return re.sub(r"<code>.*?</code>", "", text, flags=re.S)


class TestText:
    def test_returns_the_asked_language(self):
        assert i18n.text("too_short", i18n.KA) != i18n.text("too_short", i18n.RU)

    def test_unknown_language_falls_back_to_russian(self):
        assert i18n.text("too_short", "xx") == i18n.text("too_short", i18n.RU)

    def test_missing_key_is_a_programming_error(self):
        # Молча отдать пустоту хуже: дырка в тексте дойдёт до пользователя.
        with pytest.raises(KeyError):
            i18n.text("такого-ключа-нет", i18n.RU)


class TestSupported:
    def test_all_three_languages_are_offered(self):
        assert i18n.SUPPORTED == (i18n.RU, i18n.KA, i18n.EN)

    def test_an_unknown_language_is_not_offered(self):
        # В SUPPORTED попадает только то, для чего есть переводы: кнопка,
        # ведущая на чужой интерфейс, обманывала бы.
        assert not i18n.known("de")

    def test_every_supported_language_has_a_name_for_the_button(self):
        assert all(i18n.NAMES.get(lang) for lang in i18n.SUPPORTED)

    def test_languages_are_named_in_themselves(self):
        assert i18n.NAMES[i18n.KA] == "ქართული"
        assert i18n.NAMES[i18n.RU] == "Русский"
        assert i18n.NAMES[i18n.EN] == "English"


class TestEveryTextRenders:
    """Каждая функция formatting должна собираться на всех языках."""

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    def test_simple_texts(self, lang):
        for render in (
            fmt.greeting, fmt.help_text, fmt.too_short, fmt.site_unavailable,
            fmt.parser_broken, fmt.busy, fmt.nothing_everywhere, fmt.no_analogues,
            fmt.analogues_unavailable, fmt.watch_removed, fmt.city_unknown,
        ):
            assert render(lang).strip()

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    def test_texts_with_substitutions(self, lang):
        assert "нурофен" in fmt.searching("нурофен", lang)
        assert "нурофен" in fmt.nothing_found("нурофен", lang)
        assert "Тбилиси" in fmt.city_chosen("Тбилиси", lang)
        assert "Тбилиси" in fmt.choose_city("Тбилиси", lang)
        assert "10" in fmt.watch_limit(10, lang)
        assert "42" in fmt.chat_id(42, lang)
        assert "t.me/bot" in fmt.about_text("t.me/bot", lang)


class TestNothingFound:
    """Подсказка про международное название — самое полезное, что тут можно сказать."""

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    def test_suggests_the_international_name(self, lang):
        assert "cetirizine" in fmt.nothing_found("зиртек", lang)

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    def test_still_suggests_the_active_ingredient(self, lang):
        text = i18n.STRINGS["nothing_found"][lang]
        assert any(name in text for name in ("ибупрофен", "იბუპროფენი", "ibuprofen"))

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    def test_repeats_what_was_asked(self, lang):
        assert "зиртек" in fmt.nothing_found("зиртек", lang)

    def test_the_query_is_escaped(self):
        assert "&lt;b&gt;" in fmt.nothing_found("<b>x</b>")
