"""Тексты бота. Всё, что видит пользователь, собирается здесь.

Разметка — HTML телеграма. Названия приходят с чужого сайта, поэтому любой текст
оттуда обязательно проходит через html.escape.
"""

from __future__ import annotations

from html import escape
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .forms import translate_company, translate_country, translate_medicine
from .landmarks import translate_landmark
from .models import Medicine, Pharmacy, Stock
from .stats import Period
from .translit import ka_to_latin, ka_to_ru

SOURCE_URL = "http://www.mis.ge"
SOURCE_LINE = f'Источник: <a href="{SOURCE_URL}">mis.ge</a>'
DISCLAIMER = (
    "Бот показывает цены и наличие. Он не назначает лечение и не заменяет врача."
)

MEDICINES_PER_PAGE = 8
STOCKS_SHOWN = 8
"""Меньше десяти: с адресом и часами работы каждая аптека занимает четыре строки."""


def greeting() -> str:
    return (
        "Привет! Я ищу лекарства по аптекам Грузии.\n\n"
        "Напишите название препарата — по-русски, латиницей или по-грузински, "
        "например <code>нурофен</code>. Я покажу, в каких аптеках он есть "
        "и сколько стоит.\n\n"
        f"Город можно выбрать командой /city.\n\n<i>{DISCLAIMER}</i>"
    )


def help_text() -> str:
    return (
        "<b>Как пользоваться</b>\n\n"
        "Просто напишите название препарата: <code>нурофен</code>, "
        "<code>diclofenac</code>, <code>ნუროფენი</code>.\n\n"
        "Из списка выберите нужную форму выпуска — покажу аптеки с ценами.\n\n"
        "Под списком аптек есть кнопка «Следить»: я буду проверять препарат "
        "раз в сутки и напишу, когда он появится или подешевеет.\n\n"
        "<b>Команды</b>\n"
        "/city — выбрать город\n"
        "/watching — за чем слежу\n"
        "/about — откуда данные\n\n"
        f"<i>{DISCLAIMER}</i>"
    )


def about_text(contact: str) -> str:
    return (
        "Данные о наличии и ценах бот берёт с сайта "
        f'<a href="{SOURCE_URL}">mis.ge</a> — это открытый справочник аптек Грузии. '
        "Бот их не хранит и не перепродаёт, а только показывает.\n\n"
        "<b>Важно про даты.</b> Аптеки обновляют остатки сами и делают это "
        "по-разному: у части данные свежие, у части им больше года. "
        "Дату обновления я показываю у каждой строки — смотрите на неё "
        "и лучше позвоните в аптеку перед поездкой.\n\n"
        "<b>Приватность.</b> Тексты запросов не сохраняются. Бот считает обезличенную "
        "статистику — сколько было запросов и сколько из них нашлось; кто именно "
        "спрашивал, из неё не видно: telegram id не хранится, вместо него хеш. "
        "Учтите, что сайт-источник "
        "работает без шифрования, так что название препарата уходит к нему "
        "открытым текстом.\n\n"
        f"Связь: {escape(contact)}\n\n"
        f"<i>{DISCLAIMER}</i>"
    )


def stats_text(periods: Sequence[Period]) -> str:
    """Счётчики для владельца бота. Команда /stats, в /help её нет."""
    lines = ["<b>Статистика</b>", ""]
    for period in periods:
        lines.append(f"<b>{escape(period.label)}</b>")
        lines.append(f"    запросов: {period.searches}")
        if period.hit_rate is not None:
            lines.append(
                f"    нашлось: {period.found} ({period.hit_rate:.0%}), "
                f"пусто: {period.nothing}"
            )
        lines.append(f"    смотрели аптеки: {period.stocks}")
        lines.append(f"    людей: {period.people}")
        lines.append("")

    lines.append(
        "<i>Считаются только события. Ни текстов запросов, ни telegram id "
        "в базе нет — пользователи различаются по хешу с солью.</i>"
    )
    return "\n".join(lines)


def searching(query: str) -> str:
    return f"Ищу «{escape(query)}»…"


def nothing_found(query: str) -> str:
    return (
        f"По запросу «{escape(query)}» ничего не нашлось.\n\n"
        "Попробуйте написать иначе — например, действующее вещество "
        "вместо торгового названия (<code>ибупрофен</code> вместо "
        "<code>нурофен</code>) или первые несколько букв."
    )


def too_short() -> str:
    return "Слишком короткий запрос — нужно хотя бы три буквы."


def site_unavailable() -> str:
    return (
        "Сайт-источник сейчас не отвечает. Это бывает — попробуйте через "
        "несколько минут."
    )


def parser_broken() -> str:
    return (
        "Не смог разобрать ответ сайта: похоже, там что-то поменяли. "
        "Я уже знаю о проблеме, скоро починим."
    )


def busy() -> str:
    return "Ещё ищу предыдущий запрос, секунду…"


def medicines_page(
    medicines: Sequence[Medicine],
    offset: int,
    city_name: str,
    title: str = "",
) -> Tuple[str, List[Tuple[str, str]]]:
    """Страница выдачи: текст сообщения и подписи кнопок с хешами препаратов."""
    page = medicines[offset:offset + MEDICINES_PER_PAGE]

    headline = title or f"Нашлось: <b>{len(medicines)}</b>."
    lines = [f"{headline} Показываю город: <b>{escape(city_name)}</b>.", ""]
    buttons: List[Tuple[str, str]] = []

    for number, medicine in enumerate(page, start=offset + 1):
        name = escape(translate_medicine(medicine.name))
        lines.append(f"<b>{number}.</b> {name}")

        details = [
            translate_company(medicine.company),
            translate_country(medicine.country),
        ]
        detail_line = " · ".join(escape(d) for d in details if d)
        if detail_line:
            lines.append(f"    <i>{detail_line}</i>")
        if _needs_prescription(medicine):
            lines.append("    <i>по рецепту</i>")

        buttons.append((str(number), medicine.hash))

    lines.append("")
    lines.append("Выберите номер — покажу аптеки.")
    return "\n".join(lines), buttons


def shown_stocks(stocks: Sequence[Stock], limit: int = STOCKS_SHOWN) -> List[Stock]:
    """Что попадёт в сообщение: сначала дешёвые, без повторов по партиям.

    Отдельная функция, потому что по этому же списку решается, чьи адреса вообще
    нужно добывать, — и им же пользуется консольный прототип.
    """
    unique = _dedupe(stocks)
    priced = sorted((s for s in unique if s.price is not None), key=lambda s: s.price)
    unpriced = [s for s in unique if s.price is None]
    return (priced + unpriced)[:limit]


def stocks_message(
    stocks: Sequence[Stock],
    city_name: str,
    pharmacies: Optional[Dict[int, Pharmacy]] = None,
) -> str:
    """Аптеки, где препарат есть. Адреса подставляются, если карточки уже добыты."""
    pharmacies = pharmacies or {}
    unique = _dedupe(stocks)
    shown = shown_stocks(stocks)

    if not shown:
        return (
            f"В городе <b>{escape(city_name)}</b> этого препарата сейчас нет.\n\n"
            "Попробуйте выбрать другой город командой /city."
        )

    name = escape(translate_medicine(shown[0].medicine_name))
    lines = [f"<b>{name}</b>", ""]

    for stock in shown:
        lines.append(_stock_line(stock, pharmacies.get(stock.pharmacy_id)))
        lines.append("")

    if len(unique) > len(shown):
        lines.append(f"<i>…и ещё {len(unique) - len(shown)} аптек — показываю самые дешёвые.</i>")
        lines.append("")

    lines.append(f"<i>{DISCLAIMER}</i>")
    lines.append(SOURCE_LINE)
    return "\n".join(lines)


def _stock_line(stock: Stock, pharmacy: Optional[Pharmacy] = None) -> str:
    price = f"<b>{stock.price} ₾</b>" if stock.price is not None else "<i>цена не указана</i>"
    clock = " · круглосуточно" if stock.round_the_clock else ""
    updated = (
        f"обновлено {stock.updated.isoformat()}" if stock.updated else "дата обновления неизвестна"
    )
    stale = " ⚠️" if stock.is_stale else ""

    signboard = pharmacy.display_name if pharmacy and pharmacy.display_name else ""
    name = escape(pharmacy_label(signboard or stock.pharmacy_name))

    lines = [f"{price} — {name}{clock}", _where_line(stock, pharmacy)]

    schedule = _schedule_line(pharmacy)
    if schedule:
        lines.append(schedule)

    lines.append(f"<i>{updated}{stale}</i>")
    return "\n".join(lines)


def pharmacy_label(name: str, romanise: Callable[[str], str] = ka_to_latin) -> str:
    """Название аптеки: сначала латиницей, следом в скобках — как на вывеске.

    Латиница нужна, чтобы название можно было прочесть и произнести вслух;
    оригинал — чтобы сличить с тем, что написано на самой аптеке. Если название
    и так латиницей («PSP»), скобки не нужны — они повторили бы то же самое.

    Возвращает обычный текст: экранирование — забота вызывающего.
    """
    name = (name or "").strip()
    if not name:
        return ""
    romanised = romanise(name).strip()
    if not romanised or romanised.casefold() == name.casefold():
        return name
    return f"{romanised} ({name})"


def _where_line(stock: Stock, pharmacy: Optional[Pharmacy]) -> str:
    """Адрес, если он известен, иначе город и район из строки остатка."""
    if pharmacy is None or not pharmacy.address:
        where = " / ".join(
            escape(ka_to_ru(part))
            for part in (stock.city, stock.district, stock.subdistrict)
            if part and part.strip()
        )
        return f"📍 {where}" if where else ""

    # Улица как на сайте: её сличают с табличкой на доме и показывают водителю.
    street = escape(strip_area(pharmacy.address, stock))
    district = escape(ka_to_ru(stock.district)) if stock.district.strip() else ""
    address = f"{street}, {district}" if district else street

    if pharmacy.map_url:
        address = f'<a href="{escape(pharmacy.map_url, quote=True)}">{address}</a>'
    if pharmacy.landmark:
        # Перевод — чтобы понять, куда идти. Оригинал под ним — чтобы показать
        # прохожему или таксисту.
        translated = translate_landmark(pharmacy.landmark)
        if translated:
            address += f"\n{escape(translated)}"
        address += f"\n<i>{escape(pharmacy.landmark)}</i>"
    return f"📍 {address}"


def _schedule_line(pharmacy: Optional[Pharmacy]) -> str:
    if pharmacy is None:
        return ""
    parts = []
    if pharmacy.hours:
        parts.append(escape(ka_to_ru(pharmacy.hours)))
    if pharmacy.phone:
        parts.append(f"☎ {escape(pharmacy.phone)}")
    return " · ".join(parts)


def strip_area(address: str, stock: Stock) -> str:
    """Убрать из адреса город и район — они и так видны в строке остатка.

    Сайт склеивает адрес как «Тбилиси Сабуртало M мед. институт ул. такая-то 6»,
    и без обрезки половина строки уходит на уже сказанное.
    """
    remainder = address.strip()
    for part in (stock.city, stock.district, stock.subdistrict):
        part = part.strip()
        if part and remainder.startswith(part):
            remainder = remainder[len(part):].strip()
    return remainder or address.strip()


def city_chosen(city_name: str) -> str:
    return f"Город: <b>{escape(city_name)}</b>. Напишите название препарата."


def analogues_title(generic: str, total: int) -> str:
    return (
        f"🧬 Аналоги: то же действующее вещество, <b>{escape(generic)}</b>. "
        f"Нашлось: <b>{total}</b>."
    )


def no_analogues() -> str:
    return "Других препаратов с тем же действующим веществом не нашлось."


def analogues_unavailable() -> str:
    return "Не смог получить список аналогов. Попробуйте ещё раз чуть позже."


def watch_added(medicine_name: str, city_name: str) -> str:
    return (
        f"Слежу за <b>{escape(translate_medicine(medicine_name))}</b> "
        f"в городе <b>{escape(city_name)}</b>.\n\n"
        "Проверяю раз в сутки и напишу, когда препарат появится или подешевеет. "
        "Список подписок — /watching."
    )


def watch_removed() -> str:
    return "Больше не слежу. Список подписок — /watching."


def watch_limit(limit: int) -> str:
    return (
        f"Уже слежу за {limit} препаратами — это предел. "
        "Отпишитесь от ненужного через /watching, и можно будет добавить новый."
    )


def watch_list(watches, city_name) -> str:
    """Список подписок. city_name — функция, переводящая id города в название."""
    if not watches:
        return (
            "Пока ни за чем не слежу.\n\n"
            "Найдите препарат, откройте аптеки и нажмите «Следить» — "
            "я буду проверять раз в сутки и напишу, когда он появится или подешевеет."
        )

    lines = ["<b>Слежу за препаратами</b>", ""]
    for number, watch in enumerate(watches, start=1):
        name = escape(translate_medicine(watch.name)) if watch.name else "препарат"
        state = (
            f"есть, от {watch.best_price} ₾"
            if watch.available and watch.best_price is not None
            else "есть" if watch.available
            else "нет в наличии"
        )
        lines.append(f"<b>{number}.</b> {name}")
        lines.append(f"    {escape(city_name(watch.city))} · {state}")
    lines.append("")
    lines.append("Чтобы перестать следить, нажмите номер.")
    return "\n".join(lines)


def watch_news(watch, reason: str, stocks, city_name: str) -> str:
    """Уведомление о том, что препарат появился или подешевел."""
    shown = shown_stocks(stocks, limit=3)
    name = escape(translate_medicine(watch.name or (shown[0].medicine_name if shown else "")))

    # Заголовок отдельной строкой: названия препаратов длинные и кончаются
    # на «16 шт.», к которому «появился» прилипает нечитаемо.
    if reason == "cheaper":
        headline = "💰 <b>Подешевел</b>"
        prices = [s.price for s in shown if s.price is not None]
        if watch.best_price is not None and prices:
            headline += f": было от {watch.best_price} ₾, стало от {min(prices)} ₾"
    else:
        headline = "🔔 <b>Появился в продаже</b>"

    lines = [headline, "", name, f"Город: {escape(city_name)}", ""]
    for stock in shown:
        price = f"<b>{stock.price} ₾</b>" if stock.price is not None else "цена не указана"
        lines.append(f"{price} — {escape(pharmacy_label(stock.pharmacy_name))}")
    lines.append("")
    lines.append("Отписаться или посмотреть список — /watching.")
    lines.append(f"<i>{DISCLAIMER}</i>")
    lines.append(SOURCE_LINE)
    return "\n".join(lines)


def chat_id(value: int) -> str:
    return (
        f"Ваш telegram id: <code>{value}</code>\n\n"
        "Положите его в <code>MISGE_ADMIN_ID</code>, чтобы получать /stats "
        "и сообщения о поломке разбора."
    )


def choose_city(current_name: str) -> str:
    return f"Сейчас ищу в: <b>{escape(current_name)}</b>.\n\nВыберите город:"


def _dedupe(stocks: Iterable[Stock]) -> List[Stock]:
    """Одна аптека часто отдаёт несколько строк на разные партии одной цены."""
    seen: Dict[tuple, Stock] = {}
    for stock in stocks:
        key = (stock.pharmacy_id, stock.pharmacy_name, stock.price, stock.medicine_name)
        seen.setdefault(key, stock)
    return list(seen.values())


def _needs_prescription(medicine: Medicine) -> bool:
    # «გაიცემა რეცეპტის გარეშე» — «отпускается без рецепта».
    dispensing = medicine.dispensing
    return bool(dispensing) and "რეცეპტის გარეშე" not in dispensing
