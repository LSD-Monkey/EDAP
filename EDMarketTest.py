from __future__ import annotations

"""
Market test: buys a commodity once at the station we are docked at and (optionally) sells it again.
Runs the same functions as the trade of Waypoint Assist (open market, select BUY/SELL, find the commodity in the
list, buy/sell, close the dialog) and logs every step with the result, so these sequences can be tested without
flying a whole trade route.
"""

import difflib
import time
from time import sleep

from CargoParser import CargoParser
from EDAP_data import FlagsDocked
from EDlogger import logger


class MarketTest:
    def __init__(self, ap):
        self.ap = ap
        self.log = lambda msg: ap.ap_ckb('log', msg)
        self.say = lambda msg: ap.ap_ckb('log+vce', msg)
        self.results: list[tuple[str, bool | None, str]] = []  # (step, ok, detail)

    def _step(self, name: str, ok: bool | None, detail: str = '', t0: float | None = None):
        if t0 is not None:
            detail = (detail + " " if detail else "") + f"({time.time() - t0:.1f} s)"
        self.results.append((name, ok, detail))
        mark = {True: "OK  ", False: "FAIL", None: "INFO"}[ok]
        self.log(f"[Market test] {mark} {name}: {detail}")

    @staticmethod
    def _select_state(mkt) -> bool | None:
        """ True = checked by OCR, None = not checked (counted position), False = failed. """
        info = mkt.last_select_info or ''
        if mkt.last_select_failed or info.startswith("FAILED"):
            return False
        if info.startswith("OCR confirmed"):
            return True
        return None

    def _cargo(self) -> int:
        try:
            return int(self.ap.status.get_cleaned_data().get('Cargo') or 0)
        except Exception:
            return 0

    def _wait_cargo_change(self, before: int, timeout: float = 8.0) -> int:
        t0 = time.time()
        cur = self._cargo()
        while cur == before and time.time() - t0 < timeout:
            sleep(0.5)
            cur = self._cargo()
        return cur

    def _find_name(self, name: str) -> str | None:
        """ Exact commodity name from Market.json (case-insensitive), with suggestions if not found. """
        mkt = self.ap.stn_svcs_in_ship.commodities_market
        data = mkt.market_parser.get_market_data()
        items = (data or {}).get('Items', []) if isinstance(data, dict) else []
        names = [i.get('Name_Localised', '') for i in items]
        for n in names:
            if n.upper() == name.upper():
                return n
        close = difflib.get_close_matches(name, names, n=5, cutoff=0.5)
        self._step("Commodity", False, f"'{name}' is not in this market." +
                   (f" Did you mean: {', '.join(close)}?" if close else ""))
        return None

    def _cargo_count(self, name: str) -> int:
        cp = CargoParser()
        try:
            cp.get_cargo_data()
            item = cp.get_item(name)
            return int(item['Count']) if item else 0
        except Exception:
            return 0

    def run(self, name: str, qty: int = 1, sell_back: bool = True) -> bool:
        """ Buy qty of the commodity and sell it again. With a full hold (or not enough free space) and the
        commodity on board the order is reversed: sell first, then buy back. That is the order of the trade route
        (sell, then buy at the same station). """
        ap = self.ap
        mkt = ap.stn_svcs_in_ship.commodities_market
        t_start = time.time()
        self.results = []
        name = (name or '').strip()
        qty = max(1, int(qty))

        if not name:
            self._step("Start", False, "no commodity entered")
            return self._summary(t_start)
        if not ap.status.get_flag(FlagsDocked):
            self._step("Start", False, "the ship is not docked at a station")
            return self._summary(t_start)

        cap = ap.jn.ship_state().get('cargo_capacity') or 0
        cargo0 = self._cargo()
        free = cap - cargo0
        on_board = self._cargo_count(name)
        sell_first = free < qty and on_board > 0
        if sell_first and not sell_back:
            self._step("Start", False, f"not enough free cargo space ({free} t) for {qty} t. Tick 'Sell it again' "
                                       f"to sell {name} first and buy it back.")
            return self._summary(t_start)
        if free <= 0 and not sell_first:
            self._step("Start", False, f"no free cargo space and no {name} on board to sell first")
            return self._summary(t_start)
        if sell_first:
            qty = min(qty, on_board)
            self.say(f"Market test: hold full, sell {qty} {name} first and buy it back.")
        else:
            qty = min(qty, free)
            self.say(f"Market test: buy {qty} {name}" + (" and sell it again." if sell_back else "."))
        self._step("Start", True, f"docked at {ap.jn.ship_state().get('cur_station')}, cargo {cargo0}/{cap} t, "
                                  f"free {free} t, {name} on board {on_board} t")

        # 1. Market
        t0 = time.time()
        ok = ap.stn_svcs_in_ship.goto_commodities_market()
        self._step("Open commodities market", bool(ok), "", t0)
        if not ok:
            return self._finish(t_start)
        real_name = self._find_name(name)
        if real_name is None:
            return self._finish(t_start)

        if sell_first:
            sold = self._sell(real_name, qty)
            if sold > 0:
                self._buy(real_name, sold)
            else:
                self._step("Buy back", None, "skipped, nothing was sold")
        else:
            bought = self._buy(real_name, qty)
            if sell_back and bought > 0:
                self._sell(real_name, bought)
            elif sell_back:
                self._step("Sell", None, "skipped, nothing was bought")

        return self._finish(t_start)

    def _check_market_state(self, what: str):
        mkt = self.ap.stn_svcs_in_ship.commodities_market
        self._step(f"Dialog after {what}", None, mkt.last_dialog_info or "-")
        in_menu = mkt.in_station_menu()
        self._step("Still in the market", not in_menu, "station menu shown!" if in_menu else "yes")

    def _buy(self, real_name: str, qty: int) -> int:
        """ Select BUY, buy qty, check the cargo. Returns the tons bought. """
        ap = self.ap
        mkt = ap.stn_svcs_in_ship.commodities_market
        mkt.market_parser.get_market_data()
        if not mkt.market_parser.can_buy_item(real_name):
            self._step("Buy", False, f"'{real_name}' is not sold here or has no stock")
            return 0
        t0 = time.time()
        ok = mkt.select_buy(ap.keys)
        self._step("Select BUY", ok is not False, "", t0)
        if ok is False:
            return 0
        cap = ap.jn.ship_state().get('cargo_capacity') or 0
        before = self._cargo()
        t0 = time.time()
        mkt.last_select_info = ''
        mkt.last_dialog_info = ''
        mkt.last_select_failed = False
        _, act_qty = mkt.buy_commodity(ap.keys, real_name, qty, cap - before)
        self._step(f"Find '{real_name}' in the BUY list", self._select_state(mkt), mkt.last_select_info or "-")
        if mkt.last_select_failed or act_qty <= 0:
            self._step("Buy", False, "nothing bought", t0)
            return 0
        after = self._wait_cargo_change(before)
        bought = after - before
        self._step("Buy", bought > 0, f"wanted {act_qty}, cargo {before} -> {after} t (+{bought})", t0)
        self._check_market_state("buying")
        return max(0, bought)

    def _sell(self, real_name: str, qty: int) -> int:
        """ Select SELL, sell qty, check the cargo. Returns the tons sold. """
        ap = self.ap
        mkt = ap.stn_svcs_in_ship.commodities_market
        mkt.market_parser.get_market_data()
        if not mkt.market_parser.can_sell_item(real_name):
            self._step("Sell", False, f"this station does not buy '{real_name}'")
            return 0
        t0 = time.time()
        ok = mkt.select_sell(ap.keys)
        self._step("Select SELL", ok is not False, "", t0)
        if ok is False:
            return 0
        cargo_parser = CargoParser()
        t_wait = time.time()
        cargo_parser.get_cargo_data()
        while cargo_parser.get_item(real_name) is None and time.time() - t_wait < 6:
            sleep(0.5)
            cargo_parser.get_cargo_data()
        if cargo_parser.get_item(real_name) is None:
            self._step("Sell", False, f"'{real_name}' not found in Cargo.json")
            return 0
        t0 = time.time()
        mkt.last_select_info = ''
        mkt.last_dialog_info = ''
        mkt.last_select_failed = False
        before = self._cargo()
        _, sell_qty = mkt.sell_commodity(ap.keys, real_name, qty, cargo_parser)
        self._step(f"Find '{real_name}' in the SELL list", self._select_state(mkt), mkt.last_select_info or "-")
        after = self._wait_cargo_change(before) if sell_qty > 0 else self._cargo()
        sold = before - after
        self._step("Sell", sold > 0, f"wanted {sell_qty}, cargo {before} -> {after} t (-{sold})", t0)
        self._check_market_state("selling")
        return max(0, sold)

    def _finish(self, t_start: float) -> bool:
        try:
            sleep(1.0)
            self.ap.ship_control.goto_cockpit_view()
        except Exception as e:
            logger.warning(f"Market test: back to cockpit failed: {e}")
        return self._summary(t_start)

    def _summary(self, t_start: float) -> bool:
        fails = [r for r in self.results if r[1] is False]
        dur = time.time() - t_start
        if fails:
            self.say(f"Market test finished with {len(fails)} error(s) after {dur:.0f} s: "
                     + "; ".join(f"{n}: {d}" for n, _, d in fails))
        else:
            self.say(f"Market test passed ({dur:.0f} s).")
        return not fails
