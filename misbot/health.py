"""Жив ли сайт-источник.

Одиночная неудача — это норма: mis.ge маленький и иногда моргает, а клиент и
так делает три попытки. Писать о ней владельцу значит приучить его пропускать
сообщения бота мимо глаз.

Поэтому здесь считается не «был ли сбой», а «сколько он длится»: сообщаем,
когда неудачи идут подряд дольше `DOWN_AFTER`, и один раз — когда сайт снова
ответил. Отдельно от этого стоит блокировка: если сайт отвечает 403 или 429, он
жив и просто нас не пускает. Само это не пройдёт, поэтому о таком говорим сразу.

Про кого «мы» знаем: состояние общее на весь процесс, потому что и живые
запросы, и фоновая проверка подписок ходят через один и тот же клиент.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)

DOWN_AFTER = timedelta(minutes=10)
"""Сколько неудачи должны идти подряд, чтобы это перестало быть рябью."""

MIN_FAILURES = 2
"""И сколько их должно быть: одна не считается, даже если между ними час."""

OnDown = Callable[[str, bool, timedelta], Awaitable[None]]
OnUp = Callable[[timedelta], Awaitable[None]]


class SiteHealth:
    def __init__(
        self,
        *,
        on_down: Optional[OnDown] = None,
        on_up: Optional[OnUp] = None,
        down_after: timedelta = DOWN_AFTER,
        min_failures: int = MIN_FAILURES,
    ) -> None:
        self._on_down = on_down
        self._on_up = on_up
        self._down_after = down_after
        self._min_failures = min_failures

        self._since: Optional[datetime] = None
        self._failures = 0
        self._reported = False

    @property
    def down_since(self) -> Optional[datetime]:
        """Когда началась текущая полоса неудач. None — сайт отвечает."""
        return self._since

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def reported(self) -> bool:
        """Уже сказали владельцу про эту полосу."""
        return self._reported

    async def failed(self, reason: str, *, blocked: bool = False) -> None:
        now = datetime.now(timezone.utc)
        if self._since is None:
            self._since = now
        self._failures += 1

        if self._reported or self._on_down is None:
            return

        downtime = now - self._since
        # Блокировку не пересиживают: сайт жив и отвечает отказом, дальше будет
        # то же самое, пока с ним не разберутся.
        long_enough = self._failures >= self._min_failures and downtime >= self._down_after
        if not (blocked or long_enough):
            return

        self._reported = True
        log.warning("сайт недоступен %s, сообщаю владельцу", downtime)
        await self._on_down(reason, blocked, downtime)

    async def recovered(self) -> None:
        """Сайт ответил. Вызывается на каждом успешном запросе, поэтому дешёвый."""
        if self._since is None:
            return

        downtime = datetime.now(timezone.utc) - self._since
        reported = self._reported
        self._since = None
        self._failures = 0
        self._reported = False

        # Молчим, если и о поломке не говорили: «всё снова хорошо» после тишины
        # только сбивает с толку.
        if reported and self._on_up is not None:
            log.info("сайт снова отвечает, лежал %s", downtime)
            await self._on_up(downtime)
