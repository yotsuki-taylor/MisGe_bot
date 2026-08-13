"""Настройки бота. Читаются из окружения или из файла .env рядом с проектом."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .mis_client import DEFAULT_CONTACT

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

TOKEN_VAR = "MISGE_BOT_TOKEN"
CONTACT_VAR = "MISGE_CONTACT"
CITY_VAR = "MISGE_DEFAULT_CITY"
LOG_VAR = "MISGE_LOG_LEVEL"
DB_VAR = "MISGE_DB"
LOG_FILE_VAR = "MISGE_LOG_FILE"
ADMIN_VAR = "MISGE_ADMIN_ID"

DEFAULT_DB = ENV_FILE.parent / "misge.sqlite3"
DEFAULT_LOG_FILE = ENV_FILE.parent / "misge.log"


class ConfigError(RuntimeError):
    """Бота не с чем запускать."""


@dataclass(frozen=True)
class Config:
    token: str
    contact: str = DEFAULT_CONTACT
    default_city: int = 0
    """Город, который предлагается новому пользователю. 0 — вся Грузия."""

    log_level: str = "INFO"
    """На INFO пользовательские запросы в лог не попадают, см. privacy в README."""

    database: Path = DEFAULT_DB
    """Кеш карточек аптек и счётчики. Текстов запросов здесь нет и не будет."""

    admin_id: int = 0
    """Владелец: кому отвечает /stats и кому приходят сообщения о поломке разбора.

    0 — команда молчит для всех, включая владельца, а алерты не шлются.
    В личной переписке telegram id пользователя совпадает с id чата, поэтому
    одного значения хватает на оба применения.
    """

    log_file: Optional[Path] = DEFAULT_LOG_FILE
    """Под автозапуском консоли нет, и без файла лога непонятно, что случилось."""

    @classmethod
    def from_env(cls) -> "Config":
        load_env_file()

        token = os.environ.get(TOKEN_VAR, "").strip()
        if not token:
            raise ConfigError(
                f"не задан {TOKEN_VAR}. Возьмите токен у @BotFather и положите "
                f"в файл .env рядом с проектом:\n    {TOKEN_VAR}=123456:ABC-DEF"
            )

        return cls(
            token=token,
            contact=os.environ.get(CONTACT_VAR, DEFAULT_CONTACT).strip() or DEFAULT_CONTACT,
            default_city=_int(os.environ.get(CITY_VAR), default=0),
            log_level=os.environ.get(LOG_VAR, "INFO").strip().upper() or "INFO",
            database=Path(os.environ.get(DB_VAR, "").strip() or DEFAULT_DB),
            log_file=_log_file(os.environ.get(LOG_FILE_VAR)),
            admin_id=_int(os.environ.get(ADMIN_VAR), default=0),
        )


def load_env_file(path: Optional[Path] = None) -> None:
    """Простейший .env: KEY=value, строки с # игнорируются.

    Отдельной зависимости ради восьми строк не берём. Уже заданные переменные
    окружения приоритетнее файла — так удобнее переопределять при деплое.
    """
    path = path or ENV_FILE
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _log_file(raw: Optional[str]) -> Optional[Path]:
    """Пустое значение переменной выключает файловый лог совсем."""
    if raw is None:
        return DEFAULT_LOG_FILE
    raw = raw.strip()
    return Path(raw) if raw else None


def _int(raw: Optional[str], default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default
