"""Сообщения администратору о поломках.

Бот живёт на сервере, логи туда никто не ходит читать. Если mis.ge поменяет
вёрстку, парсер начнёт падать, пользователь увидит вежливое «скоро починим» —
и на этом всё закончится, потому что «скоро» никому не поручено.

Поэтому о поломке бот пишет сам: и о разборе, и о том, что источник перестал
отвечать или начал отвечать отказом. С двумя оговорками:

* одинаковые поломки шлются не чаще раза в час, иначе при сломанном сайте
  админ получит сотни сообщений подряд;
* в текст не попадает запрос пользователя — их мы не логируем и не пересылаем.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

log = logging.getLogger(__name__)

COOLDOWN = timedelta(hours=1)


class Alerter:
    def __init__(
        self,
        bot,
        chat_id: Optional[int],
        *,
        cooldown: timedelta = COOLDOWN,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._cooldown = cooldown
        self._last_sent: Dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._chat_id is not None

    async def parser_broken(self, where: str, detail: str) -> None:
        """Разбор ответа сайта не удался — скорее всего, поменялась вёрстка."""
        await self._send(
            key=f"parser:{where}",
            text=(
                f"⚠️ Не разобрался в ответе mis.ge: <b>{where}</b>\n\n"
                f"<code>{detail}</code>\n\n"
                "Похоже, на сайте поменялась вёрстка. Снимите свежие фикстуры "
                "(<code>python -m misbot.cli нурофен --save-html tests/fixtures</code>) "
                "и посмотрите, что отвалилось.\n\n"
                "<i>Запрос пользователя не прикладываю: мы их не сохраняем.</i>"
            ),
        )

    async def site_down(self, reason: str, blocked: bool, downtime: timedelta) -> None:
        """Сайт-источник не отвечает дольше терпимого — или не пускает вовсе.

        Решение «пора говорить» принимает health.py: одиночные сбои сюда не
        доходят. Здесь только текст и защита от повторов.
        """
        if blocked:
            await self._send(
                key="site:blocked",
                text=(
                    "⛔️ mis.ge не пускает бота\n\n"
                    f"<code>{reason}</code>\n\n"
                    "Сайт жив и отвечает отказом — само это не пройдёт. "
                    "Скорее всего, мы ему надоели частотой запросов или "
                    "не понравился <code>User-Agent</code>. Стоит сбавить темп "
                    "и написать на info@mis.ge."
                ),
            )
            return

        await self._send(
            key="site:down",
            text=(
                f"🔌 mis.ge не отвечает уже {_minutes(downtime)}\n\n"
                f"<code>{reason}</code>\n\n"
                "Бот пока отвечает пользователям «сайт не отвечает». "
                "Если mis.ge открывается у вас в браузере — дело не в нём, "
                "а в сети на сервере."
            ),
        )

    async def site_up(self, downtime: timedelta) -> None:
        """Сайт снова отвечает. Шлётся только если о поломке уже говорили."""
        await self._send(
            key="site:up",
            text=f"✅ mis.ge снова отвечает. Не работал около {_minutes(downtime)}.",
        )

    async def _send(self, key: str, text: str) -> None:
        if self._chat_id is None:
            return

        now = datetime.now(timezone.utc)
        last = self._last_sent.get(key)
        if last is not None and now - last < self._cooldown:
            log.debug("алерт «%s» придержан до конца паузы", key)
            return

        self._last_sent[key] = now
        try:
            await self._bot.send_message(self._chat_id, text)
        except Exception as exc:  # noqa: BLE001 — падать из-за алерта нельзя
            log.error("не удалось отправить алерт: %s", exc)


def _minutes(span: timedelta) -> str:
    """«8 минут», «2 часа» — точность до секунды здесь никому не нужна."""
    total = int(span.total_seconds())
    if total < 60:
        return f"{total} с"
    if total < 3600:
        return f"{total // 60} мин"
    return f"{total // 3600} ч {total % 3600 // 60} мин"
