from __future__ import annotations

"""
Trade route finder (Trade tab).

Finds round trips A -> B -> A from a start station A: buy at A, sell at B, buy at B, sell at A. Market data comes from
 - the local Market.json if we are docked at A (exact, current prices),
 - the Ardent Insight API (https://api.ardent-insight.com, EDDN market data) for everything else.

Search:
 1. Market of A: exports (we can buy, stock > 0) and imports (we can sell).
 2. For each export of A: the best nearby importers ('nearby/imports', within the max. distance).
 3. The best stations B (outbound profit) get their market loaded: best return commodity B -> A.
 4. Every round trip gets a profit per trip and an estimated profit per hour (jumps, supercruise, docking).

The result can be written as a waypoint file (A, B, REPEAT) for Waypoint Assist.
"""

import json
import math
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from EDlogger import logger

ARDENT_BASE = "https://api.ardent-insight.com/v2"
USER_AGENT = "EDAP-TradeFinder/1.0 (github.com/LSD-Monkey/EDAP)"

# Station types that can not be used: carriers, megaships, construction sites, points of interest
EXCLUDED_TYPES = {'fleetcarrier', 'megaship', 'gameplaypoi', 'planetaryconstructiondepot',
                  'spaceconstructiondepot', 'colonisationship', 'strongholdcarrier'}
# Station types on a planet surface (glide + planetary landing)
PLANETARY_TYPES = {'crateroutpost', 'craterport', 'onfootsettlement', 'surfacestation', 'planetaryoutpost',
                   'planetaryport', 'surfaceport'}
# Station types that always have large pads
LARGE_PAD_TYPES = {'coriolis', 'orbis', 'ocellus', 'asteroidbase', 'bernal', 'dodec', 'craterport'}

# Commodity symbols (Ardent/EDDN, Market.json 'Name') whose display name is not the symbol with spaces
SYMBOL_NAMES = {
    'agriculturalmedicines': 'Agri-Medicines', 'heliostaticfurnaces': 'Microbial Furnaces',
    'hazardousenvironmentsuits': 'H.E. Suits', 'terrainenrichmentsystems': 'Land Enrichment Systems',
    'skimercomponents': 'Skimmer Components', 'marinesupplies': 'Marine Equipment',
    'lowtemperaturediamond': 'Low Temperature Diamonds', 'atmosphericextractors': 'Atmospheric Processors',
    'coolinghoses': 'Micro-Weave Cooling Hoses', 'diagnosticsensor': 'Hardware Diagnostic Sensor',
    'mutomimager': 'Muon Imager', 'powergridassembly': 'Energy Grid Assembly', 'platinumaloy': 'Platinum Alloy',
    'opal': 'Void Opals', 'basicnarcotics': 'Narcotics', 'drones': 'Limpet', 'comercialsamples': 'Commercial Samples',
    'usscargoblackbox': 'Black Box', 'hafnium178': 'Hafnium 178', 'metaalloys': 'Meta-Alloys',
    'nonlethalweapons': 'Non-Lethal Weapons', 'cmmcomposite': 'CMM Composite', 'hnshockmount': 'HN Shock Mount',
    'autofabricators': 'Auto-Fabricators', 'fruitandvegetables': 'Fruit and Vegetables',
}


def _norm(txt: str) -> str:
    return ''.join(ch for ch in (txt or '').lower() if ch.isalnum())


def _symbol_from_market_name(name: str) -> str:
    """ '$rutile_name;' -> 'rutile' """
    n = (name or '').lower()
    if n.startswith('$') and n.endswith('_name;'):
        n = n[1:-6]
    return _norm(n)


_DISPLAY_CACHE: dict[str, str] | None = None


def display_name(symbol: str, local_names: dict[str, str] | None = None) -> str:
    """ English display name of a commodity symbol (as shown in the market and used in waypoint files). """
    global _DISPLAY_CACHE
    sym = _norm(symbol)
    if local_names and sym in local_names:
        return local_names[sym]
    if sym in SYMBOL_NAMES:
        return SYMBOL_NAMES[sym]
    if _DISPLAY_CACHE is None:
        _DISPLAY_CACHE = {}
        try:
            from EDAP_data import sorted_commodities
            for n in sorted_commodities():
                _DISPLAY_CACHE[_norm(n)] = n
        except Exception:
            pass
    return _DISPLAY_CACHE.get(sym, symbol.title())


def pad_size(value, station_type: str = '') -> int | None:
    """ Landing pad size as 1 (S), 2 (M), 3 (L) or None if unknown. """
    if isinstance(value, (int, float)) and value:
        return int(value)
    if isinstance(value, str) and value:
        v = value.strip().upper()[:1]
        return {'S': 1, 'M': 2, 'L': 3}.get(v)
    t = _norm(station_type)
    if t in LARGE_PAD_TYPES:
        return 3
    if t == 'outpost':
        return 2
    return None


def age_hours(updated_at) -> float | None:
    if not updated_at:
        return None
    try:
        if isinstance(updated_at, (int, float)):
            ts = float(updated_at)
        else:
            ts = datetime.fromisoformat(str(updated_at).replace('Z', '+00:00')).timestamp()
        return max(0.0, (time.time() - ts) / 3600.0)
    except Exception:
        return None


class ArdentClient:
    """ Minimal client of the Ardent Insight REST API with a small cache. """

    def __init__(self, timeout: float = 20.0, cache_secs: float = 600.0):
        self.timeout = timeout
        self.cache_secs = cache_secs
        self._cache: dict[str, tuple[float, object]] = {}
        self.requests = 0

    def get(self, path: str, params: dict | None = None):
        url = ARDENT_BASE + path
        if params:
            url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        hit = self._cache.get(url)
        if hit and time.time() - hit[0] < self.cache_secs:
            return hit[1]
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
        last_err = None
        for attempt in range(3):
            try:
                self.requests += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                self._cache[url] = (time.time(), data)
                return data
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    self._cache[url] = (time.time(), None)
                    return None
                last_err = e
            except Exception as e:
                last_err = e
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Ardent API request failed: {url} ({last_err})")

    @staticmethod
    def q(name: str) -> str:
        return urllib.parse.quote(name, safe='')

    def station_market(self, system: str, station: str):
        return self.get(f"/system/name/{self.q(system)}/market/name/{self.q(station)}/commodities")

    def nearby_imports(self, system: str, symbol: str, max_distance: int, min_volume: int, max_days: int):
        return self.get(f"/system/name/{self.q(system)}/commodity/name/{self.q(symbol)}/nearby/imports",
                        {'maxDistance': int(max_distance), 'minVolume': int(min_volume), 'fleetCarriers': 'false',
                         'maxDaysAgo': max(1, int(math.ceil(max_days)))})

    def system(self, system: str):
        return self.get(f"/system/name/{self.q(system)}")


class TradeFinder:
    def __init__(self, client: ArdentClient | None = None, progress=None):
        self.client = client or ArdentClient()
        self.progress = progress or (lambda msg: None)

    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def market_from_local(market_json: dict) -> dict:
        """ Market.json -> {symbol: {...}} """
        out = {}
        for it in market_json.get('Items', []):
            sym = _symbol_from_market_name(it.get('Name', ''))
            if not sym:
                continue
            out[sym] = {
                'name': it.get('Name_Localised') or display_name(sym),
                'buy': int(it.get('BuyPrice', 0) or 0), 'sell': int(it.get('SellPrice', 0) or 0),
                'stock': int(it.get('Stock', 0) or 0), 'demand': int(it.get('Demand', 0) or 0),
                'can_buy': (it.get('Stock', 0) or 0) > 0 and (it.get('Producer', True) or it.get('Rare', False))
                           and not it.get('Rare', False),
                'can_sell': bool(it.get('Consumer') or (it.get('Demand', 0) or 0) > 0),
                'updated': market_json.get('timestamp'),
            }
        return out

    @staticmethod
    def market_from_ardent(rows: list) -> dict:
        out = {}
        for r in rows or []:
            sym = _norm(r.get('commodityName', ''))
            if not sym:
                continue
            stock = int(r.get('stock') or 0)
            demand = int(r.get('demand') or 0)
            buy = int(r.get('buyPrice') or 0)
            sell = int(r.get('sellPrice') or 0)
            out[sym] = {'name': display_name(sym), 'buy': buy, 'sell': sell, 'stock': stock, 'demand': demand,
                        'can_buy': stock > 0 and buy > 0,
                        'can_sell': sell > 0 and (demand > 0 or (r.get('demandBracket') or 0) > 0),
                        'updated': r.get('updatedAt')}
        return out

    @staticmethod
    def station_reject_reason(row: dict, min_pad: int, max_arrival_ls: float, include_planetary: bool) -> str:
        """ '' if the station can be used, else the reason. """
        stype = _norm(row.get('stationType') or '')
        name = (row.get('stationName') or '')
        if stype in EXCLUDED_TYPES or 'colonisation' in name.lower() or 'construction site' in name.lower():
            return 'carrier/megaship/construction'
        if stype in PLANETARY_TYPES and not include_planetary:
            return 'planetary'
        pad = pad_size(row.get('maxLandingPadSize'), stype)
        if pad is None:
            return 'pad size unknown'
        if pad < min_pad:
            return 'pad too small'
        dta = row.get('distanceToArrival')
        if dta is not None and max_arrival_ls and float(dta) > max_arrival_ls:
            return 'too far from the star'
        return ''

    @classmethod
    def station_ok(cls, row: dict, min_pad: int, max_arrival_ls: float, include_planetary: bool) -> bool:
        return cls.station_reject_reason(row, min_pad, max_arrival_ls, include_planetary) == ''

    @staticmethod
    def estimate_trip_secs(distance_ly: float, jump_range: float, arrival_a: float, arrival_b: float,
                           secs_per_jump: float = 110.0, secs_station: float = 240.0) -> tuple[int, float]:
        """ Jumps per way and the estimated time of a round trip in seconds (measured in the logs: ~110 s per jump
        with alignment and star avoidance, ~4 min per station for approach, docking, trade and undocking, a
        supercruise of 76 Ls took ~2 min). """
        # The plotted route is not a straight line (2026-10-20: 93 ly direct, 8 jumps of max. 13.5 ly)
        jumps = max(1, int(math.ceil(distance_ly * 1.12 / max(1.0, jump_range))))

        def sc(ls):
            return 60.0 + 8.0 * math.sqrt(max(0.0, float(ls or 0)))

        total = 2 * jumps * secs_per_jump + sc(arrival_a) + sc(arrival_b) + 2 * secs_station
        return jumps, total

    # ------------------------------------------------------------------------------------------------------------
    def find_round_trips(self, start_system: str, start_station: str, cargo: int, min_pad: int = 3,
                         max_distance: float = 60, max_arrival_ls: float = 5000, max_age_hours: float = 24,
                         include_planetary: bool = False, jump_range: float = 15.0, local_market: dict | None = None,
                         max_exports: int = 20, max_destinations: int = 15, secs_per_jump: float = 110.0) -> list[dict]:
        cargo = max(1, int(cargo))
        max_days = max(1.0, max_age_hours / 24.0)

        # 1. Market of the start station
        if local_market is not None:
            mkt_a = self.market_from_local(local_market)
            self.progress(f"Start market from Market.json ({len(mkt_a)} commodities).")
        else:
            self.progress(f"Loading the market of {start_station}...")
            rows = self.client.station_market(start_system, start_station)
            if not rows:
                raise RuntimeError(f"No market data for '{start_station}' in '{start_system}' (Ardent).")
            mkt_a = self.market_from_ardent(rows)
        arrival_a = 0.0
        sys_a = None
        try:
            rows = self.client.station_market(start_system, start_station) if local_market is not None else rows
            if rows:
                arrival_a = float(rows[0].get('distanceToArrival') or 0)
                sys_a = (rows[0].get('systemX'), rows[0].get('systemY'), rows[0].get('systemZ'))
        except Exception as e:
            logger.debug(f"trade finder: start station details: {e}")

        local_names = {sym: v['name'] for sym, v in mkt_a.items()}
        exports = [(sym, v) for sym, v in mkt_a.items() if v['can_buy'] and v['buy'] > 0]
        # Most promising first: big stock, cheap compared to the price elsewhere is unknown here -> stock
        exports.sort(key=lambda kv: kv[1]['stock'], reverse=True)
        exports = exports[:max_exports]
        if not exports:
            raise RuntimeError(f"'{start_station}' sells nothing (no stock).")
        self.progress(f"{len(exports)} commodities to buy at {start_station}. Searching buyers within "
                      f"{max_distance:g} ly...")

        # 2. Best buyers for every export
        def buyers(item):
            sym, v = item
            try:
                rows = self.client.nearby_imports(start_system, sym, max_distance, min(cargo, 1000), max_days) or []
            except Exception as e:
                logger.warning(f"trade finder: imports of {sym}: {e}")
                return sym, v, []
            return sym, v, rows

        candidates: dict[str, dict] = {}  # key system|station -> best outbound
        rejected: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for done, (sym, v, rows) in enumerate(pool.map(buyers, exports), 1):
                for r in rows:
                    reason = self.station_reject_reason(r, min_pad, max_arrival_ls, include_planetary)
                    if reason:
                        rejected[reason] = rejected.get(reason, 0) + 1
                        continue
                    age = age_hours(r.get('updatedAt'))
                    if age is not None and age > max_age_hours:
                        continue
                    profit = int(r.get('sellPrice') or 0) - v['buy']
                    if profit <= 0:
                        continue
                    demand = int(r.get('demand') or 0)
                    amount = min(cargo, v['stock'], demand if demand > 0 else cargo)
                    if amount <= 0:
                        continue
                    key = f"{r.get('systemName')}|{r.get('stationName')}"
                    total = profit * amount
                    if key not in candidates or total > candidates[key]['out_total']:
                        candidates[key] = {
                            'system': r.get('systemName'), 'station': r.get('stationName'),
                            'station_type': r.get('stationType'), 'arrival_ls': float(r.get('distanceToArrival') or 0),
                            'pad': pad_size(r.get('maxLandingPadSize'), r.get('stationType') or ''),
                            'distance': float(r.get('distance') or 0),
                            'out_symbol': sym, 'out_name': v['name'], 'out_buy': v['buy'],
                            'out_sell': int(r.get('sellPrice') or 0), 'out_profit': profit, 'out_amount': amount,
                            'out_total': total, 'out_age_h': age,
                        }
                self.progress(f"Buyers searched: {done}/{len(exports)} commodities, {len(candidates)} stations.")

        if rejected:
            logger.info("Trade finder: stations skipped: " + ", ".join(f"{k} {v}" for k, v in rejected.items()))
        if not candidates:
            self.progress("No buyer found. Skipped: " + ", ".join(f"{k} {v}" for k, v in rejected.items()))
            return []

        # 3. Return trip for the best destinations
        best = sorted(candidates.values(), key=lambda c: c['out_total'], reverse=True)[:max_destinations]
        self.progress(f"Loading the markets of the best {len(best)} destinations for the return trip...")

        def return_trip(c):
            try:
                rows = self.client.station_market(c['system'], c['station']) or []
            except Exception as e:
                logger.warning(f"trade finder: market of {c['station']}: {e}")
                rows = []
            return c, self.market_from_ardent(rows)

        routes = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for c, mkt_b in pool.map(return_trip, best):
                back = None
                for sym, vb in mkt_b.items():
                    va = mkt_a.get(sym)
                    if not vb['can_buy'] or not va or not va['can_sell']:
                        continue
                    age = age_hours(vb.get('updated'))
                    if age is not None and age > max_age_hours:
                        continue
                    profit = va['sell'] - vb['buy']
                    if profit <= 0:
                        continue
                    amount = min(cargo, vb['stock'], va['demand'] if va['demand'] > 0 else cargo)
                    if amount <= 0:
                        continue
                    if back is None or profit * amount > back['back_total']:
                        back = {'back_symbol': sym, 'back_name': display_name(sym, local_names),
                                'back_buy': vb['buy'], 'back_sell': va['sell'], 'back_profit': profit,
                                'back_amount': amount, 'back_total': profit * amount, 'back_age_h': age}
                route = dict(c)
                route.update(back or {'back_symbol': None, 'back_name': '', 'back_buy': 0, 'back_sell': 0,
                                      'back_profit': 0, 'back_amount': 0, 'back_total': 0, 'back_age_h': None})
                jumps, secs = self.estimate_trip_secs(c['distance'], jump_range, arrival_a, c['arrival_ls'],
                                                      secs_per_jump=secs_per_jump)
                route['jumps'] = jumps
                route['trip_secs'] = secs
                route['profit_trip'] = route['out_total'] + route['back_total']
                route['profit_hour'] = route['profit_trip'] * 3600.0 / secs
                route['start_system'] = start_system
                route['start_station'] = start_station
                route['capital_needed'] = max(route['out_buy'] * route['out_amount'],
                                              route['back_buy'] * route['back_amount'])
                routes.append(route)
        self.progress(f"{len(routes)} round trips found ({self.client.requests} requests).")
        return routes


# ----------------------------------------------------------------------------------------------------------------
def waypoint_entry(system: str, station: str, sell: dict, buy: dict) -> dict:
    return {
        "SystemName": system, "StationName": station,
        "GalaxyBookmarkType": "", "GalaxyBookmarkNumber": 0,
        "SystemBookmarkType": "", "SystemBookmarkNumber": 0,
        "SellCommodities": sell, "BuyCommodities": buy,
        "Comment": None, "UpdateCommodityCount": False, "FleetCarrierTransfer": False,
        "Skip": False, "Completed": False,
    }


def route_to_waypoints(route: dict) -> dict:
    """ Waypoint file content for the round trip: A (sell return commodity, buy outbound), B (sell outbound, buy
    return commodity), REPEAT. """
    out_name = route['out_name']
    back_name = route.get('back_name') or ''
    wp = {"GlobalShoppingList": dict(waypoint_entry("", "", {}, {}), Skip=True)}
    wp["1"] = waypoint_entry(route['start_system'], route['start_station'],
                             {back_name: 9999} if back_name else {}, {out_name: 9999})
    wp["2"] = waypoint_entry(route['system'], route['station'], {out_name: 9999},
                             {back_name: 9999} if back_name else {})
    wp["3"] = waypoint_entry("REPEAT", "", {}, {})
    return wp
