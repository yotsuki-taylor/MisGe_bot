"""Тесты конфигурации."""

import pytest

from misbot.config import (
    ADMIN_VAR,
    CITY_VAR,
    CONTACT_VAR,
    TOKEN_VAR,
    Config,
    ConfigError,
    load_env_file,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for var in (TOKEN_VAR, CONTACT_VAR, CITY_VAR, ADMIN_VAR):
        monkeypatch.delenv(var, raising=False)
    # Чтобы тест не подхватил настоящий .env разработчика.
    monkeypatch.setattr("misbot.config.ENV_FILE", tmp_path / "absent.env")


class TestFromEnv:
    def test_missing_token_explains_how_to_fix(self):
        with pytest.raises(ConfigError, match="BotFather"):
            Config.from_env()

    def test_blank_token_is_also_missing(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VAR, "   ")
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_reads_the_token(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VAR, "123:abc")
        assert Config.from_env().token == "123:abc"

    def test_broken_city_falls_back_to_tbilisi(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VAR, "123:abc")
        monkeypatch.setenv(CITY_VAR, "Тбилиси")
        assert Config.from_env().default_city == 1

    def test_the_default_city_is_not_the_whole_country(self, monkeypatch):
        # 0 — «вся Грузия», а по ней сайт ничего не отдаёт.
        monkeypatch.setenv(TOKEN_VAR, "123:abc")
        assert Config.from_env().default_city == 1

    def test_reads_the_admin_id(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VAR, "123:abc")
        monkeypatch.setenv(ADMIN_VAR, "42")
        assert Config.from_env().admin_id == 42

    def test_without_an_admin_id_stats_are_off(self, monkeypatch):
        # 0 — команда /stats молчит для всех.
        monkeypatch.setenv(TOKEN_VAR, "123:abc")
        assert Config.from_env().admin_id == 0

    def test_broken_admin_id_turns_stats_off(self, monkeypatch):
        monkeypatch.setenv(TOKEN_VAR, "123:abc")
        monkeypatch.setenv(ADMIN_VAR, "@masha")
        assert Config.from_env().admin_id == 0


class TestEnvFile:
    def test_reads_key_values_and_skips_comments(self, monkeypatch, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# комментарий\n"
            f"{TOKEN_VAR}=123:abc\n"
            "\n"
            f'{CONTACT_VAR}="https://t.me/bot"\n',
            encoding="utf-8",
        )
        load_env_file(env)

        monkeypatch.setattr("misbot.config.ENV_FILE", env)
        config = Config.from_env()
        assert config.token == "123:abc"
        assert config.contact == "https://t.me/bot"

    def test_real_environment_wins_over_the_file(self, monkeypatch, tmp_path):
        env = tmp_path / ".env"
        env.write_text(f"{TOKEN_VAR}=из-файла\n", encoding="utf-8")
        monkeypatch.setenv(TOKEN_VAR, "из-окружения")
        load_env_file(env)

        assert Config.from_env().token == "из-окружения"

    def test_absent_file_is_not_an_error(self, tmp_path):
        load_env_file(tmp_path / "нет-такого.env")
