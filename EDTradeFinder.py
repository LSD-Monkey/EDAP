from __future__ import annotations

"""
Trade route finder (Trade tab), similar to the trade route search of Inara.

Searches the area around a reference system (usually where the ship is) for the most profitable trades:
 - one way: buy commodity X at station A, sell it at station B,
 - round trips: A -> B with X and B -> A with Y (repeated by Waypoint Assist).

Market data (EDDN data uploaded by players), setting 'TradeDataSource':
 - Spansh (https://spansh.co.uk, default): one station search of the whole area, every station with its full market,
 - Ardent Insight API (https://api.ardent-insight.com): one request per commodity.
 If the chosen source fails, the other one is used (MarketClient).
 1. Commodity report: the commodities worth checking (highest price level, not rare/salvage).
 2. For every commodity: sellers ('nearby/exports') and buyers ('nearby/imports') around the reference system.
 3. Every seller/buyer pair within the max. distance between the stations is a trade leg.
 4. Legs A->B and B->A are combined to round trips. Profit per trip and estimated profit per hour.
"""

import re
import json
import math
import time
import gzip
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from EDlogger import logger

ARDENT_BASE = "https://api.ardent-insight.com/v2"
SPANSH_SEARCH = "https://spansh.co.uk/api/stations/search"
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
    if sym in SPANSH_DISPLAY:
        return SPANSH_DISPLAY[sym]
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


AGE_KEYS = ('updatedAt', 'updated_at', 'updated', 'lastUpdated', 'timestamp', 'updatedAtDay')
_age_key_warned = False


def row_age(row: dict) -> float | None:
    """ Age in hours of a market row (buy or sell order). Tries several field names: if a row has none of them
    the age is unknown (None) and must not count as 'fresh'. """
    global _age_key_warned
    for k in AGE_KEYS:
        if row.get(k):
            return age_hours(row.get(k))
    if not _age_key_warned:
        _age_key_warned = True
        logger.warning(f"Trade finder: market row without a date field, keys: {sorted(row.keys())}")
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

    def system_commodities(self, system: str):
        """ All known buy/sell orders in the system (all stations). """
        return self.get(f"/system/name/{self.q(system)}/commodities")

    def nearby(self, kind: str, system: str, symbol: str, max_distance: float, min_volume: int, max_days: float,
               carriers: bool, **_kw):
        """ kind 'exports' (where to buy) or 'imports' (where to sell). """
        return self.get(f"/system/name/{self.q(system)}/commodity/name/{self.q(symbol)}/nearby/{kind}",
                        {'maxDistance': int(min(500, max_distance)), 'minVolume': int(max(1, min_volume)),
                         'fleetCarriers': None if carriers else 'false',
                         'maxDaysAgo': max(1, int(math.ceil(max_days)))})


# ----------------------------------------------------------------------------------------------------------------
# Spansh: station types -> Ardent/journal station types (the filters work with these)
SPANSH_TYPES = {
    'coriolisstarport': 'Coriolis', 'orbisstarport': 'Orbis', 'ocellusstarport': 'Ocellus',
    'dodecstarport': 'Dodec', 'asteroidbase': 'AsteroidBase', 'outpost': 'Outpost',
    'planetaryoutpost': 'CraterOutpost', 'planetaryport': 'CraterPort', 'settlement': 'OnFootSettlement',
    'odysseysettlement': 'OnFootSettlement', 'megaship': 'MegaShip', 'drakeclasscarrier': 'FleetCarrier',
    'spaceconstructiondepot': 'SpaceConstructionDepot', 'planetaryconstructiondepot': 'PlanetaryConstructionDepot',
}
# Spansh commodity names (display names) -> symbols where they differ (Agri-Medicines -> agriculturalmedicines)
_NAME_TO_SYMBOL = {_norm(v): k for k, v in SYMBOL_NAMES.items()}
SPANSH_DISPLAY: dict[str, str] = {}  # symbol -> name as Spansh (the game, English) writes it


def spansh_symbol(name: str) -> str:
    n = _norm(name)
    sym = _NAME_TO_SYMBOL.get(n, n)
    SPANSH_DISPLAY.setdefault(sym, name)
    return sym


def _spansh_type(t: str) -> str:
    n = _norm(t)
    if n in SPANSH_TYPES:
        return SPANSH_TYPES[n]
    if 'carrier' in n:
        return 'FleetCarrier'
    if 'settlement' in n:
        return 'OnFootSettlement'
    return t or ''


def _spansh_pad(st: dict) -> int | None:
    if st.get('large_pads') or st.get('has_large_pad'):
        return 3
    if st.get('medium_pads'):
        return 2
    if st.get('small_pads'):
        return 1
    return None


class SpanshClient:
    """ Market data from the Spansh station search, in the row format of the Ardent client (stationName,
    systemName, buyPrice, stock, ...), so that the trade finder, the presell, the fuel stop and the trade adapt work
    with both.

    Spansh returns every station with its whole market (about 70 KB per station uncompressed, gzip on the wire).
    The trade search loads the whole area once (prepare), all commodities are then taken from it. Single queries
    (fuel stop, presell) use a search for the one commodity, sorted by price or distance. """

    PAGE = 500
    MAX_RESULTS = 10000  # Spansh pages through the first 10000 results only

    def __init__(self, timeout: float = 60.0, cache_secs: float = 600.0, max_stations: int = 4000):
        self.timeout = timeout
        self.cache_secs = cache_secs
        self.max_stations = max_stations
        self.requests = 0
        self._cache: dict[str, tuple[float, object]] = {}
        # Loaded areas: (time, ref, radius, max_age_h, rows by commodity symbol)
        self._areas: list[tuple[float, str, float, float, dict[str, list[dict]]]] = []
        self._report: list[dict] | None = None

    # -- HTTP ----------------------------------------------------------------------------------------------------
    def post(self, body: dict, cache: bool = True):
        key = json.dumps(body, sort_keys=True)
        hit = self._cache.get(key) if cache else None
        if hit and time.time() - hit[0] < self.cache_secs:
            return hit[1]
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(SPANSH_SEARCH, data=data, method='POST', headers={
            'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Content-Type': 'application/json',
            'Accept-Encoding': 'gzip'})
        last_err = None
        for attempt in range(3):
            try:
                self.requests += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get('Content-Encoding', '').lower() == 'gzip' or raw[:2] == b'\x1f\x8b':
                        raw = gzip.decompress(raw)
                out = json.loads(raw.decode('utf-8'))
                if not cache:
                    return out
                self._cache[key] = (time.time(), out)
                if len(self._cache) > 40:
                    self._cache.pop(next(iter(self._cache)))
                return out
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    # 'Invalid request' (e.g. unknown reference system): no data, not an outage
                    try:
                        msg = e.read().decode('utf-8', 'ignore')[:200]
                    except Exception:
                        msg = ''
                    logger.debug(f"Spansh: 400 {msg}")
                    return None
                last_err = e
            except Exception as e:
                last_err = e
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Spansh request failed ({last_err})")

    @staticmethod
    def _age_filter(max_age_h: float) -> dict:
        t0 = datetime.fromtimestamp(time.time() - max_age_h * 3600.0, tz=timezone.utc)
        t1 = datetime.fromtimestamp(time.time() + 86400.0, tz=timezone.utc)
        return {'value': [t0.strftime('%Y-%m-%dT%H:%M:%SZ'), t1.strftime('%Y-%m-%dT%H:%M:%SZ')],
                'comparison': '<=>'}

    def search(self, filters: dict, ref: str | None = None, sort: list | None = None, limit: int = 500) -> list[dict]:
        out = []
        page = 0
        while len(out) < limit and (page + 1) * self.PAGE <= self.MAX_RESULTS + self.PAGE:
            size = min(self.PAGE, limit - len(out))
            body = {'filters': filters, 'size': size, 'page': page}
            if ref:
                body['reference_system'] = ref
            if sort:
                body['sort'] = sort
            res = self.post(body)
            if not res:
                break
            rows = res.get('results') or []
            out.extend(rows)
            if len(rows) < size or len(out) >= int(res.get('count') or 0):
                break
            page += 1
        return out

    # -- conversion ----------------------------------------------------------------------------------------------
    @staticmethod
    def _station_row(st: dict) -> dict:
        return {
            'marketId': st.get('market_id') or st.get('id'), 'stationName': st.get('name'),
            'systemName': st.get('system_name'), 'stationType': _spansh_type(st.get('type') or ''),
            'maxLandingPadSize': _spansh_pad(st), 'distanceToArrival': st.get('distance_to_arrival'),
            'distance': st.get('distance'), 'systemX': st.get('system_x'), 'systemY': st.get('system_y'),
            'systemZ': st.get('system_z'), 'updatedAt': st.get('market_updated_at'),
        }

    def _rows(self, stations: list[dict]) -> dict[str, list[dict]]:
        """ symbol -> one row per station with buy price/stock and sell price/demand. """
        by_sym: dict[str, list[dict]] = {}
        for st in stations:
            base = self._station_row(st)
            for m in st.get('market') or []:
                sym = spansh_symbol(m.get('commodity') or '')
                if not sym:
                    continue
                r = dict(base, commodityName=sym, buyPrice=int(m.get('buy_price') or 0),
                         stock=int(m.get('supply') or 0), sellPrice=int(m.get('sell_price') or 0),
                         demand=int(m.get('demand') or 0))
                by_sym.setdefault(sym, []).append(r)
        return by_sym

    # -- area (trade search) -------------------------------------------------------------------------------------
    def prepare(self, ref_system: str, radius: float, max_age_hours: float, progress=None) -> int:
        """ Loads all stations with a market within radius ly of ref_system whose market is at most max_age_hours
        old. Returns the number of stations. """
        if self._area(ref_system, radius, max_age_hours) is not None:
            return -1
        progress = progress or (lambda m: None)
        filters = {'has_market': {'value': True}, 'distance': {'min': '0', 'max': str(float(radius))},
                   'market_updated_at': self._age_filter(max_age_hours)}
        # Every page is converted to compact rows right away: a full station (market, modules, ships) is ~70 KB
        by_sym: dict[str, list[dict]] = {}
        n, page = 0, 0
        while n < self.max_stations:
            body = {'filters': filters, 'size': self.PAGE, 'page': page, 'reference_system': ref_system,
                    'sort': [{'distance': {'direction': 'asc'}}]}
            res = self.post(body, cache=False)
            if res is None:
                raise RuntimeError(f"Spansh: reference system '{ref_system}' not known")
            rows = res.get('results') or []
            total = int(res.get('count') or 0)
            for sym, lst in self._rows(rows).items():
                by_sym.setdefault(sym, []).extend(lst)
            n += len(rows)
            del res, rows
            progress(f"Spansh: {n}/{min(total, self.max_stations)} stations loaded...")
            if n >= total or n % self.PAGE or (page + 2) * self.PAGE > self.MAX_RESULTS:
                break
            page += 1
        # Do not keep the full answers (markets, modules, ships) in the request cache
        self._cache.clear()
        self._areas = [a for a in self._areas if time.time() - a[0] < self.cache_secs][-2:]
        self._areas.append((time.time(), ref_system.lower(), float(radius), float(max_age_hours), by_sym))
        self._report = self._build_report(by_sym)
        logger.info(f"Spansh: {n} stations within {radius:g} ly of {ref_system} "
                    f"(market <= {max_age_hours:g} h), {len(by_sym)} commodities, {self.requests} requests")
        return n

    def _area(self, ref: str, radius: float, max_age_h: float) -> dict[str, list[dict]] | None:
        for t, r, rad, age, by_sym in reversed(self._areas):
            if time.time() - t < self.cache_secs and r == (ref or '').lower() and rad >= radius - 0.01 \
                    and age >= max_age_h - 0.01:
                return by_sym
        return None

    @staticmethod
    def _build_report(by_sym: dict[str, list[dict]]) -> list[dict]:
        """ Commodity report like Ardent '/commodities', made from the loaded area. """
        rep = []
        for sym, rows in by_sym.items():
            sells = [r['sellPrice'] for r in rows if r['sellPrice'] > 0 and r['demand'] > 0]
            buys = [r['buyPrice'] for r in rows if r['buyPrice'] > 0 and r['stock'] > 0]
            rep.append({'commodityName': sym, 'totalStock': sum(r['stock'] for r in rows),
                        'totalDemand': sum(r['demand'] for r in rows),
                        'avgSellPrice': (sum(sells) / len(sells)) if sells else 0,
                        'maxSellPrice': max(sells) if sells else 0,
                        'minBuyPrice': min(buys) if buys else 0})
        return rep

    # -- Ardent compatible interface -----------------------------------------------------------------------------
    def commodities(self):
        """ Report of the area loaded last (prepare), None without one. """
        return self._report

    def nearby(self, kind: str, system: str, symbol: str, max_distance: float, min_volume: int, max_days: float,
               carriers: bool, by: str = 'price', limit: int = 60):
        """ kind 'exports' (stations that sell it, where to buy) or 'imports' (stations that buy it). """
        max_age_h = max_days * 24.0
        sym = _norm(symbol)
        min_volume = int(max(1, min_volume))
        area = self._area(system, max_distance, max_age_h)
        if area is not None:
            rows = area.get(sym) or []
        else:
            name = SPANSH_DISPLAY.get(sym) or display_name(sym)
            field = 'supply' if kind == 'exports' else 'demand'
            filters = {'market': [{'name': name, field: {'value': [str(min_volume), '999999999'],
                                                          'comparison': '<=>'}}],
                       'distance': {'min': '0', 'max': str(float(max_distance))},
                       'market_updated_at': self._age_filter(max_age_h)}
            if by == 'distance':
                sort = [{'distance': {'direction': 'asc'}}]
            elif kind == 'exports':
                sort = [{'market_buy_price': [{'name': name, 'direction': 'asc'}]}]
            else:
                sort = [{'market_sell_price': [{'name': name, 'direction': 'desc'}]}]
            stations = self.search(filters, ref=system, sort=sort, limit=limit)
            rows = self._rows(stations).get(sym) or []
            self._cache.clear()
        out = []
        for r in rows:
            if r['distance'] is not None and float(r['distance']) > max_distance:
                continue
            if not carriers and _norm(r.get('stationType') or '') in CARRIER_TYPES:
                continue
            if kind == 'exports':
                if r['buyPrice'] > 0 and r['stock'] >= min_volume:
                    out.append(r)
            elif r['sellPrice'] > 0 and r['demand'] >= min_volume:
                out.append(r)
        return out

    def system_commodities(self, system: str):
        """ All buy/sell orders of all stations in the system. """
        stations = self.search({'system_name': {'value': system}, 'has_market': {'value': True}}, limit=500)
        stations = [s for s in stations if (s.get('system_name') or '').lower() == (system or '').lower()]
        rows = [r for lst in self._rows(stations).values() for r in lst]
        self._cache.clear()
        return rows

    def system(self, system: str):
        res = self.search({'system_name': {'value': system}}, limit=1)
        return res[0] if res else None


def data_source() -> str:
    """ 'Spansh' or 'Ardent' (setting TradeDataSource in configs/AP.json). """
    try:
        with open(os.path.join('.', 'configs', 'AP.json'), encoding='utf-8') as fh:
            src = json.load(fh).get('TradeDataSource') or 'Spansh'
    except Exception:
        src = 'Spansh'
    return 'Ardent' if str(src).lower().startswith('ard') else 'Spansh'


class MarketClient:
    """ The chosen market data source with the other one as fallback: if a request of the active source fails
    (no answer, error) or the trade search gets no commodity list from it, the other source is used from then on
    (for this client). """

    def __init__(self, source: str | None = None, cache_secs: float = 600.0):
        src = source or data_source()
        sp, ar = SpanshClient(cache_secs=cache_secs), ArdentClient(cache_secs=cache_secs)
        self.clients = [sp, ar] if src == 'Spansh' else [ar, sp]
        self.active = 0
        self.prepared: tuple | None = None

    @property
    def name(self) -> str:
        return 'Spansh' if isinstance(self.clients[self.active], SpanshClient) else 'Ardent'

    @property
    def requests(self) -> int:
        return sum(c.requests for c in self.clients)

    def _switch(self, why) -> bool:
        if self.active + 1 >= len(self.clients):
            return False
        old = self.name
        self.active += 1
        logger.warning(f"Market data: {old} failed ({why}), using {self.name}.")
        if self.prepared:
            self._prepare_active()
        return True

    def _call(self, fn: str, *a, **kw):
        while True:
            c = self.clients[self.active]
            try:
                return getattr(c, fn)(*a, **kw)
            except Exception as e:
                if not self._switch(e):
                    raise

    def _prepare_active(self):
        c = self.clients[self.active]
        if hasattr(c, 'prepare'):
            c.prepare(*self.prepared[:3], progress=self.prepared[3])

    def prepare(self, ref_system: str, radius: float, max_age_hours: float, progress=None):
        self.prepared = (ref_system, radius, max_age_hours, progress)
        while True:
            try:
                self._prepare_active()
                return
            except Exception as e:
                if not self._switch(e):
                    raise

    def commodities(self):
        rep = self._call('commodities')
        while not rep and self._switch('no commodity list'):
            rep = self._call('commodities')
        return rep

    def nearby(self, *a, **kw):
        return self._call('nearby', *a, **kw)

    def system_commodities(self, system: str):
        return self._call('system_commodities', system)

    def system(self, system: str):
        return self._call('system', system)


def estimate_trip_secs(distance_ly: float, jump_range: float, arrival_a: float, arrival_b: float,
                       round_trip: bool = True, secs_per_jump: float = 75.0,
                       secs_station: float = 340.0) -> tuple[int, float]:
    """ Jumps per way and the estimated time in seconds (one way or round trip).
    secs_per_jump: alignment + FSD charge + hyperspace + star avoidance (measured 2026-10-20: ~92 s, less with the
    FSD charging during the alignment). secs_station: everything at a station except the supercruise flight:
    arrival in the system, approach + docking (~2.5 min), trade (~1 min), launch until supercruise (~1.5 min)
    (measured ~5.5 min). Supercruise: ~2 min for 76 Ls, grows with the square root of the distance.
    learn_timing() replaces both with the values of your own recent flights. """
    # The plotted route is not a straight line (2026-10-20: 93 ly direct, 8 jumps of max. 13.5 ly)
    jumps = max(1, int(math.ceil(distance_ly * 1.12 / max(1.0, jump_range))))

    def sc(ls):
        return 60.0 + 8.0 * math.sqrt(max(0.0, float(ls or 0)))

    if round_trip:
        total = 2 * jumps * secs_per_jump + sc(arrival_a) + sc(arrival_b) + 2 * secs_station
    else:
        total = jumps * secs_per_jump + sc(arrival_b) + 2 * secs_station
    return jumps, total


CALLSIGN_RE = re.compile(r'\b([A-Z0-9]{3}-[A-Z0-9]{3})\b')
# Fleet carrier names by call sign ('N6H-0XW' -> 'Legacy of caliban N6H-0XW'). The market data (EDDN/Ardent) only
# has the call sign, the Nav Panel shows 'NAME CALL-SIGN'. Filled from the journals (FSSSignalDiscovered).
CARRIER_NAMES: dict[str, str] = {}
_carrier_files_read: dict[str, float] = {}


def load_carrier_names(journal_dir: str, max_files: int = 400) -> dict[str, str]:
    """ Reads the names of all fleet carriers seen in the journals (FSSSignalDiscovered, SignalType FleetCarrier,
    'SignalName': 'Legacy of caliban N6H-0XW'). Files already read are skipped unless changed. """
    import os
    from os.path import join, getmtime
    try:
        files = sorted((join(journal_dir, f) for f in os.listdir(journal_dir)
                        if f.startswith('Journal.') and f.endswith('.log')), key=getmtime)[-max_files:]
    except Exception:
        return CARRIER_NAMES
    for fn in files:
        try:
            mt = getmtime(fn)
            if _carrier_files_read.get(fn) == mt:
                continue
            with open(fn, encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    if '"FleetCarrier"' not in line or 'FSSSignalDiscovered' not in line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    name = (ev.get('SignalName') or '').strip()
                    m = CALLSIGN_RE.search(name.upper())
                    if m and len(name) > 8:
                        CARRIER_NAMES[m.group(1)] = name
            _carrier_files_read[fn] = mt
        except Exception:
            continue
    return CARRIER_NAMES


_edsm_cache: dict[str, tuple[float, set | None]] = {}


def edsm_carriers_in_system(system: str) -> set[str] | None:
    """ Call signs of the fleet carriers EDSM lists in the system now, or None if EDSM can not be reached. """
    hit = _edsm_cache.get(system.upper())
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    url = "https://www.edsm.net/api-system-v1/stations?" + urllib.parse.urlencode({'systemName': system})
    result = None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8') or '{}')
        if isinstance(data, dict) and isinstance(data.get('stations'), list):
            result = set()
            for st in data['stations']:
                if 'carrier' in (st.get('type') or '').lower():
                    m = CALLSIGN_RE.search((st.get('name') or '').upper())
                    if m:
                        result.add(m.group(1))
            if not result:
                result = None  # no carrier listed at all: EDSM may simply not know them, do not reject
    except Exception as e:
        logger.warning(f"EDSM stations of {system}: {e}")
    _edsm_cache[system.upper()] = (time.time(), result)
    return result


def carrier_display_name(station: str | None) -> str:
    """ 'N6H-0XW' -> 'Legacy of caliban N6H-0XW' if the carrier was seen in the journals, else unchanged. """
    st = (station or '').strip()
    m = CALLSIGN_RE.fullmatch(st.upper())
    if m and m.group(1) in CARRIER_NAMES:
        return CARRIER_NAMES[m.group(1)]
    return st


def learn_timing(journal_dir: str, max_files: int = 12) -> dict | None:
    """ Times of your own recent flights from the journals (used for the profit per hour):
     - secs_per_jump: FSDJump -> next FSDJump of the same flight (align, charge, hyperspace, star avoidance),
     - secs_station: drop at the station -> docked, docked -> undocked, undocked -> supercruise, + 60 s for the
       arrival in the system (star avoidance, SC Assist activation). The supercruise flight itself is estimated
       from the distance of the station.
    Returns None if there are not enough flights. """
    import os
    from os.path import join, getmtime
    try:
        files = sorted((join(journal_dir, f) for f in os.listdir(journal_dir)
                        if f.startswith('Journal.') and f.endswith('.log')), key=getmtime)[-max_files:]
    except Exception:
        return None

    def ts(ev):
        try:
            return datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp()
        except Exception:
            return None

    jumps, docks, trades, launches = [], [], [], []
    last_jump = last_drop = last_docked = last_undocked = None
    for path in files:
        try:
            with open(path, encoding='utf-8') as fh:
                lines = fh.readlines()
        except Exception:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            e, t = ev.get('event'), ts(ev)
            if t is None:
                continue
            if e == 'FSDJump':
                if last_jump is not None and 20 < t - last_jump < 400:
                    jumps.append(t - last_jump)
                last_jump = t
            elif e == 'SupercruiseExit':
                last_drop, last_jump = t, None
            elif e == 'Docked':
                if last_drop is not None and 20 < t - last_drop < 600:
                    docks.append(t - last_drop)
                last_docked, last_drop, last_jump = t, None, None
            elif e == 'Undocked':
                if last_docked is not None and 10 < t - last_docked < 900:
                    trades.append(t - last_docked)
                last_undocked, last_docked = t, None
            elif e == 'StartJump' and ev.get('JumpType') == 'Supercruise':
                if last_undocked is not None and 5 < t - last_undocked < 400:
                    launches.append(t - last_undocked)
                last_undocked = None
            elif e in ('LoadGame', 'Shutdown', 'Died'):
                last_jump = last_drop = last_docked = last_undocked = None

    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else None

    if len(jumps) < 3 or not docks or not trades or not launches:
        return None
    return {'secs_per_jump': med(jumps),
            'secs_station': med(docks) + med(trades) + med(launches) + 60.0,
            'samples': len(jumps)}


class TradeFinder:
    def __init__(self, client=None, progress=None):
        self.client = client or MarketClient()
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
        age = row_age(row)
        if stype in CARRIER_TYPES:
            # Carriers move and change their orders: stricter age, and an unknown age is not accepted
            if age is None:
                return 'carrier price age unknown'
            if age > min(f['max_age_hours'], f.get('carrier_max_age_hours', 6)):
                return 'carrier price too old'
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
        station = row.get('stationName')
        if _norm(row.get('stationType') or '') in CARRIER_TYPES:
            station = carrier_display_name(station)
        return {'system': row.get('systemName'), 'station': station,
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
                    settlements: bool = False, round_trips: bool = True, commodity_count: int = 80,
                    jump_range: float = 15.0, secs_per_jump: float = 75.0, secs_station: float = 340.0,
                    max_results: int = 150, legs_per_commodity: int = 4000,
                    carrier_max_age_hours: float = 6.0, check_carriers: bool = True) -> list[dict]:
        """ All sellers x all buyers of every commodity are paired (numpy), not only the cheapest/most expensive
        60 of the whole search area: with a large area the best buyer near a seller was often not among them, that
        was the main reason why Inara found better routes. """
        import numpy as np

        cargo = max(1, int(cargo))
        min_volume = int(min_volume) if min_volume and min_volume > 0 else cargo
        f = dict(carriers=carriers, megaships=megaships, planetary=planetary, settlements=settlements,
                 min_pad=min_pad, max_arrival_ls=max_arrival_ls, max_age_hours=max_age_hours,
                 carrier_max_age_hours=carrier_max_age_hours)
        self.rejected = {}
        # Stations of a round trip are both start stations, so both need to be within the start distance plus
        # the distance between the stations (the closer one becomes the start).
        radius = min(500.0, max_start_distance + max_hop_distance)
        max_days = max(1.0, max_age_hours / 24.0)

        if hasattr(self.client, 'prepare'):
            self.progress(f"Loading the markets within {radius:g} ly of {ref_system}...")
            self.client.prepare(ref_system, radius, max_age_hours, progress=self.progress)
        self.progress("Loading the commodity list...")
        symbols = self.commodity_list(commodity_count)
        if not symbols:
            raise RuntimeError("Could not load the commodity list (Spansh / Ardent).")
        src = getattr(self.client, 'name', '')
        if src:
            logger.info(f"Trade finder: market data from {src}")
        if src == 'Spansh':
            # All markets of the area are loaded already: checking every commodity costs no requests
            symbols = self.commodity_list(max(commodity_count, 400))
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
        sell_at: dict[str, dict[str, tuple]] = {}  # commodity -> station -> (buy price, stock, age) (we can buy)
        buy_at: dict[str, dict[str, tuple]] = {}  # commodity -> station -> (sell price, demand, age) (we can sell)
        names: dict[str, str] = {}
        done = 0

        def pos(row):
            p = (row.get('systemX'), row.get('systemY'), row.get('systemZ'))
            return None if None in p else p

        with ThreadPoolExecutor(max_workers=6) as pool:
            for sym, ex, im in pool.map(load, symbols):
                done += 1
                names[sym] = display_name(sym)
                sellers = [r for r in ex if (r.get('buyPrice') or 0) > 0 and pos(r) and self._ok(r, f)]
                buyers = [r for r in im if (r.get('sellPrice') or 0) > 0 and pos(r) and self._ok(r, f)]
                sa, ba = {}, {}
                for r in sellers:
                    k = self._key(r)
                    stations.setdefault(k, self._station(r))
                    sa[k] = (int(r['buyPrice']), int(r.get('stock') or 0), row_age(r))
                for r in buyers:
                    k = self._key(r)
                    stations.setdefault(k, self._station(r))
                    ba[k] = (int(r['sellPrice']), int(r.get('demand') or 0), row_age(r))
                sell_at[sym], buy_at[sym] = sa, ba
                if sa and ba:
                    sk, bk = list(sa), list(ba)
                    sp = np.array([stations[k]['pos'] for k in sk], dtype=float)
                    bp = np.array([stations[k]['pos'] for k in bk], dtype=float)
                    buy = np.array([sa[k][0] for k in sk], dtype=float)
                    stock = np.array([sa[k][1] if sa[k][1] > 0 else cargo for k in sk], dtype=float)
                    sell = np.array([ba[k][0] for k in bk], dtype=float)
                    demand = np.array([ba[k][1] if ba[k][1] > 0 else cargo for k in bk], dtype=float)
                    dist = np.sqrt(((sp[:, None, :] - bp[None, :, :]) ** 2).sum(axis=2))
                    profit = sell[None, :] - buy[:, None]
                    amount = np.minimum(np.minimum(stock[:, None], demand[None, :]), cargo)
                    total = profit * amount
                    ok = (dist <= max_hop_distance) & (profit > 0) & (dist > 0.01)
                    total = np.where(ok, total, -1.0)
                    flat = total.ravel()
                    cnt = int((flat > 0).sum())
                    if cnt:
                        k_best = min(cnt, legs_per_commodity)
                        idx = np.argpartition(-flat, k_best - 1)[:k_best]
                        for fi in idx:
                            i, j = divmod(int(fi), len(bk))
                            t = float(flat[fi])
                            if t <= 0:
                                continue
                            key = (sk[i], bk[j])
                            leg = legs.get(key)
                            if leg is None or t > leg['total']:
                                ages = [a for a in (sa[sk[i]][2], ba[bk[j]][2]) if a is not None]
                                legs[key] = {
                                    'symbol': sym, 'name': names[sym], 'buy': int(buy[i]), 'sell': int(sell[j]),
                                    'profit': int(profit[i, j]), 'amount': int(amount[i, j]), 'total': int(t),
                                    'distance': float(dist[i, j]), 'age_h': max(ages) if ages else None,
                                    'supply': sa[sk[i]][1], 'demand': ba[bk[j]][1],
                                    'age_buy': sa[sk[i]][2], 'age_sell': ba[bk[j]][2],
                                }
                self.progress(f"Commodities checked: {done}/{len(symbols)}, {len(legs)} trades found.")

        if self.rejected:
            logger.info("Trade finder: stations skipped: " +
                        ", ".join(f"{k} {v}" for k, v in sorted(self.rejected.items())))

        def best_leg(ka: str, kb: str) -> dict | None:
            """ Best commodity from station ka to kb (also commodities that were not among the best trades). """
            leg = legs.get((ka, kb))
            best = dict(leg) if leg else None
            for sym, sa in sell_at.items():
                s_ = sa.get(ka)
                b_ = buy_at[sym].get(kb) if s_ else None
                if not s_ or not b_:
                    continue
                profit = b_[0] - s_[0]
                if profit <= 0:
                    continue
                amount = min(cargo, s_[1] if s_[1] > 0 else cargo, b_[1] if b_[1] > 0 else cargo)
                total = profit * amount
                if best is None or total > best['total']:
                    ages = [a for a in (s_[2], b_[2]) if a is not None]
                    best = {'symbol': sym, 'name': names[sym], 'buy': s_[0], 'sell': b_[0], 'profit': profit,
                            'amount': amount, 'total': total,
                            'distance': self._dist(stations[ka], stations[kb]) or 0.0,
                            'age_h': max(ages) if ages else None, 'supply': s_[1], 'demand': b_[1],
                            'age_buy': s_[2], 'age_sell': b_[2]}
            return best

        routes = []
        ranked = sorted(legs.items(), key=lambda kv: kv[1]['total'], reverse=True)
        if round_trips:
            seen = set()
            for (ka, kb), out in ranked[:25000]:
                pair = (ka, kb) if ka < kb else (kb, ka)
                if pair in seen:
                    continue
                seen.add(pair)
                back = best_leg(kb, ka)
                a, b = stations[ka], stations[kb]
                if back is not None:
                    # Start at the station that is closer to the reference system
                    if b['dist_ref'] < a['dist_ref'] and b['dist_ref'] <= max_start_distance:
                        a, b, out, back = b, a, back, out
                if a['dist_ref'] > max_start_distance:
                    continue
                routes.append(self._route(a, b, out, back, jump_range, secs_per_jump, secs_station, True))
        else:
            for (ka, kb), out in ranked:
                a, b = stations[ka], stations[kb]
                if a['dist_ref'] > max_start_distance:
                    continue
                routes.append(self._route(a, b, out, None, jump_range, secs_per_jump, secs_station, False))

        routes.sort(key=lambda r: r['profit_hour'], reverse=True)
        if carriers and check_carriers:
            routes = self._check_carriers(routes, max_results)
        self.progress(f"{len(routes)} {'round trips' if round_trips else 'trades'} found "
                      f"({self.client.requests} requests).")
        return routes[:max_results]

    def _check_carriers(self, routes: list[dict], max_results: int) -> list[dict]:
        """ Carriers in the best routes: are they still in the system? (EDSM station list of the system, kept up to
        date by the carrier jumps reported via EDDN). Routes with a carrier that is no longer there are removed.
        If EDSM can not be reached the routes are kept. """
        out, systems = [], {}
        checked = 0
        for r in routes:
            if len(out) >= max_results:
                break
            ok = True
            for sys_key, st_key, type_key in (('start_system', 'start_station', 'start_type'),
                                              ('system', 'station', 'station_type')):
                if _norm(r.get(type_key) or '') not in CARRIER_TYPES:
                    continue
                system = r[sys_key]
                if system not in systems:
                    if checked >= 60:
                        systems[system] = None  # do not ask EDSM for too many systems
                    else:
                        checked += 1
                        self.progress(f"Checking fleet carriers in {system} (EDSM)...")
                        systems[system] = edsm_carriers_in_system(system)
                present = systems[system]
                if present is None:
                    continue  # unknown
                m = CALLSIGN_RE.search((r[st_key] or '').upper())
                if m and m.group(1) not in present:
                    ok = False
                    self.rejected['carrier left the system'] = self.rejected.get('carrier left the system', 0) + 1
                    break
            if ok:
                out.append(r)
        return out

    @staticmethod
    def _route(a: dict, b: dict, out: dict, back: dict | None, jump_range: float, secs_per_jump: float,
               secs_station: float = 340.0, round_trip: bool | None = None) -> dict:
        if round_trip is None:
            round_trip = back is not None
        jumps, secs = estimate_trip_secs(out['distance'], jump_range, a['arrival_ls'], b['arrival_ls'],
                                         round_trip=round_trip, secs_per_jump=secs_per_jump,
                                         secs_station=secs_station)
        profit = out['total'] + (back['total'] if back else 0)
        ages = [x for x in (out.get('age_h'), back.get('age_h') if back else None) if x is not None]
        return {
            'start_system': a['system'], 'start_station': a['station'], 'start_type': a['station_type'],
            'start_arrival_ls': a['arrival_ls'], 'dist_to_start': a['dist_ref'],
            'system': b['system'], 'station': b['station'], 'station_type': b['station_type'],
            'arrival_ls': b['arrival_ls'], 'distance': out['distance'], 'jumps': jumps, 'trip_secs': secs,
            'out_name': out['name'], 'out_buy': out['buy'], 'out_sell': out['sell'], 'out_profit': out['profit'],
            'out_amount': out['amount'], 'out_total': out['total'], 'out_supply': out['supply'],
            'out_demand': out['demand'], 'out_age_buy': out.get('age_buy'), 'out_age_sell': out.get('age_sell'),
            'back_age_buy': back.get('age_buy') if back else None,
            'back_age_sell': back.get('age_sell') if back else None,
            'back_name': back['name'] if back else '', 'back_buy': back['buy'] if back else 0,
            'back_sell': back['sell'] if back else 0, 'back_profit': back['profit'] if back else 0,
            'back_amount': back['amount'] if back else 0, 'back_total': back['total'] if back else 0,
            'round_trip': round_trip,
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
