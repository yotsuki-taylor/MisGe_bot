"""Счётчики обращений к боту.

Считаем ровно то, что нужно, чтобы понимать, живой бот или нет: сколько было
поисковых запросов, сколько из них нашлось, сколько раз смотрели аптеки и
сколько разных людей заходило за день.

**Чего здесь нет.** Текстов запросов — их бот не сохраняет и обещает это в
/about. Telegram id тоже не хранится: от него берётся хеш с солью, и по базе
можно посчитать людей, но нельзя узнать, кто они. Соль генерируется при первом
запуске и лежит рядом со счётчиками; она же делает хеш бесполезным для того,
кто заберёт базу, но не знает соли.

Живёт в том же файле SQLite, что и кеш карточек, но отдельным соединением:
кеш — про чужие данные, счётчики — про своих пользователей, и мешать их в одном
классе незачем.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stats_events (
    day    TEXT NOT NULL,
    event  TEXT NOT NULL,
    count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, event)
);
CREATE TABLE IF NOT EXISTS stats_visitors (
    day     TEXT NOT NULL,
    person  TEXT NOT NULL,
    PRIMARY KEY (day, person)
);
CREATE TABLE IF NOT EXISTS stats_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

SEARCH = "search"
"""Пользователь прислал название препарата."""

FOUND = "found"
NOTHING = "nothing"
TOO_SHORT = "too_short"
UNAVAILABLE = "unavailable"
"""Сайт-источник не ответил или отдал непонятное."""

STOCKS = "stocks"
"""Выбрана форма выпуска — показан список аптек."""

START = "start"

WEEK = 7

_SALT_KEY = "visitor_salt"


@dataclass(frozen=True)
class Period:
    """Цифры за отрезок времени."""

    label: str
    searches: int
    found: int
    nothing: int
    stocks: int
    people: int

    @property
    def hit_rate(self) -> Optional[float]:
        """Доля запросов, по которым что-то нашлось. None, если запросов не было."""
        answered = self.found + self.nothing
        return self.found / answered if answered else None


class Stats:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: Optional[aiosqlite.Connection] = None
        self._salt = ""

    async def open(self) -> "Stats":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        self._salt = await self._ensure_salt()
        return self

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> "Stats":
        return await self.open()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def record(self, event: str, user_id: int = 0) -> None:
        """Отметить событие сегодняшним днём. Ошибки наружу не выпускаем."""
        if self._connection is None:
            return

        today = date.today().isoformat()
        try:
            await self._connection.execute(
                "INSERT INTO stats_events (day, event, count) VALUES (?, ?, 1) "
                "ON CONFLICT (day, event) DO UPDATE SET count = count + 1",
                (today, event),
            )
            if user_id:
                await self._connection.execute(
                    "INSERT OR IGNORE INTO stats_visitors (day, person) VALUES (?, ?)",
                    (today, self._person(user_id)),
                )
            await self._connection.commit()
        except Exception:
            # Счётчик — не повод не ответить пользователю.
            log.warning("не записался счётчик %s", event, exc_info=True)

    async def report(self, days: int = WEEK) -> "list[Period]":
        """Три среза: сегодня, последние `days` дней, всё время."""
        today = date.today()
        since_week = (today - timedelta(days=days - 1)).isoformat()
        return [
            await self._period("сегодня", today.isoformat()),
            await self._period(f"за {days} дней", since_week),
            await self._period("всего", None),
        ]

    async def _period(self, label: str, since: Optional[str]) -> Period:
        counts = await self._counts(since)
        return Period(
            label=label,
            searches=counts.get(SEARCH, 0),
            found=counts.get(FOUND, 0),
            nothing=counts.get(NOTHING, 0),
            stocks=counts.get(STOCKS, 0),
            people=await self._people(since),
        )

    async def _counts(self, since: Optional[str]) -> Dict[str, int]:
        if self._connection is None:
            return {}
        where, params = ("WHERE day >= ?", (since,)) if since else ("", ())
        cursor = await self._connection.execute(
            f"SELECT event, SUM(count) AS total FROM stats_events {where} GROUP BY event",
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {row["event"]: row["total"] for row in rows}

    async def _people(self, since: Optional[str]) -> int:
        if self._connection is None:
            return 0
        where, params = ("WHERE day >= ?", (since,)) if since else ("", ())
        cursor = await self._connection.execute(
            f"SELECT COUNT(DISTINCT person) FROM stats_visitors {where}", params
        )
        (total,) = await cursor.fetchone()
        await cursor.close()
        return total or 0

    async def _ensure_salt(self) -> str:
        """Соль для хеша посетителя: одна на базу, генерируется при первом запуске."""
        if self._connection is None:
            return ""
        cursor = await self._connection.execute(
            "SELECT value FROM stats_meta WHERE key = ?", (_SALT_KEY,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return row["value"]

        salt = secrets.token_hex(16)
        await self._connection.execute(
            "INSERT OR IGNORE INTO stats_meta (key, value) VALUES (?, ?)", (_SALT_KEY, salt)
        )
        await self._connection.commit()
        return salt

    def _person(self, user_id: int) -> str:
        """Хеш посетителя. Соль не даёт перебрать id: их всего-то миллиарды."""
        digest = hashlib.sha256(f"{self._salt}:{user_id}".encode("utf-8"))
        return digest.hexdigest()[:32]


async def count(stats: Optional[Stats], event: str, user_id: int = 0) -> None:
    """Отметить событие, если счётчики вообще включены.

    Обёртка нужна, чтобы обработчики бота не обрастали проверками на None:
    в тестах и в консольном прототипе счётчиков нет.
    """
    if stats is not None:
        await stats.record(event, user_id)
