"""HTML → dataclasses.

Самый хрупкий слой: вёрстка mis.ge может поменяться в любой день. Поэтому здесь
два правила. Первое — на каждое изменение структуры парсер должен падать громко
(ParseError), а не молча возвращать пустоту. Второе — всё, что здесь есть,
покрыто тестами на сохранённых фикстурах в tests/fixtures.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from selectolax.parser import HTMLParser, Node

from .models import Location, Locations, Medicine, Pharmacy, Stock

TABLE_SELECTOR = "table#table_medikamentebi"

_COUNTERS = {
    # На странице аптек счётчиков два: сколько наименований и сколько аптек.
    # Брать первый попавшийся нельзя — нужен тот, что считает нужные нам строки.
    "search": re.compile(r"მოიძებნა\s+(\d+)\s+შედეგ"),
    "pharmacies": re.compile(r"მოიძებნა\s+(\d+)\s+აფთიაქ"),
}
_HASH_RE = re.compile(r"[?&]([0-9A-F]{32})=[mfg]", re.I)
_PHARMACY_ID_RE = re.compile(r"[?&](\d+)=a")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_ROUND_THE_CLOCK = "სადღეღამისო"
"""«Круглосуточная» — приписка второй строкой в ячейке аптеки."""

_TOO_SHORT_MARKER = "მინიმუმ 3 ასოს"
"""«для поиска нужно минимум 3 буквы» — сайт отвечает так вместо результатов."""

_EMPTY_DATES = {date(1900, 1, 1)}
"""Заглушки, которые сайт ставит вместо неизвестной даты."""

SEARCH_COLUMNS = 7
PHARMACY_COLUMNS = 10


class ParseError(RuntimeError):
    """Вёрстка сайта не та, которую мы умеем разбирать."""


class QueryTooShort(ValueError):
    """Запрос короче трёх букв — сайт такие не обслуживает."""


def parse_search(html: str) -> List[Medicine]:
    """Разбирает выдачу поиска препарата. Пустой список = «ничего не нашлось»."""
    if _TOO_SHORT_MARKER in html:
        raise QueryTooShort("нужно минимум 3 буквы")

    tree = HTMLParser(html)
    table = tree.css_first(TABLE_SELECTOR)
    if table is None:
        _require_empty(html, "search", "на странице поиска нет таблицы результатов")
        return []

    medicines: List[Medicine] = []
    for row in table.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < SEARCH_COLUMNS:
            continue

        checkbox = cells[0].css_first("input[type=checkbox]")
        med_hash = checkbox.attributes.get("name") if checkbox is not None else None
        if not med_hash:
            continue

        generic_link = cells[2].css_first("a")
        medicines.append(
            Medicine(
                hash=med_hash,
                name=_text(cells[1]),
                generic=_text(cells[2]),
                generic_hash=_hash_from_href(generic_link),
                country=_text(cells[3]),
                company=_text(cells[4]),
                registration=_text(cells[5]),
                dispensing=_text(cells[6]),
            )
        )

    if not medicines:
        _require_empty(html, "search", "таблица результатов есть, но строк не разобрано")
    return medicines


def parse_pharmacies(html: str) -> List[Stock]:
    """Разбирает выдачу «наличие в аптеках». Пустой список = «нигде нет»."""
    tree = HTMLParser(html)
    table = tree.css_first(TABLE_SELECTOR)
    if table is None:
        _require_empty(html, "pharmacies", "на странице аптек нет таблицы результатов")
        return []

    stocks: List[Stock] = []
    for row in table.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < PHARMACY_COLUMNS:
            continue

        pharmacy_cell = cells[5]
        pharmacy_text = _text(pharmacy_cell)
        pharmacy_link = pharmacy_cell.css_first("a")

        stocks.append(
            Stock(
                medicine_name=_text(cells[0]),
                country=_text(cells[1]),
                company=_text(cells[2]),
                price=_price(_text(cells[3])),
                expiry=_date(_text(cells[4])),
                pharmacy_id=_pharmacy_id(pharmacy_link),
                pharmacy_name=pharmacy_text.replace(_ROUND_THE_CLOCK, "").strip(),
                round_the_clock=_ROUND_THE_CLOCK in pharmacy_text,
                updated=_date(_text(cells[6])),
                city=_text(cells[7]),
                district=_text(cells[8]),
                subdistrict=_text(cells[9]),
            )
        )

    if not stocks:
        # Если в городе препарата нет, сайт рисует таблицу с пустым tbody.
        _require_empty(html, "pharmacies", "таблица аптек есть, но строк не разобрано")
    return stocks


CARD_LABELS = {
    "legal_name": "დასახელება",
    "brand": "ფირნიში",
    "address": "მისამართი",
    "landmark": "ორიენტირი",
    "hours": "სამუშაო დრო",
    "phone": "ტელეფონი",
    "map_url": "ლოკაცია",
}
"""Подписи строк в карточке аптеки. Порядок строк на сайте не фиксирован."""


def parse_pharmacy_card(html: str, pharmacy_id: int) -> Pharmacy:
    """Разбирает карточку аптеки.

    Карточка — таблица «подпись: значение», поэтому читаем не по номерам строк,
    а по подписям: так перестановка строк на сайте ничего не сломает.
    """
    tree = HTMLParser(html)
    fields = {}

    for row in tree.css("tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        label = _text(cells[0]).rstrip(": ").strip()
        if not label:
            continue
        link = cells[-1].css_first("a")
        fields[label] = (_text(cells[-1]), link.attributes.get("href", "") if link else "")

    if not fields:
        raise ParseError(f"карточка аптеки {pharmacy_id}: таблица не найдена")

    def value(key: str) -> str:
        return fields.get(CARD_LABELS[key], ("", ""))[0]

    location = fields.get(CARD_LABELS["map_url"], ("", ""))[1]

    pharmacy = Pharmacy(
        id=pharmacy_id,
        legal_name=value("legal_name"),
        brand=value("brand"),
        address=value("address"),
        landmark=value("landmark"),
        hours=value("hours"),
        phone=value("phone"),
        map_url=location,
    )

    if not (pharmacy.address or pharmacy.legal_name or pharmacy.brand):
        raise ParseError(f"карточка аптеки {pharmacy_id}: все поля пустые")
    return pharmacy


def parse_locations(html: str) -> Locations:
    """Достаёт справочники городов, районов и микрорайонов из <select> формы."""
    tree = HTMLParser(html)
    locations = Locations(
        cities=_options(tree, "qalaqi"),
        districts=_options(tree, "ubani"),
        subdistricts=_options(tree, "qveubani"),
    )
    if not locations.cities:
        raise ParseError("на странице нет списка городов")
    return locations


def _options(tree: HTMLParser, select_name: str) -> List[Location]:
    """Опции <select>, кроме нулевой («везде»)."""
    select = tree.css_first(f'select[name="{select_name}"]')
    if select is None:
        return []

    result: List[Location] = []
    for option in select.css("option"):
        raw_id = (option.attributes.get("value") or "").strip()
        name = _text(option)
        if not raw_id.isdigit() or int(raw_id) == 0 or not name:
            continue
        result.append(Location(id=int(raw_id), name=name))
    return result


def _require_empty(html: str, unit: str, message: str) -> None:
    """Убедиться, что строк нет именно потому, что сайт ничего не нашёл.

    Сам сайт подписывает выдачу: «მოიძებნა N …». Ноль в подписи — честный
    пустой ответ. Всё остальное значит, что вёрстка поехала и мы теряем данные.
    """
    match = _COUNTERS[unit].search(html)
    if match is None or int(match.group(1)) != 0:
        raise ParseError(message)


def _text(node: Optional[Node]) -> str:
    if node is None:
        return ""
    return " ".join(node.text(separator=" ").split())


def _hash_from_href(link: Optional[Node]) -> Optional[str]:
    if link is None:
        return None
    match = _HASH_RE.search(link.attributes.get("href") or "")
    return match.group(1) if match else None


def _pharmacy_id(link: Optional[Node]) -> Optional[int]:
    if link is None:
        return None
    match = _PHARMACY_ID_RE.search(link.attributes.get("href") or "")
    return int(match.group(1)) if match else None


def _price(raw: str) -> Optional[Decimal]:
    """0.00 у mis.ge означает «цена неизвестна», а не «бесплатно»."""
    try:
        value = Decimal(raw.replace(",", ".").strip())
    except (InvalidOperation, AttributeError):
        return None
    return value if value > 0 else None


def _date(raw: str) -> Optional[date]:
    match = _DATE_RE.search(raw or "")
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match.group(0), "%Y-%m-%d").date()
    except ValueError:
        return None
    return None if parsed in _EMPTY_DATES else parsed
