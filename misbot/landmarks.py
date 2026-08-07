"""Перевод ориентиров («как найти аптеку») на русский по словарю.

Ориентиры устроены однообразно: [что-то в родительном падеже] + [слово места].
«ხეჩინაშვილის კლინიკის გვერდით» — это [Хечинашвили][клиники][рядом]. Слово места
в грузинском стоит последним, в русском — первым, поэтому мало заменить слова,
надо ещё переставить.

Что делает перевод:

1. режет фразу на части по запятым и скобкам;
2. отрывает от конца части слово места и превращает его в русский предлог;
3. остальные слова делит на знакомые (есть в словаре — переводим) и незнакомые
   (имена собственные — транслитерируем);
4. собирает часть обратно так, как принято по-русски: предлог, потом
   нарицательные, потом имена.

Падежей и согласований здесь нет и не будет: словарь хранит сразу ту форму,
которая нужна после предлога. Что не покрыто словарём — остаётся транслитом,
поэтому оригинал всегда показывается рядом с переводом.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from .translit import ka_to_ru

# Слова места: чем длиннее, тем раньше проверяем.
#
# Все предлоги здесь подобраны так, чтобы управлять родительным падежом — тогда
# словарю хватает одной формы на существительное. Поэтому «возле», а не «рядом
# с» (творительный), и «в сторону», а не «по направлению к» (дательный).
PLACE_WORDS: Dict[str, str] = {
    "მოპირდაპირე მხარეს": "напротив",
    "მოპირდაპირე მხარე": "напротив",
    "მიმართულებით მარჯვენა მხარე": "справа, в сторону",
    "მიმართულებით მარცხენა მხარე": "слева, в сторону",
    "მიმართულებით": "в сторону",
    "შესასვლელში": "у входа",
    "შესასვლელთან": "у входа",
    "გადასასვლელში": "в переходе возле",
    "მიმდებარედ": "возле",
    "მიმდებარე": "возле",
    "პირდაპირ": "напротив",
    "გვერდით": "возле",
    "უკან": "позади",
    "წინ": "у",
    "ეზოში": "во дворе",
    "ფოიე": "фойе",
    "კვეთა": "пересечение",
    "კუთხე": "угол",
    "დასაწყისი": "начало",
    "ბოლოს": "в конце",
    "შენობაში": "в здании",
    "შენობის": "в здании",
    "ტერიტორიაზე": "на территории",
    "სართული": "этаж",
}

_SUFFIX_PLACE = {
    # Приклеивается к слову, а не стоит отдельно: «სტადიონთან», «ბანკთან».
    "თან": "возле",
}

DROP_WORDS = ("აფთიაქ",)
"""«Аптека» в ориентире аптеки — тавтология, выбрасываем."""

# Нарицательные: ключ — основа, значение — форма после предлога (родительный).
NOUNS: Dict[str, str] = {
    "საავადმყოფო": "больницы",
    "კლინიკ": "клиники",
    "ინსტიტუტ": "института",
    "ცენტრ": "центра",
    "პოლიკლინიკ": "поликлиники",
    "ქუჩების": "улиц",
    "ქუჩ": "улицы",
    "გამზირ": "проспекта",
    "მოედან": "площади",
    "სტადიონ": "стадиона",
    "პარკ": "парка",
    "ბანკ": "банка",
    "მაღაზი": "магазина",
    "სუპერმარკეტ": "супермаркета",
    "ბაზრ": "рынка",
    "ბაზარ": "рынка",
    "სკოლ": "школы",
    "უნივერსიტეტ": "университета",
    "საელჩო": "посольства",
    "ეკლესი": "церкви",
    "თეატრ": "театра",
    "რესტორან": "ресторана",
    "სასტუმრო": "гостиницы",
    "ძეგლ": "памятника",
    "ხიდ": "моста",
    "სახლ": "дома",
    "შენობ": "здания",
    "გამოფენ": "выставки",
    "გამომცემლობ": "издательства",
    "სადგურ": "вокзала",
    "გზ": "дороги",
    "ბაღ": "сада",
    "სამშობიარო": "роддома",
    "მეტრო": "метро",
    "გადასასვლელ": "перехода",
    "უროლოგი": "урологии",
    "პარაზიტოლოგი": "паразитологии",
    "არქივ": "архива",
    "ბიბლიოთეკ": "библиотеки",
    "ფოსტ": "почты",
    "სასწრაფო": "скорой помощи",
    "ლაბორატორი": "лаборатории",
}

# Определения — стоят перед своим существительным и в русском тоже.
ADJECTIVES: Dict[str, str] = {
    "კლინიკურ": "клинической",
    "სამედიცინო": "медицинского",
    "მიწისქვეშა": "подземного",
    "ყოფილი": "бывшая",
    "დანიური": "датского",
    "ცენტრალურ": "центрального",
    "ახალ": "нового",
    "ძველ": "старого",
}

# Союзы и предлоги — остаются там же, где стояли, среди имён собственных.
FUNCTION_WORDS: Dict[str, str] = {
    "და": "и",
}

# Уходят в конец нарицательной части: «центра имени Жордания».
TAIL_NOUNS: Dict[str, str] = {
    "სახელობის": "имени",
}

PROPER_NAMES: Dict[str, str] = {
    # Имена, у которых есть общепринятая русская форма.
    "საქართველო": "Грузии",
    "თბილისი": "Тбилиси",
}

_DROP_TABLE = dict.fromkeys(DROP_WORDS, "")

_ORDINAL_RE = re.compile(r"^მე-(\d+)$")
_SPLIT_RE = re.compile(r"\s*[,;]\s*")
_PARENS_RE = re.compile(r"\(([^)]*)\)")


def translate_landmark(text: str) -> str:
    """Русский перевод ориентира. Пустая строка — если переводить нечего."""
    if not text or not text.strip():
        return ""

    def parens(match: "re.Match") -> str:
        inner = _translate_parts(match.group(1))
        return f"({inner})" if inner else ""

    body = _PARENS_RE.sub(lambda m: "\x00" + parens(m) + "\x00", text)
    parts = []
    for chunk in body.split("\x00"):
        if chunk.startswith("(") and chunk.endswith(")"):
            parts.append(chunk)
        else:
            translated = _translate_parts(chunk)
            if translated:
                parts.append(translated)

    result = " ".join(part for part in parts if part).strip()
    return re.sub(r"\s+([,)])", r"\1", result)


def _translate_parts(text: str) -> str:
    parts = [_translate_clause(part) for part in _SPLIT_RE.split(text) if part.strip()]
    return ", ".join(part for part in parts if part)


def _translate_clause(clause: str) -> str:
    clause = clause.strip()
    if not clause:
        return ""

    preposition, rest = _take_place_word(clause)
    words = [word for word in rest.split() if word]

    ordinals: List[str] = []
    adjectives: List[str] = []
    nouns: List[str] = []
    tail: List[str] = []
    proper: List[str] = []

    for word in words:
        if _lookup(word, _DROP_TABLE) is not None:
            continue

        ordinal = _ordinal(word)
        if ordinal:
            ordinals.append(ordinal)
            continue

        translated = _lookup(word, TAIL_NOUNS)
        if translated:
            tail.append(translated)
            continue

        translated = _lookup(word, ADJECTIVES)
        if translated:
            adjectives.append(translated)
            continue

        translated = _lookup(word, NOUNS)
        if translated:
            nouns.append(translated)
            continue

        translated = _lookup(word, FUNCTION_WORDS)
        if translated:
            proper.append(translated)
            continue

        proper.append(_proper_noun(word))

    # Вложенные нарицательные в грузинском идут от частного к общему —
    # «урологии института», по-русски наоборот. Прилагательные же остаются
    # перед своим словом в обоих языках.
    nouns.reverse()

    pieces = [preposition] + adjectives + ordinals + nouns + tail + proper
    return " ".join(piece for piece in pieces if piece).strip()


def _take_place_word(clause: str) -> Tuple[str, str]:
    """Отделить слово места от конца части и вернуть предлог с остатком."""
    lowered = clause.rstrip(".")
    for georgian in sorted(PLACE_WORDS, key=len, reverse=True):
        if lowered.endswith(georgian):
            return PLACE_WORDS[georgian], lowered[: -len(georgian)].strip()
        # «X-ის გვერდით აფთიაქი» — слово места не последнее, но и не в начале.
        marker = f" {georgian} "
        if marker in lowered:
            head, _, tail = lowered.partition(marker)
            return PLACE_WORDS[georgian], f"{head} {tail}".strip()

    words = lowered.split()
    if words:
        for suffix, preposition in _SUFFIX_PLACE.items():
            if words[-1].endswith(suffix) and len(words[-1]) > len(suffix) + 2:
                words[-1] = words[-1][: -len(suffix)]
                return preposition, " ".join(words)

    return "", lowered


def _lookup(word: str, table: Dict[str, str]) -> Optional[str]:
    """Поиск по основе: падежное окончание просто отбрасывается."""
    stripped = word.strip('"«»()').lower()
    if not stripped:
        return None
    for stem in sorted(table, key=len, reverse=True):
        if stripped.startswith(stem):
            return table[stem]
    return None


def _ordinal(word: str) -> Optional[str]:
    match = _ORDINAL_RE.match(word.strip('"«»()'))
    return f"{match.group(1)}-й" if match else None


_GENITIVE_SUFFIXES = ("ისა", "ის", "ს")
_KA_VOWELS = "აეიოუ"


def _nominative(word: str) -> str:
    """Отбросить грузинское окончание родительного падежа.

    «ხეჩინაშვილის» стоит в родительном, и без обрезки получалось бы
    «Хечинашвилис». Окончание -ის вытесняет именительное -ი, поэтому после
    обрезки согласному его возвращаем.
    """
    for suffix in _GENITIVE_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            stem = word[: -len(suffix)]
            if stem and stem[-1] not in _KA_VOWELS:
                stem += "ი"
            return stem
    return word


def _proper_noun(word: str) -> str:
    """Имя собственное: приводим к именительному, транслитерируем, кавычки на место."""
    prefix = ""
    suffix = ""
    while word and word[0] in '"«(':
        prefix += word[0]
        word = word[1:]
    while word and word[-1] in '"»).':
        suffix = word[-1] + suffix
        word = word[:-1]

    if not word:
        return prefix + suffix

    base = _nominative(word)
    known = PROPER_NAMES.get(base)
    transliterated = known if known else _capitalize(ka_to_ru(base))
    return prefix + transliterated + suffix


def _capitalize(text: str) -> str:
    """Заглавная в начале и после точки: «и.ჟორდანია» → «И.Жордания»."""
    return re.sub(r"(^|\.)(\w)", lambda m: m.group(1) + m.group(2).upper(), text)


def has_georgian(text: str) -> bool:
    return bool(re.search(r"[Ⴀ-ჿ]", text))
