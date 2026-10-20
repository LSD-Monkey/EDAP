from __future__ import annotations

"""
Trade tab of the EDAP GUI: find the best round trips from a station (similar to the Inara trade routes) and start
one directly with Waypoint Assist (A -> B -> A, REPEAT).
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
from EDTradeFinder import TradeFinder, route_to_waypoints

TIP = dict(delay=0.6, bg="#808080", fg="#FFFFFF")

SORT_KEYS = {
    "Profit per hour": 'profit_hour',
    "Profit per trip": 'profit_trip',
    "Distance": 'distance',
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
        frm = ttk.LabelFrame(parent, text="SEARCH ROUND TRIPS  (start station -> best station -> back)", padding=(10, 5))
        frm.pack(fill="x", padx=10, pady=(8, 4))
        for c in (1, 3, 5, 7):
            frm.columnconfigure(c, weight=1)

        self.v_system = tk.StringVar()
        self.v_station = tk.StringVar()
        self.v_cargo = tk.StringVar()
        self.v_jump = tk.StringVar()
        self.v_dist = tk.StringVar(value=str(cfg.get('TradeMaxDistance', 60)))
        self.v_arrival = tk.StringVar(value=str(cfg.get('TradeMaxArrivalLs', 5000)))
        self.v_age = tk.StringVar(value=str(cfg.get('TradeMaxAgeHours', 24)))
        self.v_pad = tk.StringVar(value="L")
        self.v_planetary = tk.BooleanVar(value=bool(cfg.get('TradeIncludePlanetary', False)))
        self.v_sort = tk.StringVar(value=cfg.get('TradeSortBy', "Profit per hour"))

        def lbl(text, r, c, tip):
            w = ttk.Label(frm, text=text)
            w.grid(row=r, column=c, sticky="W", padx=(2, 4), pady=2)
            ToolTip(w, msg=tip, **TIP)

        lbl("Start system:", 0, 0, "System of the start station (where you buy first).")
        ttk.Entry(frm, textvariable=self.v_system, width=24).grid(row=0, column=1, columnspan=3, sticky="EW", pady=2)
        lbl("Station:", 0, 4, "Start station. Docked there, its market is read from Market.json (exact prices).")
        ttk.Entry(frm, textvariable=self.v_station, width=24).grid(row=0, column=5, columnspan=2, sticky="EW",
                                                                    pady=2)
        b = ttk.Button(frm, text="Current station", command=self.use_current)
        b.grid(row=0, column=7, sticky="EW", padx=(6, 0), pady=2)
        ToolTip(b, msg="Fill in the system/station you are at and the data of your ship.", **TIP)

        def spin(var, r, c, frm_, to_, inc, w=7):
            s = ttk.Spinbox(frm, textvariable=var, from_=frm_, to=to_, increment=inc, width=w, justify=tk.RIGHT)
            s.grid(row=r, column=c, sticky="W", pady=2)
            return s

        lbl("Max. distance (ly):", 1, 0, "Max. direct distance between the two stations.")
        spin(self.v_dist, 1, 1, 5, 500, 5)
        lbl("Jump range (ly):", 1, 2, "Laden jump range of your ship, used to estimate the jumps and the time.")
        spin(self.v_jump, 1, 3, 1, 100, 0.5)
        lbl("Cargo (t):", 1, 4, "Cargo capacity of your ship.")
        spin(self.v_cargo, 1, 5, 1, 2000, 1)
        lbl("Pad:", 1, 6, "Min. landing pad size of the stations (L for large ships like the Type-9).")
        ttk.Combobox(frm, textvariable=self.v_pad, values=["S", "M", "L"], width=4, state="readonly").grid(
            row=1, column=7, sticky="W", pady=2)

        lbl("Max. arrival (Ls):", 2, 0, "Max. distance of the station from the arrival star (supercruise time).")
        spin(self.v_arrival, 2, 1, 50, 500000, 500, 8)
        lbl("Max. data age (h):", 2, 2, "Ignore prices older than this (market data from EDDN via Ardent Insight).")
        spin(self.v_age, 2, 3, 1, 720, 1)
        lbl("Sort by:", 2, 4, "Order of the results.")
        ttk.Combobox(frm, textvariable=self.v_sort, values=list(SORT_KEYS), width=15, state="readonly").grid(
            row=2, column=5, sticky="W", pady=2)
        cb = ttk.Checkbutton(frm, text="Planetary", variable=self.v_planetary)
        cb.grid(row=2, column=6, sticky="W", pady=2)
        ToolTip(cb, msg="Include stations on planets (glide and planetary landing).", **TIP)
        self.btn_search = ttk.Button(frm, text="Search", style="Accent.TButton", command=self.search)
        self.btn_search.grid(row=2, column=7, sticky="EW", padx=(6, 0), pady=2)

        self.lbl_status = ttk.Label(frm, text="Market data: Ardent Insight (EDDN). Docked at the start station, "
                                              "its own Market.json is used.", foreground="#9a9a9a")
        self.lbl_status.grid(row=3, column=0, columnspan=8, sticky="W", pady=(4, 0))

        # --- results ----------------------------------------------------------------------------------------------
        res = ttk.LabelFrame(parent, text="ROUND TRIPS", padding=(10, 5))
        res.pack(fill="both", expand=True, padx=10, pady=4)
        cols = (('to', "Destination", 175), ('dist', "Ly", 50), ('jumps', "Jumps", 50), ('arr', "Arrival Ls", 72),
                ('out', "Buy here -> sell there", 165), ('back', "Bring back", 150), ('trip', "Profit/trip", 85),
                ('hour', "Profit/h", 80), ('age', "Age h", 50))
        self.tree = ttk.Treeview(res, columns=[c[0] for c in cols], show="headings", height=9, selectmode="browse")
        for key, title, width in cols:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by_column(k))
            self.tree.column(key, width=width, anchor="w" if key in ('to', 'out', 'back') else "e", stretch=key in
                             ('to', 'out', 'back'))
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
        self.lbl_details = ttk.Label(bottom, text="Select a route.", justify=tk.LEFT, wraplength=720)
        self.lbl_details.grid(row=0, column=0, rowspan=2, sticky="W")
        self.btn_save = ttk.Button(bottom, text="Save as waypoint file", command=self.save_route)
        self.btn_save.grid(row=0, column=1, sticky="EW", padx=4, pady=2)
        ToolTip(self.btn_save, msg="Writes the route (start station, destination, REPEAT) into the 'waypoints' "
                                   "folder and loads it in the Waypoints tab.", **TIP)
        self.btn_start = ttk.Button(bottom, text="Start trade route", style="Accent.TButton",
                                    command=self.start_route)
        self.btn_start.grid(row=1, column=1, sticky="EW", padx=4, pady=2)
        ToolTip(self.btn_start, msg="Saves the route and starts Waypoint Assist: buy, fly, sell, buy, fly back, "
                                    "sell, ... until you stop it.", **TIP)

        self.use_current(quiet=True)
        parent.after(200, self._poll)

    # ------------------------------------------------------------------------------------------------------------
    def _ship(self) -> dict:
        return getattr(self.ap.jn, 'ship', {}) or {}

    def use_current(self, quiet=False):
        ship = self._ship()
        if ship.get('cur_star_system'):
            self.v_system.set(ship.get('cur_star_system'))
        if ship.get('cur_station'):
            self.v_station.set(ship.get('cur_station'))
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
        if not quiet:
            self.lbl_status.configure(text=f"Using {self.v_station.get()} / {self.v_system.get()}, cargo "
                                           f"{self.v_cargo.get()} t, jump range {self.v_jump.get()} ly.")

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

    def _local_market(self, system: str, station: str) -> dict | None:
        """ Market.json if it belongs to the start station. """
        try:
            from MarketParser import MarketParser
            data = MarketParser().get_market_data()
            if data and str(data.get('StationName', '')).upper() == station.upper() and \
                    str(data.get('StarSystem', '')).upper() == system.upper():
                return data
        except Exception as e:
            logger.debug(f"trade tab: Market.json: {e}")
        return None

    # ------------------------------------------------------------------------------------------------------------
    def _num(self, var, default, typ=float):
        try:
            return typ(float(str(var.get()).replace(',', '.')))
        except ValueError:
            return default

    def search(self):
        if self._busy:
            return
        system = self.v_system.get().strip()
        station = self.v_station.get().strip()
        if not system or not station:
            messagebox.showinfo("Trade", "Enter the start system and station (or click 'Current station').")
            return
        params = dict(start_system=system, start_station=station,
                      cargo=self._num(self.v_cargo, 100, int),
                      min_pad={'S': 1, 'M': 2, 'L': 3}.get(self.v_pad.get(), 3),
                      max_distance=self._num(self.v_dist, 60),
                      max_arrival_ls=self._num(self.v_arrival, 5000),
                      max_age_hours=self._num(self.v_age, 24),
                      include_planetary=bool(self.v_planetary.get()),
                      jump_range=self._num(self.v_jump, 15),
                      secs_per_jump=float(self.ap.config.get('TradeSecsPerJump', 110)))
        cfg = self.ap.config
        cfg['TradeMaxDistance'] = params['max_distance']
        cfg['TradeMaxArrivalLs'] = params['max_arrival_ls']
        cfg['TradeMaxAgeHours'] = params['max_age_hours']
        cfg['TradeIncludePlanetary'] = params['include_planetary']
        cfg['TradeSortBy'] = self.v_sort.get()
        local = self._local_market(system, station)
        params['local_market'] = local

        self._busy = True
        self.btn_search.configure(state="disabled", text="Searching...")
        self.tree.delete(*self.tree.get_children())
        self.routes = []

        def worker():
            try:
                finder = TradeFinder(progress=lambda m: self._q.put(('progress', m)))
                routes = finder.find_round_trips(**params)
                self._q.put(('done', routes))
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
                    self._busy = False
                    self.btn_search.configure(state="normal", text="Search")
                    self.routes = body
                    self.fill_tree()
                    self.lbl_status.configure(text=f"{len(body)} round trips found." if body else
                                              "No profitable round trip found. Try a larger distance or data age.")
                elif kind == 'error':
                    self._busy = False
                    self.btn_search.configure(state="normal", text="Search")
                    self.lbl_status.configure(text=f"Search failed: {body}")
        except queue.Empty:
            pass
        self.parent.after(200, self._poll)

    def fill_tree(self, key: str | None = None):
        key = key or SORT_KEYS.get(self.v_sort.get(), 'profit_hour')
        reverse = key not in ('distance',)
        self.routes.sort(key=lambda r: r.get(key) or 0, reverse=reverse)
        self._insert_rows()

    def sort_by_column(self, col: str):
        key = {'to': 'station', 'dist': 'distance', 'jumps': 'jumps', 'arr': 'arrival_ls', 'out': 'out_total',
               'back': 'back_total', 'trip': 'profit_trip', 'hour': 'profit_hour', 'age': 'out_age_h'}[col]
        self._sort_reverse = not self._sort_reverse
        self.routes.sort(key=lambda r: (r.get(key) if r.get(key) is not None else 0), reverse=self._sort_reverse)
        self._insert_rows()

    def _insert_rows(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.routes):
            ages = [a for a in (r.get('out_age_h'), r.get('back_age_h')) if a is not None]
            out = f"{r['out_name']}  +{r['out_profit']:,}/t"
            back = f"{r['back_name']}  +{r['back_profit']:,}/t" if r.get('back_name') else "- (fly back empty)"
            self.tree.insert('', 'end', iid=str(i), values=(
                f"{r['station']} ({r['system']})", f"{r['distance']:.0f}", r['jumps'], f"{r['arrival_ls']:.0f}",
                out, back, fmt_cr(r['profit_trip']), fmt_cr(r['profit_hour']),
                f"{max(ages):.0f}" if ages else "?"))
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
        txt = (f"{r['start_station']}: buy {r['out_amount']} t {r['out_name']} at {r['out_buy']:,} cr  ->  "
               f"{r['station']} ({r['system']}, {r['distance']:.0f} ly, ~{r['jumps']} jumps, {r['arrival_ls']:.0f} Ls): "
               f"sell at {r['out_sell']:,} cr (+{fmt_cr(r['out_total'])}).\n")
        if r.get('back_name'):
            txt += (f"Back: buy {r['back_amount']} t {r['back_name']} at {r['back_buy']:,} cr, sell at "
                    f"{r['start_station']} for {r['back_sell']:,} cr (+{fmt_cr(r['back_total'])}).\n")
        else:
            txt += "Back: no profitable commodity, the ship flies back empty.\n"
        txt += (f"Round trip ~{mins:.0f} min, {fmt_cr(r['profit_trip'])} cr per trip, ~{fmt_cr(r['profit_hour'])} cr/h. "
                f"Capital needed: {fmt_cr(r['capital_needed'])} cr.")
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
        back = f"and bring back {r['back_name']}" if r.get('back_name') else "and fly back empty"
        if not messagebox.askyesno("Start trade route",
                                   f"Start Waypoint Assist with this loop?\n\n"
                                   f"{r['start_station']} ({r['start_system']})  <->  {r['station']} ({r['system']})\n"
                                   f"Buy {r['out_name']}, {back}.\n\n"
                                   f"~{fmt_cr(r['profit_trip'])} cr per round trip. It runs until you stop it."):
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
