"""Справочник городов.

Пока живёт в памяти процесса и обновляется один раз при старте: список из 21
города меняется раз в никогда. В SQLite он переедет на шаге 2 вместе с районами.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .mis_client import MisClient, MisUnavailable
from .models import Location
from .parser import ParseError, parse_locations
from .translit import ka_to_ru

log = logging.getLogger(__name__)

EVERYWHERE = 0
EVERYWHERE_NAME = "вся Грузия"

FALLBACK_CITIES: Dict[int, str] = {
    1: "Тбилиси", 2: "Кутаиси", 3: "Амбролаури", 4: "Ахалцихе", 5: "Батуми",
    6: "Гори", 7: "Гурджаани", 8: "Дманиси", 9: "Зестафони", 10: "Зугдиди",
    11: "Телави", 12: "Марнеули", 13: "Мцхета", 14: "Озургети", 15: "Рустави",
    16: "Самтредиа", 17: "Сенаки", 18: "Поти", 19: "Цкнети", 20: "Хашури",
    21: "Сурами",
}
"""Снято с сайта 2026-08-07. Нужен, чтобы бот поднимался, даже если mis.ge лежит."""

PROBE_QUERY = "nurofen"
"""Списки городов лежат в <select> на любой странице выдачи — нужен любой запрос."""


class CityDirectory:
    def __init__(self, cities: Dict[int, str]) -> None:
        self._cities = cities

    @classmethod
    async def load(cls, client: MisClient) -> "CityDirectory":
        try:
            locations = parse_locations(await client.search(PROBE_QUERY))
            cities = {city.id: ka_to_ru(city.name) for city in locations.cities}
            log.info("справочник городов обновлён с сайта: %d", len(cities))
            return cls(cities)
        except (ParseError, MisUnavailable) as exc:
            # Без свежего списка бот всё ещё полезен — города меняются раз в никогда.
            log.warning("города с сайта не прочитались (%s), берём запасной список", exc)
            return cls(dict(FALLBACK_CITIES))

    def name(self, city_id: int) -> str:
        if city_id == EVERYWHERE:
            return EVERYWHERE_NAME
        return self._cities.get(city_id, EVERYWHERE_NAME)

    def known(self, city_id: int) -> bool:
        return city_id == EVERYWHERE or city_id in self._cities

    def all(self) -> List[Location]:
        """Города по алфавиту, Тбилиси первым — он нужен чаще всех остальных."""
        rest = sorted(
            (Location(id=cid, name=name) for cid, name in self._cities.items() if cid != 1),
            key=lambda city: city.name,
        )
        first: List[Location] = []
        if 1 in self._cities:
            first.append(Location(id=1, name=self._cities[1]))
        return first + rest
