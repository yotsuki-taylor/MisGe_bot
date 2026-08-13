"""Проверка склейки: настоящий Dispatcher, поддельная сессия телеграма.

Остальные тесты дёргают хендлеры напрямую и поэтому не видят, доезжают ли до них
client, cities и config. Здесь апдейт проходит через настоящий диспетчер целиком.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, List

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User

from misbot.alerts import Alerter
from misbot.bot import build_dispatcher
from misbot.config import Config
from misbot.locations import FALLBACK_CITIES, CityDirectory
from misbot.user_store import UserStore

from test_bot import FakeClient  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_TOKEN = "123456789:AAHkQwertyuiopasdfghjklzxcvbnm12345"

USER = User(id=42, is_bot=False, first_name="Маша")
CHAT = Chat(id=42, type="private")


class FakeSession(BaseSession):
    """Ничего не отправляет, только записывает, что бот попытался сделать."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: List[TelegramMethod] = []
        self._message_id = 0

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout=None) -> Any:
        self.requests.append(method)

        if isinstance(method, (SendMessage, EditMessageText)):
            self._message_id += 1
            # as_(bot) обязателен: иначе у ответа не будет привязки к боту
            # и хендлер не сможет позвать edit_text.
            return Message(
                message_id=self._message_id,
                date=datetime.now(),
                chat=CHAT,
                from_user=USER,
                text=method.text,
            ).as_(bot)
        if isinstance(method, AnswerCallbackQuery):
            return True
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        pass

    @property
    def texts(self) -> List[str]:
        return [r.text for r in self.requests if isinstance(r, (SendMessage, EditMessageText))]


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(session) -> Bot:
    return Bot(
        token=FAKE_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def dispatcher() -> Dispatcher:
    return build_dispatcher()


def message_update(text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(),
            chat=CHAT,
            from_user=USER,
            text=text,
        ),
    )


class TestWiring:
    async def test_dependencies_reach_the_handler(self, bot, dispatcher, session):
        client = FakeClient()
        await dispatcher.feed_update(
            bot,
            message_update("нурофен"),
            client=client,
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN, default_city=1),
        )

        assert client.searches == ["nurofen"], "запрос не доехал до клиента mis.ge"
        assert any("Нашлось" in text for text in session.texts)

    async def test_start_answers(self, bot, dispatcher, session):
        await dispatcher.feed_update(
            bot,
            message_update("/start"),
            client=FakeClient(),
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN),
        )
        assert any("ищу лекарства" in text for text in session.texts)

    async def test_about_uses_the_configured_contact(self, bot, dispatcher, session):
        await dispatcher.feed_update(
            bot,
            message_update("/about"),
            client=FakeClient(),
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN, contact="https://t.me/proverka"),
        )
        assert any("proverka" in text for text in session.texts)

    async def test_city_command_offers_a_keyboard(self, bot, dispatcher, session):
        await dispatcher.feed_update(
            bot,
            message_update("/city"),
            client=FakeClient(),
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN, default_city=1),
        )
        sends = [r for r in session.requests if isinstance(r, SendMessage)]
        assert sends[-1].reply_markup is not None

    async def test_user_store_reaches_the_handler(self, bot, dispatcher, session, tmp_path):
        # Хендлеры вызываются в тестах напрямую, и там подмена всегда доезжает.
        # Здесь проверяется именно проводка aiogram: имя параметра совпало с
        # ключом в start_polling.
        async with UserStore(tmp_path / "wiring.sqlite3") as users:
            await users.set_city(USER.id, 5)
            await dispatcher.feed_update(
                bot,
                message_update("/city"),
                client=FakeClient(),
                cities=CityDirectory(dict(FALLBACK_CITIES)),
                config=Config(token=FAKE_TOKEN, default_city=1),
                users=users,
            )

        assert any("Батуми" in text for text in session.texts), "город взят не из базы"

    async def test_alerter_reaches_the_handler(self, bot, dispatcher, session):
        broken = FakeClient(search_html="<html><body>всё поменялось</body></html>")
        alerts = Alerter(bot, chat_id=777)

        await dispatcher.feed_update(
            bot,
            message_update("нурофен"),
            client=broken,
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN, default_city=1),
            alerts=alerts,
        )

        sent = [r for r in session.requests if isinstance(r, SendMessage)]
        assert any(r.chat_id == 777 for r in sent), "админу о поломке не написали"
        assert any("Не разобрался в ответе" in (r.text or "") for r in sent)

    async def test_id_command_reports_the_chat(self, bot, dispatcher, session):
        await dispatcher.feed_update(
            bot,
            message_update("/id"),
            client=FakeClient(),
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN),
        )
        assert any(str(CHAT.id) in text for text in session.texts)

    async def test_html_parse_mode_is_on(self, bot, dispatcher, session):
        await dispatcher.feed_update(
            bot,
            message_update("/help"),
            client=FakeClient(),
            cities=CityDirectory(dict(FALLBACK_CITIES)),
            config=Config(token=FAKE_TOKEN),
        )
        # Разметка должна уехать как HTML, иначе пользователь увидит теги.
        assert bot.default.parse_mode == ParseMode.HTML
        assert any("<b>" in text for text in session.texts)
