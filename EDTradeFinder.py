from __future__ import annotations

"""
Trade route finder (Trade tab), similar to the trade route search of Inara.

Searches the area around a reference system (usually where the ship is) for the most profitable trades:
 - one way: buy commodity X at station A, sell it at station B,
 - round trips: A -> B with X and B -> A with Y (repeated by Waypoint Assist).

Market data: Ardent Insight API (https://api.ardent-insight.com, EDDN data uploaded by players).
 1. Commodity report: the commodities worth checking (highest price level, not rare/salvage).
 2. For every commodity: sellers ('nearby/exports') and buyers ('nearby/imports') around the reference system.
 3. Every seller/buyer pair within the max. distance between the stations is a trade leg.
 4. Legs A->B and B->A are combined to round trips. Profit per trip and estimated profit per hour.
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

# Station types that can never be used (construction sites, points of interest)
EXCLUDED_TYPES = {'gameplaypoi', 'planetaryconstructiondepot', 'spaceconstructiondepot', 'colonisationship'}
CARRIER_TYPES = {'fleetcarrier', 'strongholdcarrier', 'squadroncarrier'}
MEGASHIP_TYPES = {'megaship'}
SETTLEMENT_TYPES = {'onfootsettlement'}
# Station types on a planet surface (glide + planetary landing)
PLANETARY_TYPES = {'crateroutpost', 'craterport', 'surfacestation', 'planetaryoutpost', 'planetaryport',
                   'surfaceport'}
# Commodity categories that are not traded (missions, salvage)
SKIP_SYMBOL_PARTS = ('thargoid', 'guardian', 'titan', 'mollusc', 'pod', 'escapepod', 'relic', 'artefact',
                     'blackbox', 'datacore', 'samples', 'drones', 'occupiedcryopod', 'hostage', 'prisoner')
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

    def __init__(self, timeout: float = 30.0, cache_secs: float = 600.0):
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

    def commodities(self):
        return self.get("/commodities")

    def system(self, system: str):
        return self.get(f"/system/name/{self.q(system)}")

    def nearby(self, kind: str, system: str, symbol: str, max_distance: float, min_volume: int, max_days: float,
               carriers: bool):
        """ kind 'exports' (where to buy) or 'imports' (where to sell). """
        return self.get(f"/system/name/{self.q(system)}/commodity/name/{self.q(symbol)}/nearby/{kind}",
                        {'maxDistance': int(min(500, max_distance)), 'minVolume': int(max(1, min_volume)),
                         'fleetCarriers': None if carriers else 'false',
                         'maxDaysAgo': max(1, int(math.ceil(max_days)))})


def estimate_trip_secs(distance_ly: float, jump_range: float, arrival_a: float, arrival_b: float,
                       round_trip: bool = True, secs_per_jump: float = 110.0,
                       secs_station: float = 240.0) -> tuple[int, float]:
    """ Jumps per way and the estimated time in seconds (one way or round trip). Measured in the EDAP logs:
    ~110 s per jump with alignment and star avoidance, ~4 min per station (approach, docking, trade, undocking),
    supercruise of 76 Ls ~2 min. """
    # The plotted route is not a straight line (2026-10-20: 93 ly direct, 8 jumps of max. 13.5 ly)
    jumps = max(1, int(math.ceil(distance_ly * 1.12 / max(1.0, jump_range))))

    def sc(ls):
        return 60.0 + 8.0 * math.sqrt(max(0.0, float(ls or 0)))

    if round_trip:
        total = 2 * jumps * secs_per_jump + sc(arrival_a) + sc(arrival_b) + 2 * secs_station
    else:
        total = jumps * secs_per_jump + sc(arrival_b) + 2 * secs_station
    return jumps, total


class TradeFinder:
    def __init__(self, client: ArdentClient | None = None, progress=None):
        self.client = client or ArdentClient()
        self.progress = progress or (lambda msg: None)
        self.rejected: dict[str, int] = {}

    # ------------------------------------------------------------------------------------------------------------
    def station_reject_reason(self, row: dict, f: dict) -> str:
        """ '' if the station can be used with the filters f, else the reason. """
        stype = _norm(row.get('stationType') or '')
        name = (row.get('stationName') or '').lower()
        if stype in EXCLUDED_TYPES or 'colonisation' in name or 'construction site' in name:
            return 'construction site'
        if stype in CARRIER_TYPES and not f['carriers']:
            return 'fleet carrier'
        if stype in MEGASHIP_TYPES and not f['megaships']:
            return 'megaship'
        if stype in SETTLEMENT_TYPES and not f['settlements']:
            return 'settlement'
        if stype in PLANETARY_TYPES and not f['planetary']:
            return 'planetary'
        pad = pad_size(row.get('maxLandingPadSize'), stype)
        if stype in CARRIER_TYPES and pad is None:
            pad = 3
        if pad is None:
            return 'pad size unknown' if f['min_pad'] > 1 else ''
        if pad < f['min_pad']:
            return 'pad too small'
        dta = row.get('distanceToArrival')
        if dta is not None and f['max_arrival_ls'] and float(dta) > f['max_arrival_ls']:
            return 'too far from the star'
        age = age_hours(row.get('updatedAt'))
        if age is not None and age > f['max_age_hours']:
            return 'price too old'
        return ''

    def _ok(self, row: dict, f: dict) -> bool:
        reason = self.station_reject_reason(row, f)
        if reason:
            self.rejected[reason] = self.rejected.get(reason, 0) + 1
            return False
        return True

    def commodity_list(self, count: int) -> list[str]:
        """ The commodities worth checking: highest average price level with supply and demand. """
        report = self.client.commodities() or []
        rows = []
        for c in report:
            sym = _norm(c.get('commodityName', ''))
            if not sym or any(p in sym for p in SKIP_SYMBOL_PARTS):
                continue
            if (c.get('totalStock') or 0) <= 0 or (c.get('totalDemand') or 0) <= 0:
                continue
            spread = (c.get('avgSellPrice') or 0) - (c.get('minBuyPrice') or 0)
            rows.append((max(spread, 0) + 0.2 * (c.get('avgSellPrice') or 0), sym))
        rows.sort(reverse=True)
        return [sym for _, sym in rows[:count]]

    @staticmethod
    def _key(row: dict) -> str:
        return str(row.get('marketId') or f"{row.get('systemName')}|{row.get('stationName')}")

    @staticmethod
    def _station(row: dict) -> dict:
        return {'system': row.get('systemName'), 'station': row.get('stationName'),
                'station_type': row.get('stationType'), 'arrival_ls': float(row.get('distanceToArrival') or 0),
                'pad': pad_size(row.get('maxLandingPadSize'), row.get('stationType') or ''),
                'dist_ref': float(row.get('distance') or 0),
                'pos': (row.get('systemX'), row.get('systemY'), row.get('systemZ'))}

    @staticmethod
    def _dist(a: dict, b: dict) -> float | None:
        pa, pb = a['pos'], b['pos']
        if None in pa or None in pb:
            return None
        return math.dist(pa, pb)

    # ------------------------------------------------------------------------------------------------------------
    def find_routes(self, ref_system: str, cargo: int, max_start_distance: float = 50, max_hop_distance: float = 50,
                    min_volume: int = 0, max_arrival_ls: float = 5000, max_age_hours: float = 24, min_pad: int = 3,
                    carriers: bool = False, megaships: bool = False, planetary: bool = False,
                    settlements: bool = False, round_trips: bool = True, commodity_count: int = 50,
                    jump_range: float = 15.0, secs_per_jump: float = 110.0, top_per_side: int = 60,
                    max_results: int = 100) -> list[dict]:
        cargo = max(1, int(cargo))
        min_volume = int(min_volume) if min_volume and min_volume > 0 else cargo
        f = dict(carriers=carriers, megaships=megaships, planetary=planetary, settlements=settlements,
                 min_pad=min_pad, max_arrival_ls=max_arrival_ls, max_age_hours=max_age_hours)
        self.rejected = {}
        # Stations of a round trip are both start stations, so both need to be within the start distance plus
        # the distance between the stations (the closer one becomes the start).
        radius = min(500.0, max_start_distance + max_hop_distance)
        max_days = max(1.0, max_age_hours / 24.0)

        self.progress("Loading the commodity list...")
        symbols = self.commodity_list(commodity_count)
        if not symbols:
            raise RuntimeError("Could not load the commodity list (Ardent API).")
        self.progress(f"Searching {len(symbols)} commodities within {radius:g} ly of {ref_system}...")

        def load(sym):
            try:
                ex = self.client.nearby('exports', ref_system, sym, radius, min_volume, max_days, carriers) or []
                im = self.client.nearby('imports', ref_system, sym, radius, min_volume, max_days, carriers) or []
            except Exception as e:
                logger.warning(f"trade finder: {sym}: {e}")
                return sym, [], []
            return sym, ex, im

        stations: dict[str, dict] = {}
        legs: dict[tuple[str, str], dict] = {}  # (seller, buyer) -> best leg
        done = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for sym, ex, im in pool.map(load, symbols):
                done += 1
                sellers = [r for r in ex if (r.get('buyPrice') or 0) > 0 and self._ok(r, f)]
                buyers = [r for r in im if (r.get('sellPrice') or 0) > 0 and self._ok(r, f)]
                sellers.sort(key=lambda r: r.get('buyPrice') or 0)
                buyers.sort(key=lambda r: r.get('sellPrice') or 0, reverse=True)
                sellers, buyers = sellers[:top_per_side], buyers[:top_per_side]
                name = display_name(sym)
                for s_row in sellers:
                    ks = self._key(s_row)
                    st_s = stations.setdefault(ks, self._station(s_row))
                    for b_row in buyers:
                        profit = int(b_row.get('sellPrice') or 0) - int(s_row.get('buyPrice') or 0)
                        if profit <= 0:
                            break  # buyers are sorted by price, the rest is worse
                        kb = self._key(b_row)
                        if kb == ks:
                            continue
                        st_b = stations.setdefault(kb, self._station(b_row))
                        d = self._dist(st_s, st_b)
                        if d is None or d > max_hop_distance:
                            continue
                        stock = int(s_row.get('stock') or 0)
                        demand = int(b_row.get('demand') or 0)
                        amount = min(cargo, stock if stock > 0 else cargo, demand if demand > 0 else cargo)
                        total = amount * profit
                        leg = legs.get((ks, kb))
                        if leg is None or total > leg['total']:
                            legs[(ks, kb)] = {
                                'symbol': sym, 'name': name, 'buy': int(s_row.get('buyPrice') or 0),
                                'sell': int(b_row.get('sellPrice') or 0), 'profit': profit, 'amount': amount,
                                'total': total, 'distance': d,
                                'age_h': max([a for a in (age_hours(s_row.get('updatedAt')),
                                                          age_hours(b_row.get('updatedAt'))) if a is not None],
                                             default=None),
                                'supply': stock, 'demand': demand,
                            }
                self.progress(f"Commodities checked: {done}/{len(symbols)}, {len(legs)} trades found.")

        if self.rejected:
            logger.info("Trade finder: stations skipped: " +
                        ", ".join(f"{k} {v}" for k, v in sorted(self.rejected.items())))

        routes = []
        if round_trips:
            seen = set()
            for (ka, kb), out in legs.items():
                back = legs.get((kb, ka))
                if back is None or (kb, ka) in seen:
                    continue
                seen.add((ka, kb))
                a, b = stations[ka], stations[kb]
                # Start at the station that is closer to the reference system
                if b['dist_ref'] < a['dist_ref']:
                    a, b, out, back = b, a, back, out
                if a['dist_ref'] > max_start_distance:
                    continue
                routes.append(self._route(a, b, out, back, jump_range, secs_per_jump))
        else:
            for (ka, kb), out in legs.items():
                a, b = stations[ka], stations[kb]
                if a['dist_ref'] > max_start_distance:
                    continue
                routes.append(self._route(a, b, out, None, jump_range, secs_per_jump))

        routes.sort(key=lambda r: r['profit_hour'], reverse=True)
        self.progress(f"{len(routes)} {'round trips' if round_trips else 'trades'} found "
                      f"({self.client.requests} requests).")
        return routes[:max_results]

    @staticmethod
    def _route(a: dict, b: dict, out: dict, back: dict | None, jump_range: float, secs_per_jump: float) -> dict:
        jumps, secs = estimate_trip_secs(out['distance'], jump_range, a['arrival_ls'], b['arrival_ls'],
                                         round_trip=back is not None, secs_per_jump=secs_per_jump)
        profit = out['total'] + (back['total'] if back else 0)
        ages = [x for x in (out.get('age_h'), back.get('age_h') if back else None) if x is not None]
        return {
            'start_system': a['system'], 'start_station': a['station'], 'start_type': a['station_type'],
            'start_arrival_ls': a['arrival_ls'], 'dist_to_start': a['dist_ref'],
            'system': b['system'], 'station': b['station'], 'station_type': b['station_type'],
            'arrival_ls': b['arrival_ls'], 'distance': out['distance'], 'jumps': jumps, 'trip_secs': secs,
            'out_name': out['name'], 'out_buy': out['buy'], 'out_sell': out['sell'], 'out_profit': out['profit'],
            'out_amount': out['amount'], 'out_total': out['total'], 'out_supply': out['supply'],
            'out_demand': out['demand'],
            'back_name': back['name'] if back else '', 'back_buy': back['buy'] if back else 0,
            'back_sell': back['sell'] if back else 0, 'back_profit': back['profit'] if back else 0,
            'back_amount': back['amount'] if back else 0, 'back_total': back['total'] if back else 0,
            'round_trip': back is not None,
            'profit_trip': profit, 'profit_hour': profit * 3600.0 / secs,
            'age_h': max(ages) if ages else None,
            'capital_needed': max(out['buy'] * out['amount'], (back['buy'] * back['amount']) if back else 0),
        }


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
    """ Waypoint file content. Round trip: A (sell return commodity, buy outbound), B (sell outbound, buy return
    commodity), REPEAT. One way: A (buy), B (sell). """
    out_name = route['out_name']
    back_name = route.get('back_name') or ''
    wp = {"GlobalShoppingList": dict(waypoint_entry("", "", {}, {}), Skip=True)}
    wp["1"] = waypoint_entry(route['start_system'], route['start_station'],
                             {back_name: 9999} if back_name else {}, {out_name: 9999})
    wp["2"] = waypoint_entry(route['system'], route['station'], {out_name: 9999},
                             {back_name: 9999} if back_name else {})
    if route.get('round_trip', True):
        wp["3"] = waypoint_entry("REPEAT", "", {}, {})
    return wp
