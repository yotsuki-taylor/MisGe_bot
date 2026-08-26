"""Тесты учёта доступности сайта.

Главное здесь — про что бот молчит. Сообщать о каждом моргании источника значит
приучить владельца не читать сообщения бота.
"""

from datetime import timedelta

import pytest

from misbot.health import SiteHealth


class Recorder:
    """Запоминает, о чём позвали, вместо отправки в телеграм."""

    def __init__(self) -> None:
        self.downs = []
        self.ups = []

    async def down(self, reason: str, blocked: bool, downtime: timedelta) -> None:
        self.downs.append((reason, blocked, downtime))

    async def up(self, downtime: timedelta) -> None:
        self.ups.append(downtime)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def health(recorder) -> SiteHealth:
    # Порог нулевой: время в тестах не ждём, длительность проверяем отдельно.
    return SiteHealth(
        on_down=recorder.down, on_up=recorder.up, down_after=timedelta(0)
    )


class TestSilence:
    async def test_a_single_failure_says_nothing(self, recorder):
        health = SiteHealth(on_down=recorder.down, on_up=recorder.up, down_after=timedelta(0))
        await health.failed("таймаут")
        assert recorder.downs == []

    async def test_a_short_streak_says_nothing(self, recorder):
        # Две неудачи подряд, но порог по времени ещё не вышел.
        health = SiteHealth(on_down=recorder.down, down_after=timedelta(minutes=10))
        await health.failed("таймаут")
        await health.failed("таймаут")
        assert recorder.downs == []

    async def test_recovery_after_silence_is_also_silent(self, recorder):
        # Если о поломке не говорили, «всё снова хорошо» только сбивает с толку.
        health = SiteHealth(on_down=recorder.down, on_up=recorder.up, down_after=timedelta(0))
        await health.failed("таймаут")
        await health.recovered()
        assert recorder.ups == []

    async def test_success_without_failures_costs_nothing(self, health, recorder):
        await health.recovered()
        assert (recorder.downs, recorder.ups) == ([], [])


class TestReporting:
    async def test_a_long_streak_is_reported(self, health, recorder):
        await health.failed("таймаут")
        await health.failed("таймаут")

        assert len(recorder.downs) == 1
        reason, blocked, _ = recorder.downs[0]
        assert (reason, blocked) == ("таймаут", False)

    async def test_reported_only_once_per_streak(self, health, recorder):
        for _ in range(5):
            await health.failed("таймаут")
        assert len(recorder.downs) == 1

    async def test_recovery_is_reported_after_a_report(self, health, recorder):
        await health.failed("таймаут")
        await health.failed("таймаут")
        await health.recovered()

        assert len(recorder.ups) == 1

    async def test_a_new_streak_is_reported_again(self, health, recorder):
        await health.failed("таймаут")
        await health.failed("таймаут")
        await health.recovered()
        await health.failed("таймаут")
        await health.failed("таймаут")

        assert len(recorder.downs) == 2


class TestBlocked:
    async def test_a_block_is_reported_immediately(self, recorder):
        # Блокировку не пересиживают: сайт жив и будет отвечать отказом дальше.
        health = SiteHealth(on_down=recorder.down, down_after=timedelta(hours=1))
        await health.failed("403 Forbidden", blocked=True)

        assert len(recorder.downs) == 1
        assert recorder.downs[0][1] is True

    async def test_a_block_still_reports_only_once(self, recorder):
        health = SiteHealth(on_down=recorder.down, down_after=timedelta(hours=1))
        await health.failed("403", blocked=True)
        await health.failed("403", blocked=True)

        assert len(recorder.downs) == 1


class TestState:
    async def test_tracks_the_streak(self, health):
        assert health.down_since is None
        await health.failed("таймаут")
        assert health.down_since is not None
        assert health.failures == 1

    async def test_recovery_clears_the_streak(self, health):
        await health.failed("таймаут")
        await health.failed("таймаут")
        await health.recovered()

        assert health.down_since is None
        assert health.failures == 0
        assert not health.reported

    async def test_works_without_callbacks(self):
        # Консольный прототип и тесты создают клиент без алертов.
        health = SiteHealth(down_after=timedelta(0))
        await health.failed("таймаут")
        await health.failed("таймаут")
        await health.recovered()
