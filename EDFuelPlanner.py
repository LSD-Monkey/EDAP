from __future__ import annotations

"""
Fuel check for a plotted route (ships without fuel scoop).

The fuel used per jump is learned from the FSDJump events (JumpDist, FuelUsed) in the recent journal files of the
same ship with a similar cargo load. The FSD fuel use follows fuel = k * dist^p, k and p are fitted from these jumps.
The jump distances of the plotted route are calculated from NavRoute.json (StarPos).
"""

import json
import math
import os
from os import listdir
from os.path import join, isfile, getmtime

from EDlogger import logger


def _read_journal_events(path: str):
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"fuel planner: cannot read {path}: {e}")


def collect_jump_samples(journal_dir: str, max_files: int = 40) -> tuple[list[dict], int | None]:
    """ Reads the last journal files and returns ([{'ship_id', 'dist', 'fuel', 'cargo'}], current ship id). """
    try:
        files = [join(journal_dir, f) for f in listdir(journal_dir)
                 if f.startswith('Journal.') and f.endswith('.log') and isfile(join(journal_dir, f))]
    except Exception as e:
        logger.debug(f"fuel planner: cannot list {journal_dir}: {e}")
        return [], None
    files.sort(key=getmtime)
    files = files[-max_files:]

    samples = []
    ship_id = None
    cargo = 0
    for path in files:
        for ev in _read_journal_events(path):
            e = ev.get('event')
            if e in ('Loadout', 'LoadGame') and 'ShipID' in ev:
                ship_id = ev['ShipID']
            elif e == 'ShipyardSwap' and 'ShipID' in ev:
                ship_id = ev['ShipID']
            elif e == 'Cargo' and ev.get('Vessel', 'Ship') == 'Ship' and 'Count' in ev:
                cargo = int(ev['Count'])
            elif e == 'MarketBuy':
                cargo += int(ev.get('Count', 0))
            elif e == 'MarketSell':
                cargo = max(0, cargo - int(ev.get('Count', 0)))
            elif e == 'FSDJump':
                dist = ev.get('JumpDist')
                fuel = ev.get('FuelUsed')
                if dist and fuel and dist > 0.5 and fuel > 0:
                    samples.append({'ship_id': ship_id, 'dist': float(dist), 'fuel': float(fuel), 'cargo': cargo})
    return samples, ship_id


def route_jump_distances(nav_route_data: dict | None, cur_system: str | None = None) -> list[float]:
    """ Jump distances (ly) of the plotted route. The first entry of the route is the system where the route was
    plotted. If cur_system is somewhere in the route (e.g. restart in the middle of the route), only the jumps from
    there on are returned. """
    if not nav_route_data or nav_route_data.get('event') == 'NavRouteClear':
        return []
    route = nav_route_data.get('Route') or []
    if cur_system:
        names = [str(r.get('StarSystem', '')).upper() for r in route]
        if cur_system.upper() in names:
            route = route[names.index(cur_system.upper()):]
    dists = []
    for a, b in zip(route, route[1:]):
        pa, pb = a.get('StarPos'), b.get('StarPos')
        if not pa or not pb:
            continue
        dists.append(math.dist(pa, pb))
    return dists


def fit_fuel_model(samples: list[dict]) -> tuple[float, float, float] | None:
    """ Fits fuel = k * dist^p. Returns (k_median, k_90, p) or None. k_90: 90 % of the jumps used less. """
    if len(samples) < 3:
        return None
    xs = [math.log(s['dist']) for s in samples]
    ys = [math.log(s['fuel']) for s in samples]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    p = 2.45  # typical FSD power constant
    if sxx > 0.02:  # enough spread in the jump distances to fit the exponent
        p = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    p = min(2.8, max(2.0, p))
    ks = sorted(s['fuel'] / (s['dist'] ** p) for s in samples)
    k90 = ks[min(len(ks) - 1, int(math.ceil(0.9 * len(ks))) - 1)]
    kmed = ks[len(ks) // 2]
    return kmed, k90, p


def estimate_route_fuel(journal_dir: str, nav_route_data: dict | None, cur_cargo: int,
                        cargo_capacity: int | None, cur_system: str | None = None) -> dict | None:
    """ Estimates the fuel needed for the plotted route.
    Returns {'need': t (expected), 'need_max': t (conservative), 'jumps': n, 'samples': n, 'p': p}
    or None if not enough data. """
    dists = route_jump_distances(nav_route_data, cur_system)
    if not dists:
        return None
    samples, ship_id = collect_jump_samples(journal_dir)
    if ship_id is not None:
        samples = [s for s in samples if s['ship_id'] == ship_id]
    # Similar load only: an empty ship uses much less fuel than a full one
    tol = max(50, int(0.2 * cargo_capacity)) if cargo_capacity else 100
    similar = [s for s in samples if abs(s['cargo'] - cur_cargo) <= tol]
    if len(similar) < 3:
        # Not enough jumps with this load. Jumps with more cargo are a safe (high) estimate.
        similar = [s for s in samples if s['cargo'] >= cur_cargo - tol]
    model = fit_fuel_model(similar[-60:])
    if model is None:
        return None
    kmed, k90, p = model
    need = sum(kmed * d ** p for d in dists)
    need_max = sum(k90 * d ** p for d in dists) * 1.05  # 5 % safety margin
    return {'need': need, 'need_max': need_max, 'jumps': len(dists), 'samples': len(similar), 'p': p}
