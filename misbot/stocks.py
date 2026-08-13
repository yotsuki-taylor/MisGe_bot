"""Наличие препарата в аптеках: сначала кеш, потом сайт.

Слой между ботом и парой «клиент + кеш». Отдельно от [[pharmacies]], потому что
там карточки аптек с их девяностодневным сроком жизни, а здесь остатки, которые
живут полчаса.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .mis_client import MisClient, MisUnavailable
from .models import Stock
from .parser import parse_pharmacies
from .stock_cache import StockCache

log = logging.getLogger(__name__)


async def find_stocks(
    client: MisClient,
    cache: Optional[StockCache],
    medicine_hash: str,
    *,
    city: int = 0,
    district: int = 0,
    subdistrict: int = 0,
) -> List[Stock]:
    """Остатки препарата. Свежий кеш отдаётся сразу, без обращения к сайту.

    Если сайт недоступен, а в кеше есть просроченная запись — отдаём её.
    Цена вчерашней свежести всё равно полезнее, чем «попробуйте позже»; дату
    обновления остатка пользователь видит у каждой строки в любом случае.
    """
    where = {"city": city, "district": district, "subdistrict": subdistrict}
    cached = await cache.get(medicine_hash, **where) if cache is not None else None

    if cached is not None and cached.fresh:
        log.debug("остатки из кеша, возраст %s", cached.age)
        return parse_pharmacies(cached.html)

    try:
        html = await client.pharmacies([medicine_hash], **where)
    except MisUnavailable:
        if cached is None:
            raise
        log.warning("сайт недоступен, отдаём остатки из кеша возрастом %s", cached.age)
        return parse_pharmacies(cached.html)

    # Разбираем до записи в кеш: складывать то, что не разобралось, незачем.
    stocks = parse_pharmacies(html)
    if cache is not None:
        await cache.put(medicine_hash, html, **where)
    return stocks
