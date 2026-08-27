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

from . import i18n
from .translit import ka_to_english, ka_to_ru

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


def translate_landmark(text: str, lang: str = i18n.DEFAULT) -> str:
    """Перевод ориентира. Пустая строка — если переводить нечего."""
    if not text or not text.strip():
        return ""

    def parens(match: "re.Match") -> str:
        inner = _translate_parts(match.group(1), lang)
        return f"({inner})" if inner else ""

    body = _PARENS_RE.sub(lambda m: "\x00" + parens(m) + "\x00", text)
    parts = []
    for chunk in body.split("\x00"):
        if chunk.startswith("(") and chunk.endswith(")"):
            parts.append(chunk)
        else:
            translated = _translate_parts(chunk, lang)
            if translated:
                parts.append(translated)

    result = " ".join(part for part in parts if part).strip()
    return re.sub(r"\s+([,)])", r"\1", result)


def _translate_parts(text: str, lang: str = i18n.DEFAULT) -> str:
    parts = [
        _translate_clause(part, lang) for part in _SPLIT_RE.split(text) if part.strip()
    ]
    return ", ".join(part for part in parts if part)


def _translate_clause(clause: str, lang: str = i18n.DEFAULT) -> str:
    clause = clause.strip()
    if not clause:
        return ""

    preposition, rest = _take_place_word(clause, lang)
    words = [word for word in rest.split() if word]

    ordinals: List[str] = []
    adjectives: List[str] = []
    nouns: List[str] = []
    tail: List[str] = []
    proper: List[str] = []

    for word in words:
        if _lookup(word, _DROP_TABLE) is not None:
            continue

        ordinal = _ordinal(word, lang)
        if ordinal:
            ordinals.append(ordinal)
            continue

        translated = _lookup(word, _table(TAIL_NOUNS, TAIL_NOUNS_EN, lang))
        if translated:
            tail.append(translated)
            continue

        translated = _lookup(word, _table(ADJECTIVES, ADJECTIVES_EN, lang))
        if translated:
            adjectives.append(translated)
            continue

        translated = _lookup(word, _table(NOUNS, NOUNS_EN, lang))
        if translated:
            nouns.append(translated)
            continue

        translated = _lookup(word, _table(FUNCTION_WORDS, FUNCTION_WORDS_EN, lang))
        if translated:
            proper.append(translated)
            continue

        proper.append(_proper_noun(word, lang))

    # Вложенные нарицательные в грузинском идут от частного к общему —
    # «урологии института», по-русски наоборот. Прилагательные же остаются
    # перед своим словом в обоих языках.
    nouns.reverse()

    if lang == i18n.EN:
        # По-английски имя стоит перед нарицательным («Khechinashvili clinic»),
        # но после «named after» — за ним («medical centre named after
        # Zhordania»). Номер уходит в хвост: «hospital No. 9».
        if tail:
            pieces = adjectives + nouns + tail + proper + ordinals
        else:
            pieces = proper + adjectives + nouns + ordinals
        pieces = [preposition] + pieces
    else:
        pieces = [preposition] + adjectives + ordinals + nouns + tail + proper
    return " ".join(piece for piece in pieces if piece).strip()


def _table(russian: Dict[str, str], english: Dict[str, str], lang: str) -> Dict[str, str]:
    return english if lang == i18n.EN else russian


def _take_place_word(clause: str, lang: str = i18n.DEFAULT) -> Tuple[str, str]:
    """Отделить слово места от конца части и вернуть предлог с остатком."""
    places = _table(PLACE_WORDS, PLACE_WORDS_EN, lang)
    lowered = clause.rstrip(".")
    for georgian in sorted(places, key=len, reverse=True):
        if lowered.endswith(georgian):
            return places[georgian], lowered[: -len(georgian)].strip()
        # «X-ის გვერდით აფთიაქი» — слово места не последнее, но и не в начале.
        marker = f" {georgian} "
        if marker in lowered:
            head, _, tail = lowered.partition(marker)
            return places[georgian], f"{head} {tail}".strip()

    words = lowered.split()
    if words:
        for suffix, preposition in _table(_SUFFIX_PLACE, _SUFFIX_PLACE_EN, lang).items():
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


def _ordinal(word: str, lang: str = i18n.DEFAULT) -> Optional[str]:
    match = _ORDINAL_RE.match(word.strip('"«»()'))
    if match is None:
        return None
    return f"No. {match.group(1)}" if lang == i18n.EN else f"{match.group(1)}-й"


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


def _proper_noun(word: str, lang: str = i18n.DEFAULT) -> str:
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
    if lang == i18n.EN:
        # Имена — романизацией, как на указателях: «ხეჩინაშვილი» → «Khechinashvili».
        return prefix + _capitalize(ka_to_english(base)) + suffix

    known = PROPER_NAMES.get(base)
    transliterated = known if known else _capitalize(ka_to_ru(base))
    return prefix + transliterated + suffix


def _capitalize(text: str) -> str:
    """Заглавная в начале и после точки: «и.ჟორდანია» → «И.Жордания»."""
    return re.sub(r"(^|\.)(\w)", lambda m: m.group(1) + m.group(2).upper(), text)


def has_georgian(text: str) -> bool:
    return bool(re.search(r"[Ⴀ-ჿ]", text))


# --- английский слой -------------------------------------------------------
#
# Ключи те же, значения — английские, но в именительном падеже: в английском
# предлог ничем не управляет. Порядок слов другой, им занимается сборка ниже.

PLACE_WORDS_EN: Dict[str, str] = {
    "მოპირდაპირე მხარეს": "opposite",
    "მოპირდაპირე მხარე": "opposite",
    "მიმართულებით მარჯვენა მხარე": "on the right, towards",
    "მიმართულებით მარცხენა მხარე": "on the left, towards",
    "მიმართულებით": "towards",
    "შესასვლელში": "at the entrance to",
    "შესასვლელთან": "at the entrance to",
    "გადასასვლელში": "in the underpass by",
    "მიმდებარედ": "next to",
    "მიმდებარე": "next to",
    "პირდაპირ": "opposite",
    "გვერდით": "next to",
    "უკან": "behind",
    "წინ": "in front of",
    "ეზოში": "in the courtyard of",
    "ფოიე": "in the lobby of",
    "კვეთა": "junction of",
    "კუთხე": "corner of",
    "დასაწყისი": "start of",
    "ბოლოს": "at the end of",
    "შენობაში": "in the building of",
    "შენობის": "in the building of",
    "ტერიტორიაზე": "on the grounds of",
    "სართული": "floor",
}

NOUNS_EN: Dict[str, str] = {
    "საავადმყოფო": "hospital",
    "კლინიკ": "clinic",
    "ინსტიტუტ": "institute",
    "ცენტრ": "centre",
    "პოლიკლინიკ": "polyclinic",
    "ქუჩების": "streets",
    "ქუჩ": "street",
    "გამზირ": "avenue",
    "მოედან": "square",
    "სტადიონ": "stadium",
    "პარკ": "park",
    "ბანკ": "bank",
    "მაღაზი": "shop",
    "სუპერმარკეტ": "supermarket",
    "ბაზრ": "market",
    "ბაზარ": "market",
    "სკოლ": "school",
    "უნივერსიტეტ": "university",
    "საელჩო": "embassy",
    "ეკლესი": "church",
    "თეატრ": "theatre",
    "რესტორან": "restaurant",
    "სასტუმრო": "hotel",
    "ძეგლ": "monument",
    "ხიდ": "bridge",
    "სახლ": "building",
    "შენობ": "building",
    "გამოფენ": "exhibition centre",
    "გამომცემლობ": "publishing house",
    "სადგურ": "railway station",
    "გზ": "road",
    "ბაღ": "garden",
    "სამშობიარო": "maternity hospital",
    "მეტრო": "metro",
    "გადასასვლელ": "underpass",
    "უროლოგი": "urology",
    "პარაზიტოლოგი": "parasitology",
    "არქივ": "archive",
    "ბიბლიოთეკ": "library",
    "ფოსტ": "post office",
    "სასწრაფო": "ambulance station",
    "ლაბორატორი": "laboratory",
}

ADJECTIVES_EN: Dict[str, str] = {
    "კლინიკურ": "clinical",
    "სამედიცინო": "medical",
    "მიწისქვეშა": "underground",
    "ყოფილი": "former",
    "დანიური": "Danish",
    "ცენტრალურ": "central",
    "ახალ": "new",
    "ძველ": "old",
}

TAIL_NOUNS_EN: Dict[str, str] = {"სახელობის": "named after"}

FUNCTION_WORDS_EN: Dict[str, str] = {"და": "and"}

_SUFFIX_PLACE_EN: Dict[str, str] = {"თან": "near"}
