"""Слой HTTP к mis.ge. Возвращает сырой HTML и ничего не разбирает.

Сайт живёт только на plain HTTP: порт 443 не отвечает, сертификата нет.
Следствие — запросы пользователей идут по сети открытым текстом, логировать их нельзя.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable, Optional, Sequence

import httpx

log = logging.getLogger(__name__)

BASE_URL = "http://www.mis.ge"
SEARCH_PATH = "/mis_mobiluri.mis"  # мобильная вёрстка: та же выдача, разбирать проще
PHARMACIES_PATH = "/mis_aftiaqebi.mis"

DEFAULT_CONTACT = "https://t.me/misge_bot"
"""Подставляется в User-Agent, чтобы админам mis.ge было куда написать."""

MIN_INTERVAL = 1.0
"""Секунд между запросами. Сайт маленький, больше 1 rps ему не давать."""

RETRIES = 2

MAX_MEDICINES_PER_REQUEST = 13
"""Больше сайт не переваривает: на 14-м хеше он молча отдаёт пустую таблицу.

Проверено 2026-08-07 перебором. Отличить такой ответ от честного «нигде нет»
нельзя, поэтому лучше упасть на нашей стороне, чем поверить пустой выдаче.
"""


class MisUnavailable(RuntimeError):
    """Сайт не ответил или ответил ошибкой после всех попыток."""


class _RateLimiter:
    """Не даёт двум корутинам уйти на сайт чаще, чем раз в min_interval."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._min_interval - (time.monotonic() - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class MisClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        min_interval: float = MIN_INTERVAL,
        contact: str = DEFAULT_CONTACT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._limiter = _RateLimiter(min_interval)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": f"MisGeBot/0.1 (+{contact})",
                "Accept-Language": "ka,en;q=0.5",
            },
        )

    async def __aenter__(self) -> "MisClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(
        self,
        query: str,
        *,
        starts_with: bool = True,
        by_generic: bool = False,
    ) -> str:
        """Поиск препарата по названию.

        starts_with — искать по началу слова (c=1), иначе по вхождению.
        by_generic  — искать по международному названию, МНН (d=1).
        """
        params = {
            "c": "1" if starts_with else "0",
            "d": "1" if by_generic else "0",
            "user_name": query,
        }
        return await self._request("GET", SEARCH_PATH, params=params)

    async def pharmacies(
        self,
        medicine_hashes: Sequence[str],
        *,
        city: int = 0,
        district: int = 0,
        subdistrict: int = 0,
    ) -> str:
        """Наличие препаратов в аптеках. 0 в city/district/subdistrict = «везде»."""
        if not medicine_hashes:
            raise ValueError("нужен хотя бы один хеш препарата")
        if len(medicine_hashes) > MAX_MEDICINES_PER_REQUEST:
            raise ValueError(
                f"за раз можно спросить не больше {MAX_MEDICINES_PER_REQUEST} препаратов, "
                f"передано {len(medicine_hashes)}: сайт ответит пустой таблицей"
            )

        data = {"qalaqi": str(city), "ubani": str(district), "qveubani": str(subdistrict)}
        for h in medicine_hashes:
            data[h] = "on"
        return await self._request("POST", PHARMACIES_PATH, data=data)

    async def generic_card(self, generic_hash: str) -> str:
        """Карточка действующего вещества: латинское название и АТХ-классификация."""
        return await self._request("GET", f"/mis_generiki.mis?{generic_hash}=g")

    async def medicines_by_generic(self, latin_name: str) -> str:
        """Все препараты с этим действующим веществом — то есть аналоги."""
        return await self._request(
            "GET", "/mis_genmed.mis", params={"g": latin_name}
        )

    async def pharmacy_card(self, pharmacy_id: int) -> str:
        """Карточка аптеки: адрес, часы работы, телефон, точка на карте."""
        return await self._request("GET", f"/mis_aftiaqi.mis?{pharmacy_id}=a")

    async def _request(self, method: str, path: str, **kwargs) -> str:
        url = self._base_url + path
        last_error: Optional[Exception] = None

        for attempt in range(RETRIES + 1):
            await self._limiter.wait()
            try:
                response = await self._client.request(method, url, **kwargs)
                response.raise_for_status()
            except (httpx.HTTPError, httpx.StreamError) as exc:
                last_error = exc
                log.warning("mis.ge %s %s — попытка %d/%d: %s",
                            method, path, attempt + 1, RETRIES + 1, exc)
                await asyncio.sleep(1.0 * (attempt + 1))
                continue

            if response.encoding is None:
                response.encoding = "utf-8"
            return response.text

        raise MisUnavailable(f"{method} {url} не удался") from last_error
