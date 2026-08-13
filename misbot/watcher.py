"""Фоновая проверка подписок.

Планировщика здесь нет намеренно. Задача — «проверить каждую подписку раз в
сутки», и для неё не нужен cron: воркер просыпается раз в несколько минут и
берёт те подписки, которые давно не проверяли. Такая схема сама переживает
перезапуск (а он на сервере случается при каждой выкладке): ни одна проверка не
теряется и ни одна не выполняется дважды, потому что состояние — это поле
`checked_at` в базе, а не расписание в памяти процесса.

Проверки идут по одной: клиент к mis.ge и так держит лимит в запрос в секунду,
и обгонять живых пользователей фоновой работой ни к чему.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from .mis_client import MisClient, MisUnavailable
from .models import Stock
from .parser import ParseError
from .stock_cache import StockCache
from .stocks import find_stocks
from .watches import CHECK_EVERY, Watch, WatchStore

log = logging.getLogger(__name__)

WAKE_EVERY = 600
"""Секунд между заходами. Раз в десять минут — достаточно для суточной задачи."""

BATCH = 20
"""Сколько подписок берём за один заход, чтобы не занимать клиент надолго."""

APPEARED = "appeared"
CHEAPER = "cheaper"


def best_price(stocks: Sequence[Stock]) -> Optional[Decimal]:
    """Самая низкая известная цена. None — если препарата нет или цен нет."""
    prices = [stock.price for stock in stocks if stock.price is not None]
    return min(prices) if prices else None


def decide(watch: Watch, stocks: Sequence[Stock]) -> Optional[str]:
    """О чём стоит написать пользователю — или None, если писать не о чем.

    Пишем только про хорошие новости: появился и подешевел. Про то, что препарат
    закончился, молчим — с этим человек всё равно ничего не сделает, а
    уведомление раз в сутки «всё ещё нет» быстро превращается в спам.
    """
    now_available = bool(stocks)
    price = best_price(stocks)

    if now_available and not watch.available:
        return APPEARED

    if (
        now_available
        and price is not None
        and watch.best_price is not None
        and price < watch.best_price
    ):
        return CHEAPER

    return None


async def check_once(
    client: MisClient,
    cache: Optional[StockCache],
    watches: WatchStore,
    *,
    batch: int = BATCH,
    every: timedelta = CHECK_EVERY,
) -> List[Tuple[Watch, str, List[Stock]]]:
    """Проверить порцию подписок. Возвращает те, о которых стоит написать."""
    due = await watches.due(limit=batch, every=every)
    if not due:
        return []

    log.info("проверяю подписок: %d", len(due))
    news: List[Tuple[Watch, str, List[Stock]]] = []

    for watch in due:
        try:
            stocks = await find_stocks(client, cache, watch.medicine, city=watch.city)
        except MisUnavailable:
            # Отмечаем попытку, чтобы не долбить лежащий сайт по кругу.
            log.warning("подписка %s: сайт не ответил", watch.medicine)
            await watches.touch(watch)
            continue
        except ParseError as exc:
            log.error("подписка %s: не разобрал ответ (%s)", watch.medicine, exc)
            await watches.touch(watch)
            continue

        reason = decide(watch, stocks)
        await watches.record_check(
            watch,
            available=bool(stocks),
            best_price=best_price(stocks),
            name=stocks[0].medicine_name if stocks else "",
        )
        if reason is not None:
            news.append((watch, reason, stocks))

    return news


async def run_forever(
    client: MisClient,
    cache: Optional[StockCache],
    watches: WatchStore,
    notify,
    *,
    wake_every: int = WAKE_EVERY,
) -> None:
    """Бесконечный цикл проверок. Останавливается отменой задачи."""
    while True:
        try:
            for watch, reason, stocks in await check_once(client, cache, watches):
                await notify(watch, reason, stocks)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — цикл не должен умирать
            log.exception("проверка подписок сорвалась: %s", exc)

        await asyncio.sleep(wake_every)
