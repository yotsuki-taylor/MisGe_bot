"""Живая проверка транслитерации: русские названия против настоящего mis.ge.

Не тест — тесты не ходят в сеть. Это инструмент, чтобы померить долю попаданий
и увидеть, на каких буквах подбор написания промахивается.

    python tools/check_translit.py
    python tools/check_translit.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from misbot.mis_client import MisClient  # noqa: E402
from misbot.search import find_medicines  # noqa: E402
from misbot.translit import ka_to_ru  # noqa: E402

NAMES = [
    "нурофен", "ибупрофен", "парацетамол", "аспирин", "цитрамон",
    "диклофенак", "кетонал", "нимесил", "анальгин", "спазмалгон",
    "амоксиклав", "азитромицин", "цефтриаксон", "цефазолин", "гентамицин",
    "ципрофлоксацин", "метронидазол", "флуконазол", "ацикловир", "супрастин",
    "лоратадин", "цетиризин", "омепразол", "пантопразол", "мезим",
    "эналаприл", "лизиноприл", "амлодипин", "бисопролол", "метопролол",
    "аторвастатин", "метформин", "инсулин", "гепарин", "варфарин",
    "дексаметазон", "преднизолон", "фуросемид", "магнезия", "но-шпа",
    "дротаверин", "лидокаин", "хлоргексидин", "морфин", "трамадол",
    # Особые правила из brands.py: побуквенный подбор на них промахивается.
    "зиртек",
    # Грузинские запросы: сайт грузинский, но ищет по латинскому написанию.
    "ნუროფენი", "იბუპროფენი", "ასპირინი", "ცეტირიზინი", "დიკლოფენაკი",
    "პარაცეტამოლი", "ომეპრაზოლი", "ამოქსიცილინი", "ზირტეკი",
]


async def main(verbose: bool) -> int:
    stats = Counter()
    misses = []

    async with MisClient() as client:
        for name in NAMES:
            outcome = await find_medicines(client, name)
            stats["всего"] += 1
            if outcome.found:
                stats[outcome.strategy] += 1
                if verbose:
                    first = ka_to_ru(outcome.medicines[0].name)
                    print(f"  ✓ {name:<16} → {outcome.query:<18} "
                          f"{outcome.strategy:<9} n={len(outcome.medicines):<4} {first[:60]}")
            else:
                stats["мимо"] += 1
                misses.append((name, outcome.tried))
                if verbose:
                    print(f"  ✗ {name:<16} пробовали: {', '.join(outcome.tried)}")

    total = stats["всего"]
    hits = total - stats["мимо"]
    print(f"\nнайдено {hits} из {total} ({hits / total:.0%})")
    for strategy in ("as-is", "brand", "translit", "prefix", "inn"):
        if stats[strategy]:
            print(f"  {strategy:<9} {stats[strategy]}")

    if misses:
        print("\nне нашлись:")
        for name, tried in misses:
            print(f"  {name:<16} {', '.join(tried)}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args().verbose)))
