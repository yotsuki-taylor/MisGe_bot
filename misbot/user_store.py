"""Настройки пользователей в SQLite.

Выбранный город раньше лежал в памяти процесса, и каждый перезапуск сбрасывал
его всем: человек выбрал Батуми, а бот молча снова искал по Тбилиси. На сервере
перезапуск — обычное дело (деплой, перезагрузка), так что настройку надо хранить
на диске.

Что здесь не хранится: последняя выдача поиска. Она нужна только для листания,
после перезапуска бессмысленна и остаётся в памяти.

База — тот же файл, что и у кеша аптек ([[cache]]), но соединение своё: у этих
двух вещей разный срок жизни, а SQLite несколько соединений к одному файлу
переносит спокойно.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    city       INTEGER NOT NULL,
    language   TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

NO_CITY = 0
"""Город, который ставится строке, созданной ради языка.

Ноль — «не выбран»: bot.py подставляет вместо него город по умолчанию. Колонка
NOT NULL и без значения по умолчанию, а выбирать за человека город только потому,
что он выбрал язык, неправильно.
"""


class UserStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: Optional[aiosqlite.Connection] = None

    async def open(self) -> "UserStore":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        # WAL и таймаут — чтобы соединение кеша и это не спотыкались друг о друга.
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA busy_timeout=5000")
        await self._connection.executescript(SCHEMA)
        await self._add_language_column()
        await self._connection.commit()
        return self

    async def _add_language_column(self) -> None:
        """Колонка языка в базе, созданной до появления выбора языка.

        CREATE TABLE IF NOT EXISTS готовую таблицу не трогает, так что у всех,
        кто уже пользовался ботом, колонки нет и записать язык было бы некуда.
        """
        cursor = await self._connection.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in await cursor.fetchall()}
        await cursor.close()
        if "language" not in columns:
            log.info("добавляю колонку language в таблицу пользователей")
            await self._connection.execute(
                "ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT ''"
            )

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> "UserStore":
        return await self.open()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def get_city(self, user_id: int) -> Optional[int]:
        """Выбранный город или None, если пользователь его не выбирал."""
        if self._connection is None:
            return None

        cursor = await self._connection.execute(
            "SELECT city FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row["city"] if row is not None else None

    async def set_city(self, user_id: int, city: int) -> None:
        if self._connection is None:
            return

        await self._connection.execute(
            "INSERT INTO users (user_id, city, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET city = excluded.city, "
            "updated_at = excluded.updated_at",
            (user_id, city),
        )
        await self._connection.commit()

    async def get_language(self, user_id: int) -> Optional[str]:
        """Выбранный язык или None, если человек его ещё не выбирал."""
        if self._connection is None:
            return None

        cursor = await self._connection.execute(
            "SELECT language FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return row["language"] or None

    async def set_language(self, user_id: int, language: str) -> None:
        if self._connection is None:
            return

        await self._connection.execute(
            "INSERT INTO users (user_id, city, language, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET language = excluded.language, "
            "updated_at = excluded.updated_at",
            (user_id, NO_CITY, language),
        )
        await self._connection.commit()

    async def count(self) -> int:
        if self._connection is None:
            return 0
        cursor = await self._connection.execute("SELECT COUNT(*) FROM users")
        (total,) = await cursor.fetchone()
        await cursor.close()
        return total
