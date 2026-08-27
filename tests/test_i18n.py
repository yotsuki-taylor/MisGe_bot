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
            # Формы числа проверяет TestPlural: языку не нужна строка формы,
            # которой у него нет, — английский никогда не спросит «few».
            if not row.get(lang) and not counted(key)
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


def counted(key: str) -> bool:
    """Ключ одной из форм числа: key_one, key_few, key_many."""
    stem, _, form = key.rpartition("_")
    return bool(stem) and form in i18n.FORM_NAMES


def stems() -> list:
    """Основы ключей, у которых есть формы числа."""
    return sorted({key.rpartition("_")[0] for key in i18n.STRINGS if counted(key)})


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


class TestPlural:
    """Число и существительное должны согласоваться на каждом языке."""

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    @pytest.mark.parametrize("stem", stems())
    def test_every_count_has_a_string_in_the_asked_language(self, stem, lang):
        # Откат на русский тут был бы не пустотой, а русской фразой посреди
        # грузинского ответа — заметить такое можно только глазами.
        missing = [
            count for count in range(0, 1000)
            if not i18n.STRINGS[i18n.plural_key(stem, count, lang)].get(lang)
        ]
        assert missing == []

    @pytest.mark.parametrize("stem", stems())
    def test_every_form_is_reachable(self, stem):
        # Ключ, до которого не доводит ни одно число, — забытая правка.
        used = {
            i18n.plural_key(stem, count, lang)
            for lang in i18n.SUPPORTED for count in range(0, 1000)
        }
        unused = [key for key in i18n.STRINGS if key.startswith(f"{stem}_") and key not in used]
        assert unused == []

    def test_russian_agrees_with_the_number(self):
        assert i18n.plural("more_pharmacies", 1, i18n.RU).startswith("…и ещё 1 аптека")
        assert i18n.plural("more_pharmacies", 3, i18n.RU).startswith("…и ещё 3 аптеки")
        assert i18n.plural("more_pharmacies", 7, i18n.RU).startswith("…и ещё 7 аптек")

    def test_russian_teens_are_the_exception(self):
        # 11 и 14 звучат как 5, а не как 1 и 4, — на этом ломаются наивные правила.
        assert i18n.plural("more_pharmacies", 11, i18n.RU).startswith("…и ещё 11 аптек ")
        assert i18n.plural("more_pharmacies", 14, i18n.RU).startswith("…и ещё 14 аптек ")
        assert i18n.plural("more_pharmacies", 21, i18n.RU).startswith("…и ещё 21 аптека")
        assert i18n.plural("more_pharmacies", 22, i18n.RU).startswith("…и ещё 22 аптеки")

    def test_english_singular_is_only_the_number_one(self):
        # Русское правило дало бы «21 more pharmacy».
        assert "1 more pharmacy " in i18n.plural("more_pharmacies", 1, i18n.EN)
        assert "21 more pharmacies" in i18n.plural("more_pharmacies", 21, i18n.EN)

    @pytest.mark.parametrize("count", [1, 2, 5, 11, 21])
    def test_georgian_keeps_one_form(self, count):
        # После числительного существительное не меняется.
        assert str(count) in i18n.plural("more_pharmacies", count, i18n.KA)
        assert "აფთიაქი" in i18n.plural("more_pharmacies", count, i18n.KA)

    def test_a_missing_form_falls_back_to_many(self):
        # «в 2 аптеках» и «в 5 аптеках» — одна строка, отдельной few нет.
        assert i18n.plural_key("in_stock", 2, i18n.RU) == "in_stock_many"
        assert i18n.plural_key("in_stock", 1, i18n.RU) == "in_stock_one"


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


class TestLanguagePrompt:
    """Экран выбора видят до того, как язык выбран."""

    def test_names_every_language(self):
        # Человек должен узнать свой язык, не зная остальных.
        prompt = fmt.choose_language()
        assert "Выберите язык" in prompt
        assert "აირჩიეთ ენა" in prompt
        assert "Choose a language" in prompt

    @pytest.mark.parametrize("lang", i18n.SUPPORTED)
    def test_looks_the_same_whatever_the_current_language(self, lang):
        # Текущий язык тут ни при чём: показывать надо одно и то же.
        assert i18n.text("choose_language", lang) == fmt.choose_language()
