"""Наличие препарата в аптеках: сначала кеш, потом сайт.

Слой между ботом и парой «клиент + кеш». Отдельно от [[pharmacies]], потому что
там карточки аптек с их девяностодневным сроком жизни, а здесь остатки, которые
живут полчаса.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .mis_client import MAX_MEDICINES_PER_REQUEST, MisClient, MisUnavailable
from .models import Medicine, Stock
from .parser import parse_pharmacies
from .stock_cache import StockCache

log = logging.getLogger(__name__)


async def count_by_medicine(
    client: MisClient,
    cache: Optional[StockCache],
    medicines: Sequence[Medicine],
    *,
    city: int = 0,
) -> Dict[str, int]:
    """Сколько аптек держит каждый препарат. Ключ — хеш препарата.

    Один POST на всю страницу выдачи: сайт принимает до 13 хешей за раз, а
    показываем мы восемь.

    Сопоставлять ответ с запросом приходится по тройке «название, страна,
    компания»: строки наличия хеша препарата не содержат. Тройка различает даже
    те случаи, когда у восьми препаратов одинаковое название и разнятся только
    производитель и страна, — а это на mis.ge обычное дело.
    """
    wanted = [m for m in medicines if m.hash][:MAX_MEDICINES_PER_REQUEST]
    if not wanted:
        return {}

    hashes = [m.hash for m in wanted]
    key = "+".join(sorted(hashes))
    where = {"city": city, "district": 0, "subdistrict": 0}

    cached = await cache.get(key, **where) if cache is not None else None
    if cached is not None and cached.fresh:
        stocks = parse_pharmacies(cached.html)
    else:
        html = await client.pharmacies(hashes, **where)
        stocks = parse_pharmacies(html)
        if cache is not None:
            await cache.put(key, html, **where)

    pharmacies: Dict[Tuple[str, str, str], Set[object]] = defaultdict(set)
    for stock in stocks:
        identity = stock.pharmacy_id if stock.pharmacy_id is not None else stock.pharmacy_name
        pharmacies[(stock.medicine_name, stock.country, stock.company)].add(identity)

    return {
        medicine.hash: len(
            pharmacies.get((medicine.name, medicine.country, medicine.company), ())
        )
        for medicine in wanted
    }


MAX_COUNTED = 3 * MAX_MEDICINES_PER_REQUEST
"""Сколько препаратов готовы посчитать ради сортировки.

Наличие приходит пакетами по тринадцать, и каждый пакет — секунда по нашему же
rate-limit. Три секунды ожидания за то, чтобы имеющееся в аптеках оказалось
наверху, — разумный размен; шестнадцать секунд на две сотни аналогов — уже нет.
"""


async def count_all(
    client: MisClient,
    cache: Optional[StockCache],
    medicines: Sequence[Medicine],
    *,
    city: int = 0,
) -> Dict[str, int]:
    """Наличие для всего списка, пакетами по тринадцать хешей.

    Нужно, чтобы отсортировать выдачу: решать, что показывать выше, можно только
    зная про все препараты сразу, а не про видимую страницу.
    """
    counts: Dict[str, int] = {}
    wanted = [m for m in medicines if m.hash]
    for start in range(0, len(wanted), MAX_MEDICINES_PER_REQUEST):
        batch = wanted[start:start + MAX_MEDICINES_PER_REQUEST]
        counts.update(await count_by_medicine(client, cache, batch, city=city))
    return counts


def in_stock_first(
    medicines: Sequence[Medicine],
    counts: Optional[Dict[str, int]],
) -> List[Medicine]:
    """Сначала то, что есть в аптеках, потом остальное.

    Сортировка стабильная, поэтому внутри обеих групп сохраняется порядок сайта:
    он не случайный — там рядом стоят разные фасовки одного препарата.

    Без чисел (счёт не удался или список слишком длинный) порядок не трогаем:
    выдумывать его на неполных данных хуже, чем оставить как есть.
    """
    if not counts:
        return list(medicines)
    return sorted(medicines, key=lambda medicine: 0 if counts.get(medicine.hash) else 1)


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
