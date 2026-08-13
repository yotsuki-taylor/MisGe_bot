"""Тесты хранилища настроек пользователей."""

import pytest

from misbot.user_store import UserStore


@pytest.fixture
async def store(tmp_path):
    async with UserStore(tmp_path / "users.sqlite3") as opened:
        yield opened


class TestUserStore:
    async def test_unknown_user_has_no_city(self, store):
        assert await store.get_city(1) is None

    async def test_roundtrip(self, store):
        await store.set_city(1, 5)
        assert await store.get_city(1) == 5

    async def test_choice_is_overwritten_not_duplicated(self, store):
        await store.set_city(1, 5)
        await store.set_city(1, 2)

        assert await store.get_city(1) == 2
        assert await store.count() == 1

    async def test_users_are_independent(self, store):
        await store.set_city(1, 5)
        await store.set_city(2, 0)

        assert await store.get_city(1) == 5
        assert await store.get_city(2) == 0

    async def test_everywhere_is_stored_not_treated_as_missing(self, store):
        # 0 — это «вся Грузия», сознательный выбор, а не отсутствие настройки.
        await store.set_city(1, 0)
        assert await store.get_city(1) == 0

    async def test_survives_reopening(self, tmp_path):
        path = tmp_path / "reopen.sqlite3"
        async with UserStore(path) as first:
            await first.set_city(7, 5)

        async with UserStore(path) as second:
            assert await second.get_city(7) == 5
            assert await second.count() == 1

    async def test_shares_a_file_with_the_pharmacy_cache(self, tmp_path):
        # В боте это один и тот же файл, два соединения. Проверяем, что они
        # не мешают друг другу.
        from misbot.cache import PharmacyCache

        path = tmp_path / "shared.sqlite3"
        async with UserStore(path) as users, PharmacyCache(path) as cache:
            await users.set_city(1, 5)
            assert await users.get_city(1) == 5
            assert await cache.count() == 0

    async def test_closed_store_does_not_raise(self, tmp_path):
        store = UserStore(tmp_path / "closed.sqlite3")
        assert await store.get_city(1) is None
        await store.set_city(1, 5)
        assert await store.count() == 0
