"""Тесты сообщений администратору о поломках."""

from datetime import timedelta
from typing import List, Tuple

import pytest

from misbot.alerts import Alerter


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.sent: List[Tuple[int, str]] = []
        self.fail = fail

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("телеграм недоступен")
        self.sent.append((chat_id, text))


class TestAlerter:
    async def test_sends_to_the_admin(self):
        bot = FakeBot()
        await Alerter(bot, 42).parser_broken("поиск препарата", "нет таблицы")

        assert len(bot.sent) == 1
        chat_id, text = bot.sent[0]
        assert chat_id == 42
        assert "поиск препарата" in text
        assert "нет таблицы" in text

    async def test_silent_without_a_chat_id(self):
        bot = FakeBot()
        alerter = Alerter(bot, None)

        await alerter.parser_broken("поиск препарата", "нет таблицы")
        assert bot.sent == []
        assert alerter.enabled is False

    async def test_repeats_are_held_back(self):
        # Сломанный сайт иначе завалит админа сотней одинаковых сообщений.
        bot = FakeBot()
        alerter = Alerter(bot, 42)

        for _ in range(10):
            await alerter.parser_broken("поиск препарата", "нет таблицы")

        assert len(bot.sent) == 1

    async def test_different_places_are_reported_separately(self):
        bot = FakeBot()
        alerter = Alerter(bot, 42)

        await alerter.parser_broken("поиск препарата", "нет таблицы")
        await alerter.parser_broken("наличие в аптеках", "нет таблицы")

        assert len(bot.sent) == 2

    async def test_reports_again_after_the_pause(self):
        bot = FakeBot()
        alerter = Alerter(bot, 42, cooldown=timedelta(seconds=-1))

        await alerter.parser_broken("поиск препарата", "нет таблицы")
        await alerter.parser_broken("поиск препарата", "нет таблицы")

        assert len(bot.sent) == 2

    async def test_never_mentions_the_user_query(self):
        bot = FakeBot()
        await Alerter(bot, 42).parser_broken("поиск препарата", "нет таблицы")

        _, text = bot.sent[0]
        assert "не сохраняем" in text

    async def test_a_failing_telegram_does_not_break_the_bot(self):
        # Алерт — вспомогательная вещь, из-за неё ронять обработчик нельзя.
        alerter = Alerter(FakeBot(fail=True), 42)
        await alerter.parser_broken("поиск препарата", "нет таблицы")

    @pytest.mark.parametrize("chat_id, expected", [(42, True), (None, False)])
    def test_enabled_flag(self, chat_id, expected):
        assert Alerter(FakeBot(), chat_id).enabled is expected
