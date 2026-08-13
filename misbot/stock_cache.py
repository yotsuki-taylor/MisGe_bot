"""Кеш остатков в SQLite.

Наличие препарата в аптеках — самый частый запрос к mis.ge и единственный, что
идёт на сайт при каждом нажатии кнопки. При лимите в один запрос в секунду это
и очередь для пользователя, и нагрузка на чужой маленький сайт, который мы
обещали беречь.

**Хранится сырой HTML, а не разобранные строки.** Так у `Stock` остаётся одно
место, где он собирается — `parse_pharmacies`; иначе список полей пришлось бы
дублировать в сериализаторе и не забывать править оба. Разбор 13 килобайт
selectolax'ом стоит доли миллисекунды, а срок жизни записи короткий, так что
база не разрастается. Побочная выгода: правка парсера чинит и то, что уже лежит
в кеше.

Срок жизни короткий: остатки меняются в течение дня, и показать вчерашнюю цену
хуже, чем подождать секунду. Полчаса — компромисс между свежестью и тем, чтобы
не ходить на сайт по десять раз, пока человек листает выдачу.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    medicine    TEXT NOT NULL,
    city        INTEGER NOT NULL,
    district    INTEGER NOT NULL,
    subdistrict INTEGER NOT NULL,
    html        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (medicine, city, district, subdistrict)
);
"""

TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class CachedStocks:
    html: str
    fetched_at: datetime
    fresh: bool
    """False — запись просрочена. Годится только если сайт недоступен."""

    @property
    def age(self) -> timedelta:
        return datetime.now(timezone.utc) - self.fetched_at


class StockCache:
    def __init__(self, path: Path, ttl: timedelta = TTL) -> None:
        self._path = path
        self._ttl = ttl
        self._connection: Optional[aiosqlite.Connection] = None

    async def open(self) -> "StockCache":
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

    async def __aenter__(self) -> "StockCache":
        return await self.open()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def get(
        self,
        medicine: str,
        *,
        city: int = 0,
        district: int = 0,
        subdistrict: int = 0,
    ) -> Optional[CachedStocks]:
        """Запись из кеша, свежая или просроченная. Решает вызывающий."""
        if self._connection is None:
            return None

        cursor = await self._connection.execute(
            "SELECT html, fetched_at FROM stocks WHERE medicine = ? AND city = ? "
            "AND district = ? AND subdistrict = ?",
            (medicine, city, district, subdistrict),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None

        fetched_at = _parse_time(row["fetched_at"])
        if fetched_at is None:
            return None

        return CachedStocks(
            html=row["html"],
            fetched_at=fetched_at,
            fresh=datetime.now(timezone.utc) - fetched_at <= self._ttl,
        )

    async def put(
        self,
        medicine: str,
        html: str,
        *,
        city: int = 0,
        district: int = 0,
        subdistrict: int = 0,
    ) -> None:
        if self._connection is None:
            return

        await self._connection.execute(
            "INSERT OR REPLACE INTO stocks "
            "(medicine, city, district, subdistrict, html, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                medicine, city, district, subdistrict, html,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._connection.commit()

    async def prune(self, keep: timedelta = timedelta(days=1)) -> int:
        """Выбросить давно протухшее.

        Не по TTL: просроченная запись ещё пригодится, если сайт ляжет. А вот
        суточной давности уже нет, её показывать нельзя в любом случае.
        """
        if self._connection is None:
            return 0

        border = (datetime.now(timezone.utc) - keep).isoformat()
        cursor = await self._connection.execute(
            "DELETE FROM stocks WHERE fetched_at < ?", (border,)
        )
        await self._connection.commit()
        removed = cursor.rowcount or 0
        await cursor.close()
        return removed

    async def count(self) -> int:
        if self._connection is None:
            return 0
        cursor = await self._connection.execute("SELECT COUNT(*) FROM stocks")
        (total,) = await cursor.fetchone()
        await cursor.close()
        return total


def _parse_time(raw: str) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
