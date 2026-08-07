"""Кеш карточек аптек в SQLite.

Адрес, телефон и часы работы аптеки меняются раз в годы, а стоят дорого: одна
карточка — один запрос к mis.ge, то есть секунда по нашему же rate-limit. Без
кеша показать адреса у десяти аптек значило бы заставить пользователя ждать
десять секунд, и так при каждом запросе.

Это кусок шага 5, вытащенный вперёд: остатки и каталог сюда добавятся там же.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import aiosqlite

from .models import Pharmacy

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pharmacies (
    id          INTEGER PRIMARY KEY,
    legal_name  TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    landmark    TEXT NOT NULL DEFAULT '',
    hours       TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    map_url     TEXT NOT NULL DEFAULT '',
    fetched_at  TEXT NOT NULL
);
"""

TTL = timedelta(days=90)
"""Через сколько перечитывать карточку. Аптеки переезжают редко, но переезжают."""

_COLUMNS = ("id", "legal_name", "brand", "address", "landmark", "hours", "phone", "map_url")


class PharmacyCache:
    def __init__(self, path: Path, ttl: timedelta = TTL) -> None:
        self._path = path
        self._ttl = ttl
        self._connection: Optional[aiosqlite.Connection] = None

    async def open(self) -> "PharmacyCache":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        return self

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> "PharmacyCache":
        return await self.open()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def get_many(self, pharmacy_ids: Iterable[int]) -> Dict[int, Pharmacy]:
        """Всё, что уже лежит в кеше и ещё не протухло."""
        wanted = [pid for pid in dict.fromkeys(pharmacy_ids) if pid is not None]
        if not wanted or self._connection is None:
            return {}

        placeholders = ",".join("?" * len(wanted))
        cursor = await self._connection.execute(
            f"SELECT * FROM pharmacies WHERE id IN ({placeholders})", wanted
        )
        rows = await cursor.fetchall()
        await cursor.close()

        fresh: Dict[int, Pharmacy] = {}
        for row in rows:
            if self._expired(row["fetched_at"]):
                continue
            fresh[row["id"]] = Pharmacy(**{column: row[column] for column in _COLUMNS})
        return fresh

    async def put(self, pharmacy: Pharmacy) -> None:
        if self._connection is None:
            return

        await self._connection.execute(
            "INSERT OR REPLACE INTO pharmacies "
            "(id, legal_name, brand, address, landmark, hours, phone, map_url, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pharmacy.id, pharmacy.legal_name, pharmacy.brand, pharmacy.address,
                pharmacy.landmark, pharmacy.hours, pharmacy.phone, pharmacy.map_url,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._connection.commit()

    async def count(self) -> int:
        if self._connection is None:
            return 0
        cursor = await self._connection.execute("SELECT COUNT(*) FROM pharmacies")
        (total,) = await cursor.fetchone()
        await cursor.close()
        return total

    def _expired(self, fetched_at: str) -> bool:
        try:
            stamp = datetime.fromisoformat(fetched_at)
        except ValueError:
            return True
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - stamp > self._ttl
