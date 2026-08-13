"""Сообщения администратору о поломках.

Бот живёт на сервере, логи туда никто не ходит читать. Если mis.ge поменяет
вёрстку, парсер начнёт падать, пользователь увидит вежливое «скоро починим» —
и на этом всё закончится, потому что «скоро» никому не поручено.

Поэтому о поломке разбора бот пишет сам. С двумя оговорками:

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
