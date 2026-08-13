"""Аналоги — препараты с тем же действующим веществом.

Часто самое полезное, что можно сказать человеку: то же вещество продаётся под
десятком марок, и разница в цене бывает кратная.

Путь до списка — два запроса, и по-другому не выходит. Хеш вещества у нас есть
из выдачи поиска, а ручка `mis_genmed.mis` принимает не хеш, а **латинское**
название («Ibuprofen»). Взять его можно только из карточки вещества, где оно
лежит прямо в ссылке на эту же ручку.

Через хеш, а не через сохранённое название, потому что кнопка живёт в переписке
вечно, а состояние диалога — нет: нажатие на вчерашнее сообщение должно работать
так же, как на сегодняшнее.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from .mis_client import MisClient
from .models import Medicine
from .parser import parse_generic_name, parse_search

log = logging.getLogger(__name__)


async def find_analogues(client: MisClient, generic_hash: str) -> Tuple[str, List[Medicine]]:
    """Название вещества латиницей и все препараты с ним."""
    name = parse_generic_name(await client.generic_card(generic_hash))
    return name, parse_search(await client.medicines_by_generic(name))
