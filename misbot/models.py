"""Модели данных. Ничего не знают ни об HTTP, ни об HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class Medicine:
    """Строка выдачи поиска по названию препарата."""

    hash: str
    """Имя чекбокса в форме — идентификатор препарата. Стабилен между запросами."""

    name: str
    generic: str
    """Международное название (МНН)."""

    generic_hash: Optional[str]
    country: str
    company: str
    registration: str
    """Номер регистрации и срок её действия, как одна строка. Часто пустой."""

    dispensing: str
    """Режим отпуска: группа и нужен ли рецепт. Часто пустой."""

    @property
    def card_url(self) -> str:
        return f"http://www.mis.ge/mis_medikamenti.mis?{self.hash}=m"


@dataclass(frozen=True)
class Stock:
    """Остаток препарата в конкретной аптеке."""

    medicine_name: str
    country: str
    company: str

    price: Optional[Decimal]
    """None, если сайт отдал 0.00 — это «нет данных», а не бесплатно."""

    expiry: Optional[date]
    """Срок годности. None, если пусто или заглушка 1900-01-01."""

    pharmacy_id: Optional[int]
    pharmacy_name: str
    round_the_clock: bool
    """Аптека круглосуточная (в ячейке второй строкой стоит «სადღეღამისო»)."""

    updated: Optional[date]
    """Дата обновления остатка. У части аптек отстаёт на год+ — показывать всегда."""

    city: str
    district: str
    subdistrict: str

    @property
    def pharmacy_url(self) -> Optional[str]:
        if self.pharmacy_id is None:
            return None
        return f"http://www.mis.ge/mis_aftiaqi.mis?{self.pharmacy_id}=a"

    @property
    def is_stale(self) -> bool:
        """Остаток не обновляли больше двух месяцев."""
        if self.updated is None:
            return True
        return (date.today() - self.updated).days > 60


@dataclass(frozen=True)
class Pharmacy:
    """Карточка аптеки: mis_aftiaqi.mis?<id>=a.

    Данные почти неизменные — адрес и телефон живут годами, поэтому карточка
    кешируется надолго (см. cache.py) и лишний раз с сайта не тянется.
    """

    id: int
    legal_name: str
    """Юрлицо, например «шпс Геа». Пользователю обычно интереснее вывеска."""

    brand: str
    """Вывеска — то, что написано на аптеке снаружи."""

    address: str
    landmark: str
    """Ориентир: «напротив архива»."""

    hours: str
    phone: str
    map_url: str

    @property
    def display_name(self) -> str:
        return self.brand or self.legal_name

    @property
    def coordinates(self) -> Optional["tuple[float, float]"]:
        """Широта и долгота из ссылки на Google Maps, если она там есть."""
        match = re.search(r"q=(-?\d+\.\d+)[,\s]+(-?\d+\.\d+)", self.map_url or "")
        if match is None:
            return None
        return float(match.group(1)), float(match.group(2))


@dataclass(frozen=True)
class Location:
    """Пункт справочника городов / районов / микрорайонов."""

    id: int
    name: str


@dataclass(frozen=True)
class Locations:
    cities: "list[Location]"
    districts: "list[Location]"
    subdistricts: "list[Location]"
