"""Поиск препарата по запросу на любом из трёх алфавитов.

Слой между транслитерацией и клиентом: решает, что и в каком порядке спросить
у mis.ge, и останавливается на первом варианте, который что-то нашёл.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import brands
from .mis_client import MisClient
from .models import Medicine
from .parser import QueryTooShort, parse_search
from .translit import (
    MIN_QUERY_LENGTH,
    is_cyrillic,
    is_georgian,
    ru_to_latin_candidates,
    shorten,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
"""Потолок обращений к сайту на один пользовательский запрос: 1 rps, ждать долго."""

AS_IS = "as-is"
BRAND = "brand"
"""Написание взято из словаря brands.py, а не подобрано по буквам."""

TRANSLIT = "translit"
PREFIX = "prefix"
INN = "inn"


@dataclass
class SearchOutcome:
    medicines: List[Medicine]
    query: str
    """Строка, которую в итоге приняли на сайте."""

    strategy: str
    tried: List[str] = field(default_factory=list)
    html: str = ""
    """Сырой ответ сайта — пригодится для кеша и для снятия фикстур."""

    @property
    def found(self) -> bool:
        return bool(self.medicines)


async def find_medicines(
    client: MisClient,
    text: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> SearchOutcome:
    """Ищет препарат, подбирая написание под то, что понимает mis.ge."""
    text = text.strip()
    if len(text) < MIN_QUERY_LENGTH:
        raise QueryTooShort(f"нужно минимум {MIN_QUERY_LENGTH} буквы")

    tried: List[str] = []
    seen: set = set()
    for query, strategy, by_generic in _plan(text, max_attempts):
        # Ключ с флагом: одна и та же строка по названию и по МНН — разные запросы.
        key = (query, by_generic)
        if key in seen or len(query) < MIN_QUERY_LENGTH:
            continue
        seen.add(key)
        tried.append(query)

        try:
            html = await client.search(query, by_generic=by_generic)
            medicines = parse_search(html)
        except QueryTooShort:
            continue

        if medicines:
            # Тексты запросов — на DEBUG: на обычном уровне лога их быть не должно.
            log.debug("«%s» → «%s» (%s), попыток %d", text, query, strategy, len(tried))
            return SearchOutcome(medicines, query, strategy, tried, html)

        if len(tried) >= max_attempts:
            break

    return SearchOutcome([], text, AS_IS, tried)


def _plan(text: str, max_attempts: int) -> List[Tuple[str, str, bool]]:
    """Что спрашивать у сайта и в каком порядке."""
    if is_georgian(text) or not is_cyrillic(text):
        # Грузиница и латиница уходят как есть, подбирать нечего.
        return [
            (text, AS_IS, False),
            (shorten(text), PREFIX, False),
            (text, INN, True),
        ]

    plan: List[Tuple[str, str, bool]] = []

    # Что знаем наверняка — спрашиваем первым: подбор по буквам до правильного
    # написания добирается пятой попыткой, а это пять секунд ожидания.
    known = brands.lookup(text)
    if known is not None:
        plan.extend((name, BRAND, False) for name in known.names)
        if known.generic:
            # Бренда может не быть в аптеках — тогда по МНН найдутся аналоги.
            plan.append((known.generic, INN, True))

    # Три обращения придерживаем на обрубленные префиксы и на поиск по МНН.
    candidates = ru_to_latin_candidates(text, limit=max(1, max_attempts - 3))
    plan.extend((c, TRANSLIT, False) for c in candidates)

    # Хвост русского названия часто расходится с латинским («цефтриаксон» →
    # ceftriaxone), а поиск идёт по началу строки — обрубаем и пробуем снова.
    plan.extend((shorten(c), PREFIX, False) for c in candidates[:2])
    if candidates:
        plan.append((candidates[0], INN, True))
    return plan
