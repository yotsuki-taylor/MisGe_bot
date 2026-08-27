"""Тексты бота. Всё, что видит пользователь, собирается здесь.

Слова живут в [[i18n]], здесь — сборка: что за чем идёт, что выделено жирным,
где перенос строки. Каждая функция принимает язык; по умолчанию русский, чтобы
консольный прототип и тесты не тащили его через все вызовы.

Разметка — HTML телеграма. Названия приходят с чужого сайта, поэтому любой текст
оттуда обязательно проходит через html.escape.

**Контент против интерфейса.** Интерфейс переводится словарём, а названия
препаратов, аптек и адреса приходят с mis.ge и переводятся правилами (forms.py,
translit.py, landmarks.py) — у каждого свой языковой слой. Для грузинского
интерфейса эти правила выключены: сайт грузинский, и показать оригинал
правильнее, чем транслитерировать его для того, кто читает по-грузински
свободнее нас.
"""

from __future__ import annotations

from html import escape
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import i18n
from .forms import translate_company, translate_country, translate_medicine
from .landmarks import translate_landmark
from .models import Medicine, Pharmacy, Stock
from .stats import Period
from .translit import ka_to_english, ka_to_latin, ka_to_ru

SOURCE_URL = "http://www.mis.ge"

MEDICINES_PER_PAGE = 8
STOCKS_SHOWN = 8
"""Меньше десяти: с адресом и часами работы каждая аптека занимает четыре строки."""


def disclaimer(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("disclaimer", lang)


def source_line(lang: str = i18n.DEFAULT) -> str:
    return f'{i18n.text("source", lang)}: <a href="{SOURCE_URL}">mis.ge</a>'


DISCLAIMER = disclaimer()
SOURCE_LINE = source_line()


# --- контент с сайта -------------------------------------------------------

def _medicine_name(name: str, lang: str) -> str:
    """Название препарата: переведённое или как на сайте."""
    return translate_medicine(name, lang)


def _from_site(text: str, lang: str) -> str:
    """Грузинская строка с сайта — город, район, часы работы."""
    if lang == i18n.KA:
        return text
    return ka_to_english(text) if lang == i18n.EN else ka_to_ru(text)


def _pharmacy_name(name: str, lang: str) -> str:
    """Вывеска аптеки. Грузинскому читателю латиница рядом с ней не нужна."""
    if lang == i18n.KA:
        return name
    if lang == i18n.EN:
        # «აფთიაქი 217» — это не вывеска, а номер: по-английски он читается
        # как «Pharmacy 217», а не «Aptiaqi 217».
        return pharmacy_label(name, ka_to_english)
    return pharmacy_label(name)


# --- команды ---------------------------------------------------------------

def choose_language() -> str:
    """Экран выбора языка. Кнопки называют языки на них самих."""
    return i18n.text("choose_language", i18n.DEFAULT)


def language_chosen(lang: str) -> str:
    return i18n.text("language_chosen", lang)


def greeting(lang: str = i18n.DEFAULT) -> str:
    return f"{i18n.text('greeting', lang)}\n\n<i>{disclaimer(lang)}</i>"


def help_text(lang: str = i18n.DEFAULT) -> str:
    return f"{i18n.text('help', lang)}\n\n<i>{disclaimer(lang)}</i>"


def about_text(contact: str, lang: str = i18n.DEFAULT) -> str:
    body = i18n.text("about", lang).format(
        source_url=SOURCE_URL, contact=escape(contact)
    )
    return f"{body}\n\n<i>{disclaimer(lang)}</i>"


def stats_text(periods: Sequence[Period]) -> str:
    """Счётчики для владельца бота. Не переводятся: читает их один человек."""
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


def searching(query: str, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("searching", lang).format(query=escape(query))


def nothing_found(query: str, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("nothing_found", lang).format(query=escape(query))


def nothing_everywhere(lang: str = i18n.DEFAULT) -> str:
    """Пустой ответ на поиск «по всей Грузии».

    Сайт на такой запрос отдаёт ноль аптек даже для препаратов, которые в
    аптеках есть, — поэтому говорить «нигде нет» было бы неправдой.
    """
    return i18n.text("nothing_everywhere", lang)


def too_short(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("too_short", lang)


def site_unavailable(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("site_unavailable", lang)


def site_blocked(lang: str = i18n.DEFAULT) -> str:
    """Сайт отвечает, но отказом: пересиживать нечего, обещать «скоро» честнее."""
    return i18n.text("site_blocked", lang)


def parser_broken(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("parser_broken", lang)


def busy(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("busy", lang)


def city_unknown(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("city_unknown", lang)


def pharmacies_count(count: int, lang: str = i18n.DEFAULT) -> str:
    """«в 1 аптеке», «в 2 аптеках», «в 21 аптеке» — и «нет в наличии» на ноль.

    Форм две, потому что этого требует русский; в грузинском числительное
    существительное не меняет, и обе строки словаря там совпадают.
    """
    if count <= 0:
        return i18n.text("out_of_stock", lang)
    single = count % 10 == 1 and count % 100 != 11
    key = "in_stock_one" if single else "in_stock_many"
    return i18n.text(key, lang).format(count=count)


def medicines_page(
    medicines: Sequence[Medicine],
    offset: int,
    city_name: str,
    title: str = "",
    counts: Optional[Dict[str, int]] = None,
    lang: str = i18n.DEFAULT,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Страница выдачи: текст сообщения и подписи кнопок с хешами препаратов."""
    page = medicines[offset:offset + MEDICINES_PER_PAGE]

    headline = title or i18n.text("found_total", lang).format(total=len(medicines))
    showing = i18n.text("showing_city", lang).format(city=escape(city_name))
    lines = [f"{headline} {showing}", ""]
    buttons: List[Tuple[str, str]] = []

    for number, medicine in enumerate(page, start=offset + 1):
        name = escape(_medicine_name(medicine.name, lang))
        lines.append(f"<b>{number}.</b> {name}")

        details = _medicine_details(medicine, lang)
        if _needs_prescription(medicine):
            details.append(i18n.text("prescription", lang))
        detail_line = " · ".join(escape(d) for d in details if d)
        if detail_line:
            lines.append(f"    <i>{detail_line}</i>")

        if counts is not None and medicine.hash in counts:
            lines.append(f"    {pharmacies_count(counts[medicine.hash], lang)}")

        buttons.append((str(number), medicine.hash))

    lines.append("")
    lines.append(i18n.text("pick_number", lang))
    return "\n".join(lines), buttons


def _medicine_details(medicine: Medicine, lang: str) -> List[str]:
    """Производитель и страна: для грузинского — как на сайте."""
    return [
        translate_company(medicine.company, lang),
        translate_country(medicine.country, lang),
    ]


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
    lang: str = i18n.DEFAULT,
) -> str:
    """Аптеки, где препарат есть. Адреса подставляются, если карточки уже добыты."""
    pharmacies = pharmacies or {}
    unique = _dedupe(stocks)
    shown = shown_stocks(stocks)

    if not shown:
        return i18n.text("no_stock_in_city", lang).format(city=escape(city_name))

    name = escape(_medicine_name(shown[0].medicine_name, lang))
    lines = [f"<b>{name}</b>", ""]

    for stock in shown:
        lines.append(_stock_line(stock, pharmacies.get(stock.pharmacy_id), lang))
        lines.append("")

    if len(unique) > len(shown):
        more = i18n.text("more_pharmacies", lang).format(count=len(unique) - len(shown))
        lines.append(f"<i>{more}</i>")
        lines.append("")

    lines.append(f"<i>{disclaimer(lang)}</i>")
    lines.append(source_line(lang))
    return "\n".join(lines)


def _stock_line(
    stock: Stock,
    pharmacy: Optional[Pharmacy] = None,
    lang: str = i18n.DEFAULT,
) -> str:
    price = (
        f"<b>{stock.price} ₾</b>" if stock.price is not None
        else f"<i>{i18n.text('price_unknown', lang)}</i>"
    )
    clock = f" · {i18n.text('round_the_clock', lang)}" if stock.round_the_clock else ""
    updated = (
        i18n.text("updated", lang).format(date=stock.updated.isoformat())
        if stock.updated else i18n.text("updated_unknown", lang)
    )
    stale = " ⚠️" if stock.is_stale else ""

    signboard = pharmacy.display_name if pharmacy and pharmacy.display_name else ""
    name = escape(_pharmacy_name(signboard or stock.pharmacy_name, lang))

    lines = [f"{price} — {name}{clock}", _where_line(stock, pharmacy, lang)]

    schedule = _schedule_line(pharmacy, lang)
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


def _where_line(stock: Stock, pharmacy: Optional[Pharmacy], lang: str) -> str:
    """Адрес, если он известен, иначе город и район из строки остатка."""
    if pharmacy is None or not pharmacy.address:
        where = " / ".join(
            escape(_from_site(part, lang))
            for part in (stock.city, stock.district, stock.subdistrict)
            if part and part.strip()
        )
        return f"📍 {where}" if where else ""

    # Улица как на сайте: её сличают с табличкой на доме и показывают водителю.
    street = escape(strip_area(pharmacy.address, stock))
    district = escape(_from_site(stock.district, lang)) if stock.district.strip() else ""
    address = f"{street}, {district}" if district else street

    if pharmacy.map_url:
        address = f'<a href="{escape(pharmacy.map_url, quote=True)}">{address}</a>'
    if pharmacy.landmark:
        # Перевод — чтобы понять, куда идти. Оригинал под ним — чтобы показать
        # прохожему или таксисту. Для грузинского хватает одного оригинала.
        translated = "" if lang == i18n.KA else translate_landmark(pharmacy.landmark, lang)
        if translated:
            address += f"\n{escape(translated)}"
        address += f"\n<i>{escape(pharmacy.landmark)}</i>"
    return f"📍 {address}"


def _schedule_line(pharmacy: Optional[Pharmacy], lang: str = i18n.DEFAULT) -> str:
    if pharmacy is None:
        return ""
    parts = []
    if pharmacy.hours:
        parts.append(escape(_from_site(pharmacy.hours, lang)))
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


def city_chosen(city_name: str, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("city_chosen", lang).format(city=escape(city_name))


def choose_city(current_name: str, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("choose_city", lang).format(city=escape(current_name))


def analogues_title(generic: str, total: int, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("analogues_title", lang).format(
        generic=escape(generic), total=total
    )


def no_analogues(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("no_analogues", lang)


def analogues_unavailable(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("analogues_unavailable", lang)


UNNAMED_MEDICINE = i18n.text("unnamed_medicine", i18n.DEFAULT)
"""Название не добыли — лучше обтекаемо, чем дыра в предложении."""


def watch_added(medicine_name: str, city_name: str, lang: str = i18n.DEFAULT) -> str:
    name = (
        escape(_medicine_name(medicine_name, lang)) if medicine_name
        else i18n.text("unnamed_medicine", lang)
    )
    return i18n.text("watch_added", lang).format(name=name, city=escape(city_name))


def watch_removed(lang: str = i18n.DEFAULT) -> str:
    return i18n.text("watch_removed", lang)


def watch_limit(limit: int, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("watch_limit", lang).format(limit=limit)


def watch_list(watches, city_name, lang: str = i18n.DEFAULT) -> str:
    """Список подписок. city_name — функция, переводящая id города в название."""
    if not watches:
        return i18n.text("watch_list_empty", lang)

    lines = [i18n.text("watch_list_title", lang), ""]
    for number, watch in enumerate(watches, start=1):
        name = (
            escape(_medicine_name(watch.name, lang)) if watch.name
            else i18n.text("unnamed_medicine_short", lang)
        )
        if watch.available and watch.best_price is not None:
            state = i18n.text("watch_state_priced", lang).format(price=watch.best_price)
        elif watch.available:
            state = i18n.text("watch_state_available", lang)
        else:
            state = i18n.text("out_of_stock", lang)
        lines.append(f"<b>{number}.</b> {name}")
        lines.append(f"    {escape(city_name(watch.city))} · {state}")
    lines.append("")
    lines.append(i18n.text("watch_list_hint", lang))
    return "\n".join(lines)


def watch_news(
    watch,
    reason: str,
    stocks,
    city_name: str,
    lang: str = i18n.DEFAULT,
) -> str:
    """Уведомление о том, что препарат появился или подешевел."""
    shown = shown_stocks(stocks, limit=3)
    raw_name = watch.name or (shown[0].medicine_name if shown else "")
    name = escape(_medicine_name(raw_name, lang))

    # Заголовок отдельной строкой: названия препаратов длинные и кончаются
    # на «16 шт.», к которому «появился» прилипает нечитаемо.
    if reason == "cheaper":
        headline = i18n.text("watch_news_cheaper", lang)
        prices = [s.price for s in shown if s.price is not None]
        if watch.best_price is not None and prices:
            headline += i18n.text("watch_news_cheaper_prices", lang).format(
                old=watch.best_price, new=min(prices)
            )
    else:
        headline = i18n.text("watch_news_appeared", lang)

    lines = [
        headline, "", name,
        i18n.text("watch_news_city", lang).format(city=escape(city_name)), "",
    ]
    for stock in shown:
        price = (
            f"<b>{stock.price} ₾</b>" if stock.price is not None
            else i18n.text("price_unknown", lang)
        )
        lines.append(f"{price} — {escape(_pharmacy_name(stock.pharmacy_name, lang))}")
    lines.append("")
    lines.append(i18n.text("watch_news_hint", lang))
    lines.append(f"<i>{disclaimer(lang)}</i>")
    lines.append(source_line(lang))
    return "\n".join(lines)


def chat_id(value: int, lang: str = i18n.DEFAULT) -> str:
    return i18n.text("chat_id", lang).format(value=value)


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
