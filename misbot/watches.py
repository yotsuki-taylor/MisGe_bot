"""Подписки на препараты в SQLite.

«Следить за препаратом» — единственная причина держать бота в списке, а не
удалить после одного поиска: нужного лекарства часто нет нигде, и человек
возвращается проверять руками.

Подписка — это тройка «кто, что, где»: пользователь, хеш препарата и город.
Рядом хранится последнее известное состояние — было ли лекарство в наличии и по
какой минимальной цене. Именно с ним сравнивается свежая выдача, чтобы писать
только когда что-то изменилось, а не каждый день.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    user_id     INTEGER NOT NULL,
    medicine    TEXT NOT NULL,
    city        INTEGER NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    available   INTEGER NOT NULL DEFAULT 0,
    best_price  TEXT,
    checked_at  TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, medicine, city)
);
"""

MAX_PER_USER = 10
"""Больше десяти — это уже не «слежу за лекарством», а нагрузка на mis.ge."""

CHECK_EVERY = timedelta(hours=20)
"""Насколько устаревшая проверка считается просроченной.

Не ровно сутки: иначе при ежедневном перезапуске проверка каждый раз чуть-чуть
не дотягивала бы до порога и не случалась никогда.
"""


@dataclass(frozen=True)
class Watch:
    user_id: int
    medicine: str
    city: int
    name: str
    available: bool
    best_price: Optional[Decimal]
    checked_at: Optional[datetime]


class WatchStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: Optional[aiosqlite.Connection] = None

    async def open(self) -> "WatchStore":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA busy_timeout=5000")
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        return self

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> "WatchStore":
        return await self.open()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def add(
        self,
        user_id: int,
        medicine: str,
        city: int,
        *,
        name: str,
        available: bool,
        best_price: Optional[Decimal],
    ) -> bool:
        """Подписать. False — если у пользователя уже слишком много подписок."""
        if self._connection is None:
            return False
        if not await self.exists(user_id, medicine, city):
            if await self.count_for(user_id) >= MAX_PER_USER:
                return False

        now = datetime.now(timezone.utc).isoformat()
        await self._connection.execute(
            "INSERT OR REPLACE INTO watches "
            "(user_id, medicine, city, name, available, best_price, checked_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, medicine, city, name, int(available),
                str(best_price) if best_price is not None else None,
                now, now,
            ),
        )
        await self._connection.commit()
        return True

    async def remove(self, user_id: int, medicine: str, city: int) -> bool:
        if self._connection is None:
            return False
        cursor = await self._connection.execute(
            "DELETE FROM watches WHERE user_id = ? AND medicine = ? AND city = ?",
            (user_id, medicine, city),
        )
        await self._connection.commit()
        removed = bool(cursor.rowcount)
        await cursor.close()
        return removed

    async def exists(self, user_id: int, medicine: str, city: int) -> bool:
        if self._connection is None:
            return False
        cursor = await self._connection.execute(
            "SELECT 1 FROM watches WHERE user_id = ? AND medicine = ? AND city = ?",
            (user_id, medicine, city),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    async def for_user(self, user_id: int) -> List[Watch]:
        if self._connection is None:
            return []
        cursor = await self._connection.execute(
            "SELECT * FROM watches WHERE user_id = ? ORDER BY created_at", (user_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_watch(row) for row in rows]

    async def due(self, limit: int = 50, every: timedelta = CHECK_EVERY) -> List[Watch]:
        """Подписки, которые пора проверить.

        Сортировка по дате проверки: если бот долго лежал, первыми пойдут те,
        кого не проверяли дольше всех.
        """
        if self._connection is None:
            return []

        border = (datetime.now(timezone.utc) - every).isoformat()
        cursor = await self._connection.execute(
            "SELECT * FROM watches WHERE checked_at IS NULL OR checked_at < ? "
            "ORDER BY checked_at LIMIT ?",
            (border, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_watch(row) for row in rows]

    async def record_check(
        self,
        watch: Watch,
        *,
        available: bool,
        best_price: Optional[Decimal],
    ) -> None:
        if self._connection is None:
            return
        await self._connection.execute(
            "UPDATE watches SET available = ?, best_price = ?, checked_at = ? "
            "WHERE user_id = ? AND medicine = ? AND city = ?",
            (
                int(available),
                str(best_price) if best_price is not None else None,
                datetime.now(timezone.utc).isoformat(),
                watch.user_id, watch.medicine, watch.city,
            ),
        )
        await self._connection.commit()

    async def touch(self, watch: Watch) -> None:
        """Отметить проверку, ничего не меняя: сайт не ответил, данных нет."""
        if self._connection is None:
            return
        await self._connection.execute(
            "UPDATE watches SET checked_at = ? "
            "WHERE user_id = ? AND medicine = ? AND city = ?",
            (
                datetime.now(timezone.utc).isoformat(),
                watch.user_id, watch.medicine, watch.city,
            ),
        )
        await self._connection.commit()

    async def count_for(self, user_id: int) -> int:
        if self._connection is None:
            return 0
        cursor = await self._connection.execute(
            "SELECT COUNT(*) FROM watches WHERE user_id = ?", (user_id,)
        )
        (total,) = await cursor.fetchone()
        await cursor.close()
        return total

    async def count(self) -> int:
        if self._connection is None:
            return 0
        cursor = await self._connection.execute("SELECT COUNT(*) FROM watches")
        (total,) = await cursor.fetchone()
        await cursor.close()
        return total


def _watch(row: aiosqlite.Row) -> Watch:
    return Watch(
        user_id=row["user_id"],
        medicine=row["medicine"],
        city=row["city"],
        name=row["name"],
        available=bool(row["available"]),
        best_price=_price(row["best_price"]),
        checked_at=_time(row["checked_at"]),
    )


def _price(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _time(raw: Optional[str]) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
