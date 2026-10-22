from __future__ import annotations

"""
Adapts the purchase of a trade route to the market at the moment of buying ('TradeAdaptCommodity').

The route was found with the prices of the search. While trading the supply of the commodity that makes the money
can run out (other commanders buy it, the stock does not refill fast enough) or the price at the destination drops.
Then the hold would be flown half empty, or with a commodity that is no longer the best one.

At the buy station (Market.json is current there) and with the prices of the destination station (Ardent):
  - every commodity that can be bought here and is bought at the destination is rated by profit per ton,
  - the hold is filled in that order: the best commodity as far as its stock goes, then the next one, ...
  - commodities with less than 'TradeMinProfitPerTon' (default 1000 cr/t) are not bought.
The waypoint file is updated: this station buys the new list, the destination sells it.
Without destination prices (Ardent not reachable, station not known) nothing is changed.
"""

from EDlogger import logger


def _next_trade_waypoint(waypoints: dict, key: str) -> str | None:
    """ Key of the waypoint where the goods bought at 'key' are sold (next one, after REPEAT the first one). """
    keys = [k for k, v in waypoints.items() if k != 'GlobalShoppingList' and isinstance(v, dict)]
    if key not in keys:
        return None
    order = keys[keys.index(key) + 1:] + keys[:keys.index(key)]
    for k in order:
        wp = waypoints[k]
        if (wp.get('SystemName') or '').upper() == 'REPEAT' or wp.get('Skip'):
            continue
        if wp.get('StationName'):
            return k
    return None


def _station_matches(ardent_name: str, wp_name: str) -> bool:
    from EDTradeFinder import CALLSIGN_RE, _norm
    a, b = (ardent_name or '').upper(), (wp_name or '').upper()
    if _norm(a) == _norm(b):
        return True
    m = CALLSIGN_RE.search(a)
    return bool(m and m.group(1) in b)  # carrier: Ardent has the call sign, the waypoint 'NAME CALL-SIGN'


def destination_prices(system: str, station: str) -> dict[str, tuple[int, int]] | None:
    """ {symbol: (sell price, demand)} at the destination station, or None if unknown. """
    from EDTradeFinder import ArdentClient, _norm
    try:
        rows = ArdentClient(cache_secs=300).system_commodities(system) or []
    except Exception as e:
        logger.warning(f"trade adapt: Ardent {system}: {e}")
        return None
    out = {}
    for r in rows:
        if not _station_matches(r.get('stationName') or '', station):
            continue
        price = int(r.get('sellPrice') or 0)
        if price > 0:
            out[_norm(r.get('commodityName') or '')] = (price, int(r.get('demand') or 0))
    return out or None


def adapt_buy_list(wp_obj, ap, dest_key: str) -> bool:
    """ Re-plans BuyCommodities of waypoint dest_key (we are docked there, Market.json is current) and the
    SellCommodities of the station where the goods are sold. Returns True if the waypoint file was changed. """
    from EDTradeFinder import _norm, _symbol_from_market_name, display_name
    cfg = ap.config
    if not cfg.get('TradeAdaptCommodity', True):
        return False
    wps = wp_obj.waypoints
    wp = wps.get(dest_key) or {}
    buy = wp.get('BuyCommodities') or {}
    if not buy or 'ALL' in buy:
        return False
    sell_key = _next_trade_waypoint(wps, dest_key)
    if not sell_key:
        return False
    dst = wps[sell_key]
    prices = destination_prices(dst.get('SystemName') or '', dst.get('StationName') or '')
    if not prices:
        ap.ap_ckb('log', f"Trade: no prices of {dst.get('StationName')} known, buying as planned.")
        return False

    data = wp_obj.market_parser.current_data or {}
    cap = int(ap.jn.ship_state().get('cargo_capacity') or 0)
    try:
        free = cap - int(ap.status.get_cleaned_data().get('Cargo') or 0)
    except Exception:
        free = cap
    if free <= 0:
        return False
    min_profit = int(cfg.get('TradeMinProfitPerTon', 1000))

    cands = []
    for it in data.get('Items', []):
        stock, bp = int(it.get('Stock') or 0), int(it.get('BuyPrice') or 0)
        if stock <= 0 or bp <= 0 or it.get('Rare'):
            continue
        sym = _symbol_from_market_name(it.get('Name') or '')
        name = it.get('Name_Localised') or display_name(sym)
        p = prices.get(sym) or prices.get(_norm(name))
        if not p:
            continue
        profit = p[0] - bp
        avail = min(stock, p[1]) if p[1] > 0 else stock
        if profit >= min_profit and avail > 0:
            cands.append({'name': name, 'profit': profit, 'avail': avail, 'stock': stock, 'buy': bp,
                          'sell': p[0]})
    planned = list(buy)
    if not cands:
        ap.ap_ckb('log+vce', f"Trade: nothing here sells at {dst.get('StationName')} with more than "
                             f"{min_profit} cr/t profit, buying as planned.")
        return False
    cands.sort(key=lambda c: c['profit'], reverse=True)
    # Keep the planned commodity first unless another one is clearly better (prices of the destination may be a
    # few hours old: no switching for a few percent)
    main_i = next((i for i, c in enumerate(cands) if c['name'].upper() == planned[0].upper()), None)
    if main_i and cands[main_i]['profit'] >= 0.9 * cands[0]['profit']:
        cands.insert(0, cands.pop(main_i))

    plan, left = [], free
    for c in cands:
        if left <= 0:
            break
        take = min(c['avail'], left)
        if take < min(10, left):
            continue
        plan.append((c, take))
        left -= take
    if not plan:
        return False

    new_names = [c['name'] for c, _ in plan]
    # Exact amounts: a commodity limited by the demand at the destination must not fill the rest of the hold
    new_buy = {c['name']: (9999 if i == 0 and t >= free else t) for i, (c, t) in enumerate(plan)}
    if {k.upper(): v for k, v in new_buy.items()} == {k.upper(): v for k, v in buy.items()}:
        return False
    if len(new_buy) == 1 and new_names[0].upper() == planned[0].upper():
        # back to the planned commodity alone (stock refilled): no message needed
        wp['BuyCommodities'] = new_buy
        _save(wp_obj)
        return True
    total = sum(c['profit'] * t for c, t in plan)
    main = next((c for c in cands if c['name'].upper() == planned[0].upper()), None)
    if main:
        why = f"{planned[0]}: only {main['stock']} t in stock, {main['profit']:,} cr/t"
    else:
        it0 = next((i for i in data.get('Items', []) if (i.get('Name_Localised') or '').upper() == planned[0].upper()),
                   None)
        why = (f"{planned[0]}: not in stock" if not it0 or int(it0.get('Stock') or 0) <= 0 else
               f"{planned[0]}: less than {min_profit} cr/t profit now")
    ap.ap_ckb('log+vce', f"Trade: changed purchase ({why}). Now: " +
              ", ".join(f"{t} t {c['name']} (+{c['profit']:,} cr/t)" for c, t in plan) +
              (f", {left} t empty" if left > 0 else "") + f". About {total / 1e6:.1f} M cr.")
    wp['BuyCommodities'] = new_buy
    sells = dst.setdefault('SellCommodities', {})
    for n in new_names:
        sells.setdefault(n, 9999)
    _save(wp_obj)
    return True


def _save(wp_obj):
    try:
        from pathlib import Path
        wp_obj.write_waypoints(data=None, filename='./waypoints/' + Path(wp_obj.filename).name)
    except Exception as e:
        logger.warning(f"trade adapt: saving the waypoint file: {e}")
