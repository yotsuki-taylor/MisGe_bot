"""Карточки аптек: сначала из кеша, чего нет — с сайта.

Отдельный слой, потому что порядок «спросить кеш, добрать недостающее, положить
обратно» нужен и боту, и консольному прототипу.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from .cache import PharmacyCache
from .mis_client import MisClient, MisUnavailable
from .models import Pharmacy
from .parser import ParseError, parse_pharmacy_card

log = logging.getLogger(__name__)

MAX_FETCHES = 8
"""Сколько карточек добираем за раз: каждая — секунда ожидания пользователя."""


async def resolve(
    client: MisClient,
    cache: Optional[PharmacyCache],
    pharmacy_ids: Iterable[int],
    *,
    max_fetches: int = MAX_FETCHES,
) -> Dict[int, Pharmacy]:
    """Карточки для указанных аптек. Чего не добыли — просто не будет в словаре."""
    wanted: List[int] = [pid for pid in dict.fromkeys(pharmacy_ids) if pid is not None]
    if not wanted:
        return {}

    known = await cache.get_many(wanted) if cache is not None else {}
    missing = [pid for pid in wanted if pid not in known][:max_fetches]

    for pharmacy_id in missing:
        try:
            card = parse_pharmacy_card(await client.pharmacy_card(pharmacy_id), pharmacy_id)
        except MisUnavailable:
            log.warning("карточка аптеки %s: сайт не ответил", pharmacy_id)
            break  # если сайт лёг, остальные тоже не приедут
        except ParseError as exc:
            log.warning("карточка аптеки %s не разобралась: %s", pharmacy_id, exc)
            continue

        known[pharmacy_id] = card
        if cache is not None:
            await cache.put(card)

    return known


def cached_only(cache_result: Dict[int, Pharmacy], pharmacy_ids: Iterable[int]) -> bool:
    """Все ли нужные карточки уже на руках — чтобы не дёргать сайт зря."""
    return all(pid in cache_result for pid in pharmacy_ids if pid is not None)
