"""Транслитерация в обе стороны.

Направлений два, и они устроены по-разному.

**Наружу, грузиница → кириллица.** Однозначная замена по алфавиту: 33 буквы,
каждой соответствует своя. Нужна, чтобы показать пользователю название препарата
и адрес аптеки — весь контент mis.ge на грузинском.

**Внутрь, кириллица → латиница.** Здесь однозначного ответа нет. Сайт ищет не по
грузинскому написанию, а по международному латинскому названию препарата, причём
по началу строки и минимум от трёх букв. Русские названия лекарств — сами по себе
транслитерация тех же латинских, но неоднозначная: «диклофенак» это `diclofenac`,
а «кетонал» — `ketonal`, хотя буква «к» одна и та же. Поэтому функция отдаёт не
один вариант, а ранжированный список кандидатов; перебирать их — дело search.py.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

MIN_QUERY_LENGTH = 3
"""Сайт отказывается искать по запросу короче трёх букв."""

_GEORGIAN = re.compile(r"[Ⴀ-ჿ]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-z]")


def is_georgian(text: str) -> bool:
    return bool(_GEORGIAN.search(text))


def is_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def is_latin(text: str) -> bool:
    return bool(_LATIN.search(text))


# --- грузиница → кириллица -------------------------------------------------

KA_TO_RU: Dict[str, str] = {
    "ა": "а", "ბ": "б", "გ": "г", "დ": "д", "ე": "е", "ვ": "в", "ზ": "з",
    "თ": "т", "ი": "и", "კ": "к", "ლ": "л", "მ": "м", "ნ": "н", "ო": "о",
    "პ": "п", "ჟ": "ж", "რ": "р", "ს": "с", "ტ": "т", "უ": "у", "ფ": "ф",
    "ქ": "к", "ღ": "г", "ყ": "к", "შ": "ш", "ჩ": "ч", "ც": "ц", "ძ": "дз",
    "წ": "ц", "ჭ": "ч", "ხ": "х", "ჯ": "дж", "ჰ": "х",
    # вышедшие из употребления, изредка попадаются в старых записях
    "ჱ": "е", "ჲ": "и", "ჳ": "в", "ჴ": "х", "ჵ": "о", "ჶ": "ф",
}

KA_OVERRIDES: Dict[str, str] = {
    # Города и районы, у которых есть устоявшееся русское имя: побуквенная
    # замена дала бы «Тпилиси» и «Пoти». Список конечный, ведём вручную.
    "თბილისი": "Тбилиси",
    "ქუთაისი": "Кутаиси",
    "ბათუმი": "Батуми",
    "რუსთავი": "Рустави",
    "ზუგდიდი": "Зугдиди",
    "ფოთი": "Поти",
    "გორი": "Гори",
    "თელავი": "Телави",
    "მცხეთა": "Мцхета",
    "ოზურგეთი": "Озургети",
    "ახალციხე": "Ахалцихе",
    "ამბროლაური": "Амбролаури",
    "ზესტაფონი": "Зестафони",
    "სამტრედია": "Самтредиа",
    "სენაკი": "Сенаки",
    "ხაშური": "Хашури",
    "სურამი": "Сурами",
    "წყნეთი": "Цкнети",
    "მარნეული": "Марнеули",
    "დმანისი": "Дманиси",
    "გურჯაანი": "Гурджаани",
    "საბურთალო": "Сабуртало",
    "ვაკე": "Ваке",
    "გლდანი": "Глдани",
    "დიდუბე": "Дидубе",
    "ისანი": "Исани",
    "სამგორი": "Самгори",
    "მთაწმინდა": "Мтацминда",
    "ჩუღურეთი": "Чугурети",
    "ნაძალადევი": "Надзаладеви",
    "ავლაბარი": "Авлабари",
    "ვარკეთილი": "Варкетили",
    "დიღომი": "Дигоми",
    "სადღეღამისო": "круглосуточно",
    "აფთიაქი": "аптека",
    "სადგური": "Садгури",
    # Расписания: «შაბ/9.00-15.00» без словаря читалось бы как «шаб/9.00-15.00».
    "ყოველდღე": "ежедневно",
    "შაბათ-კვირა": "сб-вс",
    "დასვენება": "выходной",
    "დასვენების": "выходной",
    "ორშ": "пн",
    "სამშ": "вт",
    "ოთხ": "ср",
    "ხუთ": "чт",
    "პარ": "пт",
    "შაბ": "сб",
    "კვ": "вс",
    "შაბათი": "суббота",
    "კვირა": "воскресенье",
}


def _build_pattern(overrides: Dict[str, str]) -> "re.Pattern":
    """Словарные замены, длинные раньше коротких.

    Границы проверяем не через \\b, а lookaround'ами: ключи бывают с точкой на
    конце («გამზ.»), а соседом справа бывает не пробел, а слеш («კვ/9.00»).
    Без границ короткий ключ «კვ» влезал бы внутрь слова «კვირა».
    """
    keys = sorted(overrides, key=len, reverse=True)
    body = "|".join(re.escape(key) for key in keys)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)")


_OVERRIDES_RE = _build_pattern(KA_OVERRIDES)


def ka_to_ru(text: str) -> str:
    """Грузинский текст кириллицей. Известное берётся из словаря целиком.

    Адреса сюда не попадают: улицу показываем как есть, на грузинском.
    """
    return convert(text, KA_OVERRIDES, _OVERRIDES_RE)


def convert(
    text: str,
    overrides: Dict[str, str],
    pattern: "re.Pattern",
    gap: Optional[Callable[[str], str]] = None,
) -> str:
    """Заменить словарные куски, остальное отдать `gap` (по умолчанию — побуквенно).

    Вынесено отдельно, потому что тем же способом переводятся формы выпуска
    (forms.py): словарь там свой и с промежутками — названиями брендов — надо
    обойтись иначе, а механика одна и та же.
    """
    if not text:
        return text

    gap = gap or _ka_letters
    result = []
    position = 0
    for match in pattern.finditer(text):
        result.append(gap(text[position:match.start()]))
        result.append(overrides[match.group(0)])
        position = match.end()
    result.append(gap(text[position:]))
    return "".join(result)


build_pattern = _build_pattern


def _ka_letters(text: str) -> str:
    return "".join(KA_TO_RU.get(char, char) for char in text)


# --- грузиница → латиница --------------------------------------------------

KA_TO_LAT: Dict[str, str] = {
    # Национальная система романизации (2002) — та же, что на дорожных знаках
    # и в Google Maps. Гортанные (კ, პ, ტ, ყ, წ, ჭ) пишутся в ней с апострофом;
    # апостроф выкидываем: в названии аптеки он только мешает читать.
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
    "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
    # вышедшие из употребления, изредка попадаются в старых записях
    "ჱ": "ey", "ჲ": "y", "ჳ": "w", "ჴ": "kh", "ჵ": "o", "ჶ": "f",
}

KA_TO_LAT_OVERRIDES: Dict[str, str] = {
    # Сети и слова, у которых есть собственное латинское написание: по системе
    # вышло бы «Aversi» верно, а вот «ფარმა-» даёт «parma-», потому что ფ — это p.
    # Список конечный, ведём вручную.
    "აფთიაქი": "Aptiaqi",
    "ავერსი": "Aversi",
    "პსპ": "PSP",
    "ჯიპისი": "GPC",
    "ფარმადეპო": "Pharmadepo",
    "ფარმაგიდი": "Pharmagidi",
    "ფარმაცია": "Pharmacia",
    "გეფა": "Gepha",
}

_KA_TO_LAT_OVERRIDES_RE = _build_pattern(KA_TO_LAT_OVERRIDES)
_KA_WORD_RE = re.compile(r"[Ⴀ-ჿ]+")


def ka_to_latin(text: str) -> str:
    """Грузинский текст латиницей. Слова с большой буквы — это имена собственные.

    Нужна для названий аптек: латиница читается и произносится всеми, а русский
    транслит вывески («Пармагиди») не поможет ни спросить дорогу, ни найти сеть
    в картах.
    """
    return convert(text, KA_TO_LAT_OVERRIDES, _KA_TO_LAT_OVERRIDES_RE, gap=_ka_latin_words)


def _ka_latin_words(text: str) -> str:
    """Побуквенно, слово за словом. Латиница и цифры вокруг остаются как есть."""
    def one(match: "re.Match") -> str:
        word = "".join(KA_TO_LAT.get(char, char) for char in match.group(0))
        return word[:1].upper() + word[1:]

    return _KA_WORD_RE.sub(one, text)


# --- кириллица → латиница --------------------------------------------------

Option = Tuple[str, int]
"""Латинский вариант и его цена: 0 — обычное написание, больше — экзотика."""

_RU_TO_LAT: Dict[str, Sequence[Option]] = {
    "а": (("a", 0),), "б": (("b", 0),), "в": (("v", 0), ("w", 3)),
    "д": (("d", 0),), "е": (("e", 0),), "ё": (("e", 0), ("yo", 2)),
    "ж": (("j", 0), ("zh", 1), ("g", 3)), "з": (("z", 0), ("s", 3)),
    "и": (("i", 0), ("y", 3)), "й": (("y", 0), ("i", 1), ("", 2)),
    "л": (("l", 0),), "м": (("m", 0),), "н": (("n", 0),), "о": (("o", 0),),
    "п": (("p", 0),), "р": (("r", 0),), "с": (("s", 0), ("c", 3)),
    "т": (("t", 0), ("th", 2)), "у": (("u", 0), ("ou", 3)),
    "ч": (("ch", 0), ("tch", 3)), "ш": (("sh", 0), ("ch", 3)),
    "щ": (("sch", 0), ("sh", 1)), "ъ": (("", 0),),
    "ы": (("y", 0), ("i", 1)), "ь": (("", 0), ("i", 2)), "э": (("e", 0),),
    "ю": (("yu", 0), ("iu", 1), ("u", 2)),
    "я": (("ya", 0), ("ia", 1), ("a", 2)),
}

_FRONT_VOWELS = "еиэя"
"""Перед ними латинская c читается как «ц» — это меняет выбор буквы."""

_VOWELS = "аеёиоуыэюя"

MAX_CANDIDATES = 8
_BEAM = 32
"""Сколько частичных вариантов тащим дальше на каждом шаге."""


def ru_to_latin_candidates(text: str, limit: int = MAX_CANDIDATES) -> List[str]:
    """Ранжированный список латинских написаний. Первый — самый вероятный."""
    text = text.strip().lower()
    if not text:
        return []

    beam: List[Tuple[int, str]] = [(0, "")]
    position = 0
    while position < len(text):
        options, consumed = _options(text, position)
        expanded = [
            (cost + option_cost, prefix + option)
            for cost, prefix in beam
            for option, option_cost in options
        ]
        expanded.sort(key=lambda item: item[0])
        beam = expanded[:_BEAM]
        position += consumed

    seen = set()
    result = []
    for _, candidate in beam:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
        if len(result) == limit:
            break
    return result


def ru_to_latin(text: str) -> str:
    """Самый вероятный вариант — когда перебирать некогда."""
    candidates = ru_to_latin_candidates(text, limit=1)
    return candidates[0] if candidates else ""


def _options(text: str, position: int) -> Tuple[Sequence[Option], int]:
    """Варианты латинской записи для буквы (или пары) и сколько букв съели."""
    char = text[position]
    following = text[position + 1] if position + 1 < len(text) else ""

    if char == "к":
        if following == "с":
            return (("x", 0), ("ks", 1), ("cs", 3)), 2
        # «ке», «ки» через c читались бы как «це», «ци» — остаётся только k
        if following and following in _FRONT_VOWELS:
            return (("k", 0),), 1
        return (("c", 0), ("k", 1)), 1

    if char == "ц":
        # Перед e/i латинская c и так звучит как «ц»: citramon, cefazolin
        if following and following in _FRONT_VOWELS:
            return (("c", 0),), 1
        return (("ts", 0), ("c", 1), ("z", 2)), 1

    if char == "х":
        # В начале слова перед согласной это почти всегда греческое ch-:
        # хлор → chlor, хром → chrom. В середине слова — скорее h.
        if position == 0 and following and following not in _VOWELS:
            return (("ch", 0), ("h", 1), ("kh", 2), ("x", 3)), 1
        return (("h", 0), ("ch", 1), ("kh", 1), ("x", 2)), 1

    if char == "г":
        # heparin, но gentamicin — обе ветки живые
        return (("g", 0), ("h", 1)), 1

    if char == "ф":
        # ibuprofen, но morphine
        return (("f", 0), ("ph", 1)), 1

    options = _RU_TO_LAT.get(char)
    if options is None:
        return ((char, 0),), 1
    return options, 1


def shorten(query: str, ratio: float = 0.65) -> str:
    """Обрезать запрос до префикса.

    Сайт ищет по началу строки, поэтому расхождение в хвосте («цефтриаксон» →
    `ceftriaxone`, а не `ceftriakson`) лечится тем, что хвост просто отбрасывается.
    """
    keep = max(MIN_QUERY_LENGTH, int(len(query) * ratio))
    return query[:keep]
