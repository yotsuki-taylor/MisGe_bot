"""Консольный прототип: поиск препарата и его наличия без телеграма.

    python -m misbot.cli nurofen
    python -m misbot.cli nurofen --pick 1 --city 1
    python -m misbot.cli --locations

Нужен, чтобы проверять слои mis_client + parser отдельно от бота и снимать
свежие фикстуры (--save-html) при поломке разбора.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

from .cache import PharmacyCache
from .config import DEFAULT_DB
from .formatting import shown_stocks, strip_area
from .forms import (
    translate_company,
    translate_country,
    translate_dispensing,
    translate_generic,
    translate_medicine,
)
from .landmarks import translate_landmark
from .mis_client import MisClient, MisUnavailable
from .models import Medicine, Stock
from .pharmacies import resolve
from .parser import ParseError, QueryTooShort, parse_locations, parse_pharmacies
from .search import find_medicines
from .translit import ka_to_ru


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="misbot.cli",
        description="Поиск лекарств по аптекам Грузии (данные mis.ge)",
    )
    parser.add_argument("query", nargs="?", help="название препарата по-русски, латиницей или грузиницей")
    parser.add_argument("--pick", help="номера препаратов из выдачи через запятую, напр. 1,3")
    parser.add_argument("--city", type=int, default=0, help="id города, 0 = везде (1 = Тбилиси)")
    parser.add_argument("--district", type=int, default=0, help="id района, 0 = везде")
    parser.add_argument("--subdistrict", type=int, default=0, help="id микрорайона, 0 = везде")
    parser.add_argument("--limit", type=int, default=20, help="сколько строк печатать")
    parser.add_argument("--georgian", action="store_true", help="не переводить вывод в кириллицу")
    parser.add_argument("--no-addresses", action="store_true", help="не добывать адреса аптек")
    parser.add_argument("--locations", action="store_true", help="напечатать справочники городов и районов")
    parser.add_argument("--save-html", type=Path, help="куда сложить сырой HTML ответов")
    return parser


async def run(args: argparse.Namespace) -> int:
    async with MisClient() as client:
        if args.locations:
            html = await client.search("nurofen")
            _dump(args.save_html, "locations.html", html)
            show = (lambda text: text) if args.georgian else ka_to_ru
            locations = parse_locations(html)
            _print_locations("ГОРОДА", locations.cities, show)
            _print_locations("РАЙОНЫ (Тбилиси)", locations.districts, show)
            _print_locations("МИКРОРАЙОНЫ", locations.subdistricts, show)
            return 0

        if not args.query:
            print("нужен запрос: python -m misbot.cli нурофен", file=sys.stderr)
            return 2

        show = (lambda text: text) if args.georgian else ka_to_ru

        outcome = await find_medicines(client, args.query)
        if not outcome.found:
            print(f"ничего не найдено, пробовали: {', '.join(outcome.tried)}")
            return 1

        _dump(args.save_html, "search.html", outcome.html)
        if outcome.query != args.query:
            print(f"запрос ушёл на сайт как «{outcome.query}» ({outcome.strategy})\n")
        medicines = outcome.medicines

        _print_medicines(medicines, args.limit, show)

        picked = _pick(medicines, args.pick)
        if not picked:
            print("\nчтобы посмотреть аптеки: добавьте --pick 1 (номер из первой колонки)")
            return 0

        html = await client.pharmacies(
            [m.hash for m in picked],
            city=args.city,
            district=args.district,
            subdistrict=args.subdistrict,
        )
        _dump(args.save_html, "pharmacies.html", html)
        stocks = parse_pharmacies(html)

        if not stocks:
            print("\nв выбранной локации этого препарата нет")
            return 0

        cards = {}
        if not args.no_addresses:
            shown = shown_stocks(stocks, args.limit)
            async with PharmacyCache(DEFAULT_DB) as cache:
                cards = await resolve(
                    client, cache,
                    [s.pharmacy_id for s in shown],
                    max_fetches=args.limit,
                )

        _print_stocks(stocks, args.limit, show, cards)
        return 0


def _pick(medicines: List[Medicine], raw: Optional[str]) -> List[Medicine]:
    if not raw:
        return []
    picked = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk.isdigit():
            continue
        index = int(chunk) - 1
        if 0 <= index < len(medicines):
            picked.append(medicines[index])
    return picked


def _print_medicines(medicines: List[Medicine], limit: int, show) -> None:
    print(f"НАЙДЕНО ПРЕПАРАТОВ: {len(medicines)}\n")
    for number, medicine in enumerate(medicines[:limit], start=1):
        print(f"{number:>3}. {translate_medicine(medicine.name)}")
        print(f"     МНН: {translate_generic(medicine.generic) or '—'} | "
              f"{translate_country(medicine.country) or '—'} | "
              f"{translate_company(medicine.company) or '—'}")
        if medicine.dispensing:
            print(f"     отпуск: {translate_dispensing(medicine.dispensing)}")
    if len(medicines) > limit:
        print(f"\n… ещё {len(medicines) - limit}, показать больше: --limit")


def _print_stocks(stocks: List[Stock], limit: int, show, cards=None) -> None:
    cards = cards or {}

    print(f"\nАПТЕК С ЭТИМ ПРЕПАРАТОМ: {len(stocks)}\n")
    for stock in shown_stocks(stocks, limit):
        price = f"{stock.price} ₾" if stock.price is not None else "цена не указана"
        clock = " (24ч)" if stock.round_the_clock else ""
        where = " / ".join(
            show(p) for p in (stock.city, stock.district, stock.subdistrict) if p
        )
        updated = stock.updated.isoformat() if stock.updated else "дата неизвестна"
        stale = "  ⚠ давно не обновляли" if stock.is_stale else ""
        card = cards.get(stock.pharmacy_id)
        # Вывеску и ориентир не транслитерируем: их сличают с тем, что написано
        # на улице, и показывают прохожим.
        name = card.display_name if card and card.display_name else show(stock.pharmacy_name)

        print(f"{price:>18}  {name}{clock}")
        if card and card.address:
            street = strip_area(card.address, stock)
            print(f"{'':>18}  {street}, {where}")
            if card.landmark:
                translated = translate_landmark(card.landmark)
                if translated:
                    print(f"{'':>18}  ориентир: {translated}")
                print(f"{'':>18}  {'':>10}{card.landmark}")
            schedule = " · ".join(p for p in (show(card.hours), card.phone) if p)
            if schedule:
                print(f"{'':>18}  {schedule}")
        else:
            print(f"{'':>18}  {where}")
        print(f"{'':>18}  обновлено: {updated}{stale}")
        print(f"{'':>18}  {translate_medicine(stock.medicine_name)}")
        print()

    print("источник данных: http://www.mis.ge")
    print("бот показывает цены и наличие и не даёт медицинских советов")


def _print_locations(title: str, items, show) -> None:
    print(f"\n{title} ({len(items)})")
    for item in items:
        print(f"  {item.id:>4}  {show(item.name)}")


def _dump(directory: Optional[Path], name: str, html: str) -> None:
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(html, encoding="utf-8")


def main() -> int:
    # Грузиница в консоли Windows иначе превращается в вопросительные знаки.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args()
    try:
        return asyncio.run(run(args))
    except MisUnavailable as exc:
        print(f"mis.ge недоступен: {exc}", file=sys.stderr)
        return 3
    except QueryTooShort as exc:
        print(f"слишком короткий запрос: {exc}", file=sys.stderr)
        return 2
    except ParseError as exc:
        print(f"парсер сломался (вёрстка сайта изменилась?): {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
