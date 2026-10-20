from __future__ import annotations

"""
Trade tab of the EDAP GUI: search the most profitable trade routes around the ship (similar to the trade route
search of Inara) and start one directly with Waypoint Assist.
"""

import json
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tktooltip import ToolTip

from EDlogger import logger
from EDTradeFinder import TradeFinder, route_to_waypoints, learn_timing

TIP = dict(delay=0.6, bg="#808080", fg="#FFFFFF")

SORT_KEYS = {
    "Profit per hour": 'profit_hour',
    "Profit per trip": 'profit_trip',
    "Distance between stations": 'distance',
    "Distance to start": 'dist_to_start',
}


def fmt_cr(value: float) -> str:
    v = float(value or 0)
    if abs(v) >= 1e9:
        return f"{v / 1e9:.2f} B"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.2f} M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.0f} k"
    return f"{v:.0f}"


class TradeTab:
    def __init__(self, gui, parent):
        self.gui = gui
        self.ap = gui.ed_ap
        self.parent = parent
        self.routes: list[dict] = []
        self._q = queue.Queue()
        self._busy = False
        self._sort_reverse = True
        cfg = self.ap.config

        # --- search -----------------------------------------------------------------------------------------------
        frm = ttk.LabelFrame(parent, text="TRADE ROUTE SEARCH", padding=(10, 5))
        frm.pack(fill="x", padx=10, pady=(8, 4))
        for c in (1, 3, 5):
            frm.columnconfigure(c, weight=1)

        V = tk.StringVar
        self.v_system = V()
        self.v_mode = V(value=cfg.get('TradeMode', "Round trips"))
        self.v_start = V(value=str(cfg.get('TradeSearchRadius', 50)))
        self.v_hop = V(value=str(cfg.get('TradeMaxHopDistance', 50)))
        self.v_arrival = V(value=str(cfg.get('TradeMaxArrivalLs', 5000)))
        self.v_age = V(value=str(cfg.get('TradeMaxAgeHours', 24)))
        self.v_cargo = V()
        self.v_minvol = V(value=str(cfg.get('TradeMinVolume', 0)))
        self.v_jump = V()
        self.v_pad = V(value="L")
        self.v_count = V(value=str(cfg.get('TradeCommodityCount', 50)))
        self.v_sort = V(value=cfg.get('TradeSortBy', "Profit per hour"))
        B = tk.BooleanVar
        self.v_carriers = B(value=bool(cfg.get('TradeIncludeCarriers', False)))
        self.v_megaships = B(value=bool(cfg.get('TradeIncludeMegaships', False)))
        self.v_planetary = B(value=bool(cfg.get('TradeIncludePlanetary', False)))
        self.v_settlements = B(value=bool(cfg.get('TradeIncludeSettlements', False)))

        def lbl(text, r, c, tip):
            w = ttk.Label(frm, text=text)
            w.grid(row=r, column=c, sticky="W", padx=(2, 4), pady=2)
            ToolTip(w, msg=tip, **TIP)

        def spin(var, r, c, lo, hi, inc, tip):
            w = ttk.Spinbox(frm, textvariable=var, from_=lo, to=hi, increment=inc, width=7, justify=tk.RIGHT)
            w.grid(row=r, column=c, sticky="W", pady=2)
            ToolTip(w, msg=tip, **TIP)

        lbl("Reference system:", 0, 0, "Centre of the search, usually where your ship is.")
        ttk.Entry(frm, textvariable=self.v_system, width=18).grid(row=0, column=1, columnspan=2, sticky="EW", pady=2)
        b = ttk.Button(frm, text="Current location", command=self.use_current)
        b.grid(row=0, column=3, sticky="W", padx=(6, 0), pady=2)
        ToolTip(b, msg="Your current system and the data of your ship (cargo, pad size, laden jump range).", **TIP)
        lbl("Route type:", 0, 4, "Round trips: A -> B with one commodity, B -> A with another, repeated.\n"
                                 "One way: buy at A, sell at B.")
        ttk.Combobox(frm, textvariable=self.v_mode, values=["Round trips", "One way"], width=12,
                     state="readonly").grid(row=0, column=5, sticky="W", pady=2)

        lbl("Max. to start (ly):", 1, 0, "Max. distance from the reference system to the first station.")
        spin(self.v_start, 1, 1, 0, 500, 10, "0 - 500 ly")
        lbl("Station to station (ly):", 1, 2, "Max. direct distance between the two trade stations.")
        spin(self.v_hop, 1, 3, 5, 500, 5, "5 - 500 ly")
        lbl("Max. from star (Ls):", 1, 4, "Max. distance of a station from the arrival star (long supercruise "
                                                 "costs time).")
        spin(self.v_arrival, 1, 5, 50, 1000000, 500, "Light seconds")

        lbl("Cargo (t):", 2, 0, "Cargo capacity of your ship.")
        spin(self.v_cargo, 2, 1, 1, 2000, 1, "Tons")
        lbl("Min. supply/demand:", 2, 2, "Min. stock at the seller and demand at the buyer. 0 = your cargo capacity.")
        spin(self.v_minvol, 2, 3, 0, 1000000, 100, "0 = cargo capacity")
        lbl("Max. price age (h):", 2, 4, "Ignore market data older than this.")
        spin(self.v_age, 2, 5, 1, 720, 1, "Hours")

        lbl("Landing pad:", 3, 0, "Min. landing pad size (L for large ships like the Type-9).")
        ttk.Combobox(frm, textvariable=self.v_pad, values=["S", "M", "L"], width=4, state="readonly").grid(
            row=3, column=1, sticky="W", pady=2)
        lbl("Jump range (ly):", 3, 2, "Laden jump range, for the estimate of jumps and time.")
        spin(self.v_jump, 3, 3, 1, 100, 0.5, "Light years")
        lbl("Commodities:", 3, 4, "How many commodities are searched (most valuable first). More = slower.")
        spin(self.v_count, 3, 5, 5, 150, 5, "5 - 150")

        chk = ttk.Frame(frm)
        chk.grid(row=4, column=0, columnspan=4, sticky="W", pady=(2, 0))
        for text, var, tip in (("Fleet carriers", self.v_carriers, "Include fleet carriers (prices change often, "
                                                                    "markets close)."),
                               ("Megaships", self.v_megaships, "Include megaships."),
                               ("Planetary ports", self.v_planetary, "Include stations on planets (glide and planetary "
                                                                     "landing)."),
                               ("Odyssey settlements", self.v_settlements, "Include Odyssey settlements.")):
            w = ttk.Checkbutton(chk, text=text, variable=var)
            w.pack(side="left", padx=(0, 12))
            ToolTip(w, msg=tip, **TIP)
        lbl("Sort by:", 4, 4, "Order of the results.")
        ttk.Combobox(frm, textvariable=self.v_sort, values=list(SORT_KEYS), width=13, state="readonly").grid(
            row=4, column=5, sticky="W", pady=2)

        bar = ttk.Frame(frm)
        bar.grid(row=5, column=0, columnspan=6, sticky="EW", pady=(6, 0))
        bar.columnconfigure(0, weight=1)
        self.lbl_status = ttk.Label(bar, text="Market data: Ardent Insight (EDDN, uploaded by players).",
                                    foreground="#9a9a9a", wraplength=760, justify=tk.LEFT)
        self.lbl_status.grid(row=0, column=0, sticky="W")
        self.btn_search = ttk.Button(bar, text="Search", style="Accent.TButton", command=self.search, width=14)
        self.btn_search.grid(row=0, column=1, sticky="E")

        # --- results ----------------------------------------------------------------------------------------------
        res = ttk.LabelFrame(parent, text="RESULTS", padding=(10, 5))
        res.pack(fill="both", expand=True, padx=10, pady=4)
        cols = (('from', "From (start)", 140), ('to', "To", 140), ('start', "To start", 60), ('dist', "Ly", 42),
                ('arr', "Ls", 52), ('out', "Commodity  ->", 125), ('back', "<-  Back", 125),
                ('trip', "Profit/trip", 76), ('hour', "Profit/h", 70), ('age', "Age", 42))
        self.tree = ttk.Treeview(res, columns=[c[0] for c in cols], show="headings", height=8, selectmode="browse")
        for key, title, width in cols:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by_column(k))
            self.tree.column(key, width=width, anchor="w" if key in ('from', 'to', 'out', 'back') else "e",
                             stretch=key in ('from', 'to', 'out', 'back'))
        vsb = ttk.Scrollbar(res, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_details())
        self.tree.bind("<Double-1>", lambda e: self.start_route())

        # --- details + actions ------------------------------------------------------------------------------------
        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", padx=10, pady=(2, 8))
        bottom.columnconfigure(0, weight=1)
        self.lbl_details = ttk.Label(bottom, text="Select a route.", justify=tk.LEFT, wraplength=700)
        self.lbl_details.grid(row=0, column=0, rowspan=2, sticky="W")
        self.btn_save = ttk.Button(bottom, text="Save as waypoint file", command=self.save_route)
        self.btn_save.grid(row=0, column=1, sticky="EW", padx=4, pady=2)
        ToolTip(self.btn_save, msg="Writes the route into the 'waypoints' folder and loads it in the Waypoints tab.",
                **TIP)
        self.btn_start = ttk.Button(bottom, text="Start trade route", style="Accent.TButton",
                                    command=self.start_route)
        self.btn_start.grid(row=1, column=1, sticky="EW", padx=4, pady=2)
        ToolTip(self.btn_start, msg="Saves the route and starts Waypoint Assist: fly to the start station, buy, "
                                    "fly, sell, (buy, fly back, sell, repeat) - until you stop it.", **TIP)

        self.use_current(quiet=True)
        parent.after(200, self._poll)

    # ------------------------------------------------------------------------------------------------------------
    def _ship(self) -> dict:
        return getattr(self.ap.jn, 'ship', {}) or {}

    def use_current(self, quiet=False):
        ship = self._ship()
        if ship.get('cur_star_system'):
            self.v_system.set(ship.get('cur_star_system'))
        if ship.get('cargo_capacity'):
            self.v_cargo.set(str(ship.get('cargo_capacity')))
        try:
            from EDAP_data import ship_size_map
            size = ship_size_map.get(ship.get('type'), '')
            if size in ('S', 'M', 'L'):
                self.v_pad.set(size)
        except Exception:
            pass
        jr = self._jump_range_from_journal()
        if jr:
            self.v_jump.set(f"{jr:.1f}")
        elif not self.v_jump.get():
            self.v_jump.set("15")
        if not self.v_cargo.get():
            self.v_cargo.set("100")
        if not quiet:
            self.lbl_status.configure(text=f"Reference {self.v_system.get()}, cargo {self.v_cargo.get()} t, pad "
                                           f"{self.v_pad.get()}, jump range {self.v_jump.get()} ly.")

    def _jump_range_from_journal(self) -> float | None:
        """ Longest recent jump of this ship with a similar load (laden jump range). """
        try:
            from EDFuelPlanner import collect_jump_samples
            samples, ship_id = collect_jump_samples(os.path.dirname(self.ap.jn.current_log), max_files=15)
            samples = [s for s in samples if ship_id is None or s['ship_id'] == ship_id]
            if not samples:
                return None
            cargo = max(s['cargo'] for s in samples)
            laden = [s['dist'] for s in samples if s['cargo'] >= 0.8 * cargo] or [s['dist'] for s in samples]
            return max(laden)
        except Exception as e:
            logger.debug(f"trade tab: jump range: {e}")
            return None

    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _num(var, default, typ=float):
        try:
            return typ(float(str(var.get()).replace(',', '.')))
        except ValueError:
            return default

    def search(self):
        if self._busy:
            return
        system = self.v_system.get().strip()
        if not system:
            messagebox.showinfo("Trade", "Enter the reference system (or click 'Current location').")
            return
        params = dict(ref_system=system,
                      cargo=self._num(self.v_cargo, 100, int),
                      max_start_distance=self._num(self.v_start, 50),
                      max_hop_distance=self._num(self.v_hop, 50),
                      min_volume=self._num(self.v_minvol, 0, int),
                      max_arrival_ls=self._num(self.v_arrival, 5000),
                      max_age_hours=self._num(self.v_age, 24),
                      min_pad={'S': 1, 'M': 2, 'L': 3}.get(self.v_pad.get(), 3),
                      carriers=bool(self.v_carriers.get()), megaships=bool(self.v_megaships.get()),
                      planetary=bool(self.v_planetary.get()), settlements=bool(self.v_settlements.get()),
                      round_trips=self.v_mode.get() == "Round trips",
                      commodity_count=self._num(self.v_count, 50, int),
                      jump_range=self._num(self.v_jump, 15),
                      secs_per_jump=float(self.ap.config.get('TradeSecsPerJump', 75)),
                      secs_station=float(self.ap.config.get('TradeSecsPerStation', 340)))
        cfg = self.ap.config
        cfg.update({'TradeSearchRadius': params['max_start_distance'], 'TradeMaxHopDistance': params['max_hop_distance'],
                    'TradeMaxArrivalLs': params['max_arrival_ls'], 'TradeMaxAgeHours': params['max_age_hours'],
                    'TradeMinVolume': params['min_volume'], 'TradeCommodityCount': params['commodity_count'],
                    'TradeIncludeCarriers': params['carriers'], 'TradeIncludeMegaships': params['megaships'],
                    'TradeIncludePlanetary': params['planetary'], 'TradeIncludeSettlements': params['settlements'],
                    'TradeMode': self.v_mode.get(), 'TradeSortBy': self.v_sort.get()})

        self._busy = True
        self.btn_search.configure(state="disabled", text="Searching...")
        self.tree.delete(*self.tree.get_children())
        self.routes = []
        self.lbl_details.configure(text="")

        journal_dir = os.path.dirname(self.ap.jn.current_log) if getattr(self.ap.jn, 'current_log', None) else None

        def worker():
            try:
                # Times of your own recent flights (per jump, per station) for the profit per hour
                timing = learn_timing(journal_dir) if journal_dir else None
                if timing:
                    params['secs_per_jump'] = timing['secs_per_jump']
                    params['secs_station'] = timing['secs_station']
                    self._q.put(('progress', f"Times of your last flights: {timing['secs_per_jump']:.0f} s per jump, "
                                             f"{timing['secs_station'] / 60:.1f} min per station."))
                self._timing = (params['secs_per_jump'], params['secs_station'], bool(timing))
                finder = TradeFinder(progress=lambda m: self._q.put(('progress', m)))
                routes = finder.find_routes(**params)
                skipped = ", ".join(f"{k} {v}" for k, v in sorted(finder.rejected.items()))
                self._q.put(('done', (routes, skipped)))
            except Exception as e:
                logger.exception("trade search failed")
                self._q.put(('error', str(e)))

        threading.Thread(target=worker, name="TradeSearch", daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, body = self._q.get_nowait()
                if kind == 'progress':
                    self.lbl_status.configure(text=body)
                elif kind == 'done':
                    routes, skipped = body
                    self._busy = False
                    self.btn_search.configure(state="normal", text="Search")
                    self.routes = routes
                    self.fill_tree()
                    msg = f"{len(routes)} routes found." if routes else \
                        "No profitable route found. Try larger distances, an older price age or fewer filters."
                    tm = getattr(self, '_timing', None)
                    if tm:
                        msg += (f"  Time: {tm[0]:.0f} s/jump, {tm[1] / 60:.1f} min/station"
                                f"{' (from your journals)' if tm[2] else ''}.")
                    if skipped:
                        msg += f"  Skipped: {skipped}."
                    self.lbl_status.configure(text=msg)
                elif kind == 'error':
                    self._busy = False
                    self.btn_search.configure(state="normal", text="Search")
                    self.lbl_status.configure(text=f"Search failed: {body}")
        except queue.Empty:
            pass
        self.parent.after(200, self._poll)

    def fill_tree(self, key: str | None = None):
        key = key or SORT_KEYS.get(self.v_sort.get(), 'profit_hour')
        reverse = key not in ('distance', 'dist_to_start')
        self.routes.sort(key=lambda r: r.get(key) or 0, reverse=reverse)
        self._insert_rows()

    def sort_by_column(self, col: str):
        key = {'from': 'start_station', 'to': 'station', 'start': 'dist_to_start', 'dist': 'distance',
               'arr': 'arrival_ls', 'out': 'out_total', 'back': 'back_total', 'trip': 'profit_trip',
               'hour': 'profit_hour', 'age': 'age_h'}[col]
        self._sort_reverse = not self._sort_reverse
        self.routes.sort(key=lambda r: (r.get(key) if r.get(key) is not None else 0), reverse=self._sort_reverse)
        self._insert_rows()

    def _insert_rows(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.routes):
            out = f"{r['out_name']} +{r['out_profit']:,}"
            if r.get('round_trip') and r.get('back_name'):
                back = f"{r['back_name']} +{r['back_profit']:,}"
            elif r.get('round_trip'):
                back = "- (back empty)"
            else:
                back = "(one way)"
            self.tree.insert('', 'end', iid=str(i), values=(
                f"{r['start_station']} ({r['start_system']})", f"{r['station']} ({r['system']})",
                f"{r['dist_to_start']:.0f}", f"{r['distance']:.0f}", f"{max(r['start_arrival_ls'], r['arrival_ls']):.0f}",
                out, back, fmt_cr(r['profit_trip']), fmt_cr(r['profit_hour']),
                f"{r['age_h']:.0f}h" if r.get('age_h') is not None else "?"))
        if self.routes:
            self.tree.selection_set('0')

    def selected(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self.routes[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def show_details(self):
        r = self.selected()
        if not r:
            self.lbl_details.configure(text="Select a route.")
            return
        mins = r['trip_secs'] / 60.0
        txt = (f"Start: {r['start_station']} ({r['start_system']}, {r['dist_to_start']:.0f} ly away, "
               f"{r['start_arrival_ls']:.0f} Ls, {r['start_type'] or '?'}). "
               f"Buy {r['out_amount']} t {r['out_name']} at {r['out_buy']:,} cr (supply {r['out_supply']:,}).\n"
               f"Sell at {r['station']} ({r['system']}, {r['distance']:.0f} ly, ~{r['jumps']} jumps, "
               f"{r['arrival_ls']:.0f} Ls, {r['station_type'] or '?'}) for {r['out_sell']:,} cr "
               f"(demand {r['out_demand']:,}): +{fmt_cr(r['out_total'])}.\n")
        if r.get('round_trip') and r.get('back_name'):
            txt += (f"Back: buy {r['back_amount']} t {r['back_name']} at {r['back_buy']:,} cr, sell at "
                    f"{r['start_station']} for {r['back_sell']:,} cr: +{fmt_cr(r['back_total'])}.\n")
        elif r.get('round_trip'):
            txt += "Back: no profitable commodity, the ship flies back empty.\n"
        txt += (f"{'Round trip' if r.get('round_trip') else 'Trip'} ~{mins:.0f} min, {fmt_cr(r['profit_trip'])} cr, "
                f"~{fmt_cr(r['profit_hour'])} cr/h. Capital needed: {fmt_cr(r['capital_needed'])} cr.")
        self.lbl_details.configure(text=txt)

    # ------------------------------------------------------------------------------------------------------------
    def save_route(self, route: dict | None = None) -> str | None:
        r = route or self.selected()
        if not r:
            messagebox.showinfo("Trade", "Select a route first.")
            return None
        name = re.sub(r'[^A-Za-z0-9]+', '_', f"trade_{r['start_station']}_{r['station']}").strip('_')[:80] + ".json"
        os.makedirs('./waypoints', exist_ok=True)
        path = os.path.join('./waypoints', name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(route_to_waypoints(r), f, indent=4)
        try:
            if self.gui.waypoint_editor_tab is not None:
                self.gui.waypoint_editor_tab.editor_load_waypoint_file(os.path.abspath(path))
            else:
                self.ap.waypoint.load_waypoint_file(path)
        except Exception as e:
            logger.warning(f"trade tab: loading {path}: {e}")
            self.ap.waypoint.load_waypoint_file(path)
        self.gui.log_msg(f"Trade route saved: waypoints/{name}")
        return path

    def start_route(self):
        r = self.selected()
        if not r:
            messagebox.showinfo("Trade", "Select a route first.")
            return
        if self.gui._assist_running():
            messagebox.showinfo("Trade", "An assist is running. Stop it first.")
            return
        if r.get('round_trip'):
            what = (f"{r['start_station']} ({r['start_system']})  <->  {r['station']} ({r['system']})\n"
                    f"Buy {r['out_name']}, sell it, "
                    f"{'bring back ' + r['back_name'] if r.get('back_name') else 'fly back empty'}. "
                    f"Repeated until you stop it.\n\n"
                    f"~{fmt_cr(r['profit_trip'])} cr per round trip.")
        else:
            what = (f"{r['start_station']} ({r['start_system']})  ->  {r['station']} ({r['system']})\n"
                    f"Buy {r['out_name']} and sell it (one way).\n\n~{fmt_cr(r['profit_trip'])} cr.")
        dist = f"\nThe start station is {r['dist_to_start']:.0f} ly away." if r['dist_to_start'] > 0.5 else ""
        if not messagebox.askyesno("Start trade route", f"Start Waypoint Assist with this route?\n\n{what}{dist}"):
            return
        if not self.save_route(r):
            return
        # Start Waypoint Assist like ticking the checkbox on the main tab
        self.gui.checkboxvar['Waypoint Assist'].set(1)
        self.gui.check_cb('Waypoint Assist')
        try:
            self.gui._nb.select(0)
        except Exception:
            pass
