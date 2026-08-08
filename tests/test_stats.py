"""Тесты счётчиков. База — временная, сети не требуют."""

import pytest

from misbot import formatting as fmt
from misbot.stats import (
    FOUND,
    NOTHING,
    SEARCH,
    STOCKS,
    Stats,
    count,
)


@pytest.fixture
async def stats(tmp_path):
    store = await Stats(tmp_path / "stats.sqlite3").open()
    yield store
    await store.close()


class TestCounters:
    async def test_events_add_up(self, stats):
        for _ in range(3):
            await stats.record(SEARCH, user_id=1)
        today, _week, total = await stats.report()
        assert today.searches == 3
        assert total.searches == 3

    async def test_events_are_counted_separately(self, stats):
        await stats.record(SEARCH, user_id=1)
        await stats.record(FOUND)
        await stats.record(STOCKS, user_id=1)
        today, _week, _total = await stats.report()
        assert (today.searches, today.found, today.stocks) == (1, 1, 1)

    async def test_survives_reopening(self, tmp_path):
        path = tmp_path / "reopen.sqlite3"
        async with Stats(path) as first:
            await first.record(SEARCH, user_id=1)
        async with Stats(path) as second:
            await second.record(SEARCH, user_id=1)
            today, _week, _total = await second.report()
        assert today.searches == 2

    async def test_empty_report_is_zeroes(self, stats):
        today, week, total = await stats.report()
        assert (today.searches, week.searches, total.searches) == (0, 0, 0)
        assert today.hit_rate is None

    async def test_hit_rate(self, stats):
        await stats.record(FOUND)
        await stats.record(FOUND)
        await stats.record(FOUND)
        await stats.record(NOTHING)
        today, _week, _total = await stats.report()
        assert today.hit_rate == 0.75

    async def test_periods_are_labelled(self, stats):
        labels = [period.label for period in await stats.report(days=7)]
        assert labels == ["сегодня", "за 7 дней", "всего"]


class TestVisitors:
    async def test_the_same_person_is_counted_once(self, stats):
        for _ in range(5):
            await stats.record(SEARCH, user_id=7)
        today, _week, _total = await stats.report()
        assert today.searches == 5
        assert today.people == 1

    async def test_different_people_are_counted_apart(self, stats):
        await stats.record(SEARCH, user_id=1)
        await stats.record(SEARCH, user_id=2)
        today, _week, _total = await stats.report()
        assert today.people == 2

    async def test_events_without_a_person_are_still_counted(self, stats):
        # Ошибки сайта считаем, но приписывать их человеку незачем.
        await stats.record(NOTHING)
        today, _week, _total = await stats.report()
        assert today.nothing == 1
        assert today.people == 0

    async def test_telegram_id_is_not_stored(self, stats):
        await stats.record(SEARCH, user_id=123456789)
        cursor = await stats._connection.execute("SELECT person FROM stats_visitors")
        stored = [row["person"] for row in await cursor.fetchall()]
        await cursor.close()
        assert stored and all("123456789" not in person for person in stored)

    async def test_the_salt_differs_between_databases(self, tmp_path):
        # Иначе хеш одного и того же id совпал бы у всех, кто ставил бота.
        async with Stats(tmp_path / "one.sqlite3") as one:
            async with Stats(tmp_path / "two.sqlite3") as two:
                assert one._person(1) != two._person(1)

    async def test_the_salt_survives_reopening(self, tmp_path):
        path = tmp_path / "salt.sqlite3"
        async with Stats(path) as first:
            person = first._person(1)
        async with Stats(path) as second:
            assert second._person(1) == person


class TestCountHelper:
    async def test_none_is_a_no_op(self):
        await count(None, SEARCH, 1)  # не должно падать

    async def test_records_when_present(self, stats):
        await count(stats, SEARCH, 1)
        today, _week, _total = await stats.report()
        assert today.searches == 1

    async def test_a_broken_database_does_not_break_the_bot(self, stats):
        await stats.close()
        await count(stats, SEARCH, 1)  # соединения нет — просто ничего не делаем


class TestStatsText:
    async def test_shows_every_period(self, stats):
        await stats.record(SEARCH, user_id=1)
        text = fmt.stats_text(await stats.report())
        assert "сегодня" in text and "за 7 дней" in text and "всего" in text
        assert "запросов: 1" in text

    async def test_says_what_is_not_stored(self, stats):
        text = fmt.stats_text(await stats.report())
        assert "текстов запросов" in text
