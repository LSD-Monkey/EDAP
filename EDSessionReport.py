from __future__ import annotations

"""
Session report from the Elite Dangerous journals: what happened while the bot was running, so that changes can be
measured (interdictions, drops at planets/stars, deaths, docking denials, phases without progress, profit).

Written to the log when Waypoint Assist stops. Command line:
    python EDSessionReport.py            # last 12 hours
    python EDSessionReport.py 4          # last 4 hours
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime


def _ts(ev: dict) -> float | None:
    try:
        return datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp()
    except Exception:
        return None


def _local(t: float) -> str:
    return datetime.fromtimestamp(t).strftime('%H:%M')


def load_events(journal_dir: str, start: float, end: float | None = None) -> list[dict]:
    end = end or time.time() + 60
    try:
        files = sorted((os.path.join(journal_dir, f) for f in os.listdir(journal_dir)
                        if f.startswith('Journal.') and f.endswith('.log')), key=os.path.getmtime)
    except Exception:
        return []
    out = []
    for fn in files:
        try:
            if os.path.getmtime(fn) < start:
                continue
            with open(fn, encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    t = _ts(ev)
                    if t is not None and start <= t <= end:
                        ev['_t'] = t
                        out.append(ev)
        except Exception:
            continue
    out.sort(key=lambda e: e['_t'])
    return out


def build_report(events: list[dict], start: float, end: float | None = None) -> list[str]:
    end = end or time.time()
    c = Counter(e['event'] for e in events)
    lines = [f"Session report {_local(start)} - {_local(end)} ({(end - start) / 3600:.1f} h)"]

    # Trade
    profit = sales = 0
    for e in events:
        if e['event'] == 'MarketSell':
            sales += 1
            paid = int(e.get('AvgPricePaid') or 0) * int(e.get('Count') or 0)
            profit += (int(e.get('TotalSale') or 0) - paid) if paid else 0
    hours = max(0.05, (end - start) / 3600)
    lines.append(f"  Trade: {sales} sales, profit {profit / 1e6:.1f} M cr ({profit / 1e6 / hours:.1f} M cr/h), "
                 f"{c['FSDJump']} jumps, {c['Docked']} dockings")

    # Interdictions
    ints = [e for e in events if e['event'] == 'Interdicted']
    if ints:
        by = Counter(e.get('Interdictor_Localised') or e.get('Interdictor') or '?' for e in ints)
        worst, n = by.most_common(1)[0]
        lines.append(f"  Interdictions: {len(ints)} ({sum(1 for e in ints if e.get('Submitted'))} submitted), "
                     f"most by '{worst}': {n}x" + (f", escaped {c['EscapeInterdiction']}x" if c['EscapeInterdiction']
                                                   else ""))
    else:
        lines.append("  Interdictions: none")

    # Drops out of supercruise not at the destination and not by an interdiction
    int_minutes = {e['timestamp'][:16] for e in ints}
    drops = Counter()
    for i, e in enumerate(events):
        if e['event'] != 'SupercruiseExit' or e['timestamp'][:16] in int_minutes:
            continue
        prev = events[max(0, i - 3):i]
        if any(p['event'] == 'SupercruiseDestinationDrop' for p in prev):
            continue
        if e.get('BodyType') in ('Planet', 'Star', 'PlanetaryRing', 'StellarRing', 'Null'):
            drops[e.get('BodyType')] += 1
    lines.append("  Unplanned drops: " + (", ".join(f"{k} {v}" for k, v in drops.items()) if drops else "none"))

    # Damage, deaths
    hull = [float(e.get('Health', 1)) for e in events if e['event'] == 'HullDamage' and not e.get('Fighter')]
    deaths = [e for e in events if e['event'] == 'Died']
    rebuys = [e for e in events if e['event'] == 'Resurrect']
    lines.append(f"  Damage: lowest hull {min(hull) * 100:.0f}%" if hull else "  Damage: none")
    if deaths:
        lines.append(f"  Ship destroyed {len(deaths)}x: " + ", ".join(
            f"{_local(e['_t'])} {e.get('KillerName_Localised') or e.get('KillerShip') or '?'}" for e in deaths) +
            "; respawn " + ", ".join(f"{r.get('Option')} {int(r.get('Cost') or 0) / 1e6:.1f} M" for r in rebuys))
    if c['HeatDamage']:
        lines.append(f"  Heat damage: {c['HeatDamage']}x")

    # Docking
    dd = Counter(e.get('Reason') for e in events if e['event'] == 'DockingDenied')
    if dd:
        lines.append("  Docking denied: " + ", ".join(f"{k} {v}" for k, v in dd.items()))

    # Phases without progress (no jump, docking or trade for > 15 min)
    progress = [e['_t'] for e in events if e['event'] in ('FSDJump', 'Docked', 'MarketSell', 'MarketBuy',
                                                        'SupercruiseDestinationDrop')]
    marks = [start] + progress + [end]
    gaps = [(a, b) for a, b in zip(marks, marks[1:]) if b - a > 900]
    if gaps:
        lines.append("  No progress for > 15 min: " + ", ".join(
            f"{_local(a)}-{_local(b)} ({(b - a) / 60:.0f} min)" for a, b in gaps))
    return lines


def session_report(journal_dir: str, start: float, end: float | None = None) -> list[str]:
    return build_report(load_events(journal_dir, start, end), start, end)


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    if sys.platform == 'win32':
        from WindowsKnownPaths import get_path, FOLDERID, UserHandle
        jd = get_path(FOLDERID.SavedGames, UserHandle.current) + "/Frontier Developments/Elite Dangerous"
    else:
        jd = sys.argv[2] if len(sys.argv) > 2 else "./linux_ed"
    start = time.time() - hours * 3600
    print("\n".join(session_report(jd, start)))


if __name__ == '__main__':
    main()
