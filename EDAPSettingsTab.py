from __future__ import annotations

"""
Settings tab of the EDAP GUI.

All AP.json settings shown in the GUI are described once in SETTINGS (section, label, type, range, tooltip). The tab
is built from this table: grouped sections, a search field, tooltips, a 'changed' marker, 'Reset section' to the
defaults and immediate apply (the change is active at once, 'Save' writes AP.json).
"""

import os
import tkinter as tk
from tkinter import ttk

from tktooltip import ToolTip

TIP_STYLE = dict(delay=0.6, bg="#808080", fg="#FFFFFF")

# type: 'bool', 'int', 'float', 'str', 'choice'
# restart: the change needs a restart of EDAP
SETTINGS: list[dict] = [
    # --- General ----------------------------------------------------------------------------------------------
    dict(section="General", key="VoiceEnable", label="Voice output", type="bool",
         tip="EDAP speaks its status messages (Windows text to speech)."),
    dict(section="General", key="PauseWhenUnfocused", label="Pause keys while Elite is not active", type="bool",
         tip="No key is sent while another window (e.g. EDAP, Discord) is in front. EDAP continues when you click "
             "into Elite again. Strongly recommended."),
    dict(section="General", key="GameConnectionCheck", label="Stop on connection loss / main menu", type="bool",
         tip="Stops every assist when 'CONNECTION ERROR' is on screen, the game is in the main menu or was closed. "
             "Without it EDAP keeps pressing keys for hours after a disconnect."),
    dict(section="General", key="AutomaticLogout", label="Log out when the route is complete", type="bool",
         tip="FSD Route Assist: log out of the game after reaching the destination."),
    dict(section="General", key="Language", label="Language (HUD texts)", type="choice", choices="locales",
         restart=True, tip="Language of the game. Used to recognise HUD texts by OCR. Needs a restart."),

    # --- Hotkeys ----------------------------------------------------------------------------------------------
    dict(section="Hotkeys", key="HotkeysEnable", label="Enable global hotkeys", type="bool",
         tip="Hotkeys also work while Elite is in front. Use keys that are not bound in Elite."),
    dict(section="Hotkeys", key="HotKey_StopAllAssists", label="Stop all assists", type="str",
         tip="Key name as used by the python 'keyboard' package, e.g. end, home, ins, pgup, f9, ctrl+shift+s."),
    dict(section="Hotkeys", key="HotKey_StartFSD", label="Start FSD Route Assist", type="str",
         tip="Key name, e.g. home."),
    dict(section="Hotkeys", key="HotKey_StartSC", label="Start Supercruise Assist", type="str",
         tip="Key name, e.g. ins."),
    dict(section="Hotkeys", key="HotKey_StartRobigo", label="Start Robigo Assist", type="str",
         tip="Key name, e.g. pgup."),

    # --- Waypoint Assist ------------------------------------------------------------------------------------------
    dict(section="Waypoint Assist", key="WaypointAutoRestarts", label="Auto-restarts after an error", type="int",
         min=0, max=20, tip="Waypoint Assist restarts itself this often in a row after an error (e.g. alignment "
                            "failed). The counter is reset after 20 minutes without error. 0 = never restart."),
    dict(section="Waypoint Assist", key="WaypointRestartDelay", label="Wait before restart / retry (s)",
         type="int", min=0, max=300, tip="Seconds to wait before an auto-restart or a new attempt to reach "
                                         "a station."),
    dict(section="Waypoint Assist", key="WaypointStationRetries", label="Attempts to reach a station", type="int",
         min=1, max=20, tip="Waypoint Assist stops after this many failed attempts in a row to reach a station."),
    dict(section="Waypoint Assist", key="WaypointNeverStop", label="Fail-safe: never stop", type="bool",
         tip="Waypoint Assist does not stop on errors: 1) jump to a neighbour system and back, 2) leave the system "
             "and wait, 3) start another trade route. Low fuel: fuel stop at the nearest station. Main menu / "
             "connection lost: wait until the game is playable again. Only STOP stops it."),
    dict(section="Waypoint Assist", key="AutoReconnect", label="Fail-safe: reconnect after connection error",
         type="bool", tip="CONNECTION ERROR / main menu: press OK, CONTINUE in the main menu, choose the game mode and "
                          "load the game again (repeated with growing pauses while the servers are down). Off: only "
                          "wait until the game is playable again."),
    dict(section="Waypoint Assist", key="ReconnectMode", label="Fail-safe: game mode for reconnect", type="choice",
         choices=["Solo", "Open"], tip="Game mode chosen when reconnecting."),
    dict(section="Waypoint Assist", key="WaypointRecoveryJumps", label="Fail-safe: jumps out and back", type="int",
         min=1, max=10, tip="How often the fail-safe jumps to a neighbour system and back before the long wait."),
    dict(section="Waypoint Assist", key="WaypointRecoveryWait", label="Fail-safe: wait (min)", type="int",
         min=1, max=240, tip="Minutes to wait outside the system when jumping out and back did not help."),
    dict(section="Waypoint Assist", key="WaypointRecoveryNewRoute", label="Fail-safe: start another trade route",
         type="bool", tip="Still failing after the wait: search trade routes around the ship with the Trade tab "
                          "filters and start the best one without the stations of the failed route."),
    dict(section="Waypoint Assist", key="RefuelStopPercent", label="Fuel stop below (%)", type="int",
         min=5, max=80, tip="With the fail-safe on: below this fuel level (or if the fuel check says the route can "
                            "not be flown) the jumps stop and the ship docks at the nearest station with a fitting "
                            "pad to refuel, then continues."),
    dict(section="Waypoint Assist", key="TradePreSellMinTons", label="Sell other cargo first above (t)",
         type="int", min=0, max=2000, tip="Starting a trade route with more than this many tons on board that the "
                                          "route does not sell: fly to the most profitable station nearby (Trade tab "
                                          "filters), sell it, then start the route. 0 = off."),
    dict(section="Waypoint Assist", key="SCEngageTimeout", label="Max. time mass locked (s)", type="int",
         min=30, max=600, tip="Entering supercruise is given up after this time mass locked. A FSD cooldown is "
                              "waited for, 'Supercruise' is pressed up to 4 times. Then the station is tried again "
                              "(see 'Attempts to reach a station') and Waypoint Assist stops instead of waiting forever."),
    dict(section="Waypoint Assist", key="TradeBuyAttempts", label="Attempts to buy a commodity", type="int",
         min=1, max=5, tip="If a purchase is not confirmed (cargo unchanged), the market is left and entered again "
                           "and the purchase is tried again, up to this many attempts. Then Waypoint Assist "
                           "stops, still docked."),
    dict(section="Waypoint Assist", key="FuelRouteCheck", label="Check fuel for the route", type="bool",
         tip="Ships without fuel scoop: before jumping, the fuel for the plotted route is estimated from your last "
             "jumps (same ship, similar cargo). Stops if it is not enough, warns if it will be tight."),

    # --- Supercruise Assist -----------------------------------------------------------------------------------
    dict(section="Supercruise Assist", key="SCAssistAlign", label="Align to the target after activating",
         type="bool", tip="Points the ship to the destination with the compass before the in-game SCA flies. "
                          "Afterwards the throttle is set to 50 %."),
    dict(section="Supercruise Assist", key="SCAssistCheckActiveOCR", label="Check 'SUPERCRUISE ASSIST ACTIVE'",
         type="bool", tip="Reads the HUD text to see if the SCA is still active and re-activates it if not."),
    dict(section="Supercruise Assist", key="SCAssistFallbackManual", label="Fallback: EDAP steers itself",
         type="bool", tip="If the in-game SCA cannot be activated, EDAP steers to the target itself "
                          "(old method, needs a good RPY tuning)."),
    dict(section="Supercruise Assist", key="SCAssistStallTime", label="No progress after (s)", type="int",
         min=0, max=600, tip="If the distance to the target does not change for this long: 1st align + 50 % "
                             "throttle, 2nd re-activate the SCA, 3rd give up. 0 = off."),
    dict(section="Supercruise Assist", key="SCAssistNoLOSEscapeTime", label="Line of sight escape (s)",
         type="int", min=5, max=120, tip="Target behind a planet ('MOVE TO OBTAIN LINE OF SIGHT'): pitch up 90° "
                                         "and fly this long, then re-activate the SCA."),
    dict(section="Supercruise Assist", key="SCStarAheadPercent", label="Star ahead: avoid at (% of view)",
         type="int", min=0, max=60, tip="If a star covers this much of the view ahead (centre of the screen) "
                                        "during Supercruise Assist, EDAP pitches up and flies the 'Line of sight "
                                        "escape' time, then re-activates the SCA. Prevents the emergency drop at "
                                        "a star that lies between the ship and the station. 0 = off."),
    dict(section="Supercruise Assist", key="SCAssistMaxActivations", label="Max. (re-)activations", type="int",
         min=1, max=20, tip="How often the SCA is (re-)activated for one destination before giving up."),
    dict(section="Supercruise Assist", key="SCAssistTimeout", label="Timeout (s)", type="int", min=0, max=14400,
         step=60, tip="Max. time to reach the destination. 0 = no limit."),

    # --- Docking & departure ------------------------------------------------------------------------------------
    dict(section="Docking & Departure", key="DockApproachTime", label="Max. approach at 100 % (s)",
         type="int", min=0, max=120, tip="Docking is requested right after the drop and again every few seconds "
                                         "while 'too far away'. After this time at 100 % the throttle goes to 50 % "
                                         "(speed limit in the no-fire zone)."),
    dict(section="Docking & Departure", key="PlotRouteWhileUndocking", label="Plot the route while undocking",
         type="bool", tip="Start the launch first and plot the route in the galaxy map while the docking computer "
                          "flies out of the station (saves ~25 s per station)."),
    dict(section="Docking & Departure", key="PreRollAfterUndock", label="Roll to the target while mass locked",
         type="bool", tip="While boosting away from the station: roll so the next target is straight above or "
                          "below. Then only a pitch (fast) is needed in supercruise."),
    dict(section="Docking & Departure", key="DockingRetries", label="Docking request attempts", type="int",
         min=1, max=60, tip="How often docking is requested (at least 8 are used)."),
    dict(section="Docking & Departure", key="WaitForAutoDockTimer", label="Wait for auto-dock (s)", type="int",
         min=30, max=900, step=10, tip="After docking was granted: max. time for the docking computer to land."),
    dict(section="Docking & Departure", key="FCDepartureTime", label="Fleet carrier departure (s)", type="float",
         min=0, max=60, step=0.5, tip="Extra time to fly away from a fleet carrier before entering supercruise."),
    dict(section="Docking & Departure", key="FCDepartureAngle", label="Fleet carrier pitch up (°)", type="float",
         min=0, max=90, step=5, tip="Pitch up when leaving a fleet carrier."),
    dict(section="Docking & Departure", key="OCDepartureAngle", label="Construction site pitch up (°)",
         type="float", min=0, max=90, step=5, tip="Pitch up when leaving an orbital construction site."),

    # --- Navigation & jumping -----------------------------------------------------------------------------------
    dict(section="Navigation & Jumping", key="NavAlignTries", label="Align attempts", type="int", min=1, max=20,
         tip="How many attempts to align to the next system before the jump."),
    dict(section="Navigation & Jumping", key="JumpTries", label="Jump attempts", type="int", min=1, max=20,
         tip="How many attempts to jump."),
    dict(section="Navigation & Jumping", key="SunBrightThreshold", label="Sun brightness threshold", type="int",
         min=0, max=255, step=5, tip="Brightness (0-255) above which the screen centre is seen as a star "
                                     "(sun avoidance). Higher = less sensitive."),
    dict(section="Navigation & Jumping", key="GalMap_SystemSelectDelay", label="Galaxy map select delay (s)",
         type="float", min=0, max=5, step=0.1, tip="Wait in the galaxy map before the system is selected. "
                                                    "Increase on slow PCs."),
    dict(section="Navigation & Jumping", key="FSDChargeWhileAligning", label="Charge the FSD while aligning",
         type="bool", tip="Start the FSD charge (~15 s) before the alignment to the next system. The charged FSD "
                          "waits until the ship points at the target, then jumps."),
    dict(section="Navigation & Jumping", key="StarPassTimeNoScoop", label="Fly past the star, no scoop (s)",
         type="float", min=0, max=30, step=1, tip="After a jump: seconds at 100 % past the arrival star for ships "
                                                  "without fuel scoop (with scoop: 17 s). Increase if the next "
                                                  "target is often behind the star."),

    # --- Fuel -------------------------------------------------------------------------------------------------
    dict(section="Fuel", key="RefuelThreshold", label="Scoop below (%)", type="int", min=0, max=100,
         tip="With fuel scoop: refuel at a scoopable star when the tank is below this level."),
    dict(section="Fuel", key="FuelScoopTimeOut", label="Scoop timeout (s)", type="int", min=5, max=300,
         tip="Max. time to wait for a full tank while scooping."),
    dict(section="Fuel", key="FuelThreasholdAbortAP", label="Abort route below (%)", type="int", min=0, max=100,
         tip="Stops the route when the tank is below this level after a jump (only while jumps are left)."),

    # --- Keys & input -----------------------------------------------------------------------------------------
    dict(section="Keys & Input", key="EnableRandomness", label="Randomise timing", type="bool",
         tip="Varies key hold times, delays and adds short random pauses (so actions do not have a fixed rhythm)."),
    dict(section="Keys & Input", key="RandomnessScale", label="Random pause factor", type="float", min=0, max=5,
         step=0.25, tip="Scales the random pauses: 0.5 = half as long, 2 = twice as long."),
    dict(section="Keys & Input", key="ActivateEliteEachKey", label="Activate Elite before each key", type="bool",
         tip="Brings the Elite window to the front before every key. Only needed if keys get lost."),
    dict(section="Keys & Input", key="Key_DefHoldTime", label="Key hold time (s)", type="float", min=0.01,
         max=1, step=0.01, tip="Default time a key is held down."),
    dict(section="Keys & Input", key="Key_RepeatDelay", label="Delay between repeats (s)", type="float",
         min=0.01, max=1, step=0.01, tip="Pause between repeated key presses."),
    dict(section="Keys & Input", key="Key_ModDelay", label="Modifier key delay (s)", type="float", min=0.0,
         max=0.5, step=0.01, tip="Delay so a modifier (Shift, Ctrl, ...) is detected before/after the key."),
    dict(section="Keys & Input", key="ThrottleKeyHold", label="Throttle key hold (s)", type="float", min=0.05,
         max=1.5, step=0.05, tip="Hold time of the throttle keys (0 %, 50 %, 100 %). Was 1 s (3 s after each "
                                 "jump), ~8 s per jump."),

    # --- Overlay ------------------------------------------------------------------------------------------------
    dict(section="Overlay", key="OverlayTextEnable", label="Show overlay text in game", type="bool",
         tip="Shows the EDAP status as text over the game (experimental)."),
    dict(section="Overlay", key="OverlayTextXOffset", label="X offset (px)", type="int", min=0, max=8000,
         step=10, tip="Distance from the left screen border."),
    dict(section="Overlay", key="OverlayTextYOffset", label="Y offset (px)", type="int", min=0, max=8000,
         step=10, tip="Distance from the top screen border."),
    dict(section="Overlay", key="OverlayTextFontSize", label="Font size", type="int", min=6, max=72,
         tip="Font size of the overlay text."),

    # --- Scanner & combat ---------------------------------------------------------------------------------------
    dict(section="Scanner & Combat", key="ElwScannerEnable", label="ELW scanner", type="bool",
         tip="FSD Route Assist: FSS scan in every system, announces Earth-like, water and ammonia worlds."),
    dict(section="Scanner & Combat", key="DSSButton", label="Discovery scanner button", type="choice",
         choices=["Primary", "Secondary"], tip="Fire button the discovery scanner (honk) is assigned to."),
    dict(section="Scanner & Combat", key="AFKCombat_AttackAtWill", label="AFK combat: fighter attacks at will",
         type="bool", tip="Orders the ship launched fighter to attack at will."),

    # --- OCR ----------------------------------------------------------------------------------------------------
    dict(section="OCR", key="OCRLanguage", label="OCR language", type="choice",
         choices=["en", "de", "fr", "es", "ru"], restart=True,
         tip="Language model of the text recognition. Needs a restart."),
    dict(section="OCR", key="OCRMobile", label="Fast OCR model (less accurate)", type="bool", restart=True,
         tip="Smaller and faster text recognition model, for slow PCs. Needs a restart."),
]


def _locale_choices() -> list[str]:
    try:
        return sorted(f[:-5] for f in os.listdir('locales') if f.endswith('.json'))
    except Exception:
        return ['en']


class SettingsTab:
    """ Builds the settings tab from SETTINGS. """

    def __init__(self, parent, config: dict, defaults: dict, on_change, on_dirty=None, height: int = 520):
        """
        @param parent: Frame of the notebook page.
        @param config: The AP config dict (changed in place).
        @param defaults: Default values (for 'Reset section').
        @param on_change: on_change(key, value) is called after a value was changed (apply it).
        @param on_dirty: on_dirty(True/False) when there are changes that are not saved yet.
        """
        self.config = config
        self.defaults = defaults
        self.on_change = on_change
        self.on_dirty = on_dirty
        self.vars: dict[str, tk.Variable] = {}
        self.rows: dict[str, list] = {}  # key -> widgets of the row
        self.row_text: dict[str, str] = {}  # key -> searchable text
        self.sections: dict[str, ttk.LabelFrame] = {}
        self.section_keys: dict[str, list[str]] = {}
        self.changed_lbl: dict[str, ttk.Label] = {}
        self._loading = False
        self._dirty = False

        # --- top bar: search -------------------------------------------------------------------------------------
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.search_var, width=30)
        ent.pack(side="left", padx=5)
        ToolTip(ent, msg="Type to filter the settings by name or description.", **TIP_STYLE)
        self.search_var.trace_add("write", lambda *_: self._filter())
        ttk.Button(top, text="Clear", command=lambda: self.search_var.set("")).pack(side="left")
        ttk.Label(top, text="Changes are active at once. 'Save All Settings' stores them.  ● = differs from default",
                  foreground="#9a9a9a").pack(side="right")

        # --- scrollable area -------------------------------------------------------------------------------------
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, padx=10, pady=5)
        self.canvas = tk.Canvas(outer, highlightthickness=0, height=height)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        # Mouse wheel only while the pointer is over the settings
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.inner.columnconfigure([0, 1], weight=1, uniform="settings")

        self._build()

    # ------------------------------------------------------------------------------------------------------------
    def _on_wheel(self, event):
        if getattr(event, 'num', None) in (4, 5):
            self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        else:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_wheel_widget(self, event):
        self._on_wheel(event)
        return "break"  # do not pass the event to the widget class (would change the value)

    def _build(self):
        order = []
        for item in SETTINGS:
            if item['section'] not in order:
                order.append(item['section'])
        # Two independent columns of sections (no gaps between sections of different height)
        cols = []
        for c in range(2):
            col_frame = ttk.Frame(self.inner)
            col_frame.grid(row=0, column=c, sticky="NEW")
            col_frame.columnconfigure(0, weight=1)
            cols.append(col_frame)
        col_rows = [0, 0]
        for i, section in enumerate(order):
            col = i % 2
            frm = ttk.LabelFrame(cols[col], text=section.upper(), padding=(10, 5))
            frm.grid(row=col_rows[col], column=0, padx=4, pady=4, sticky="NEW")
            frm.columnconfigure(0, weight=1)
            col_rows[col] += 1
            self.sections[section] = frm
            self.section_keys[section] = []
            r = 0
            for item in (s for s in SETTINGS if s['section'] == section):
                self._add_row(frm, r, item)
                self.section_keys[section].append(item['key'])
                r += 1
            btn = ttk.Button(frm, text="Reset section", command=lambda s=section: self.reset_section(s))
            btn.grid(row=r, column=0, columnspan=3, sticky="E", pady=(6, 2))
            ToolTip(btn, msg="Sets all values of this section back to the defaults.", **TIP_STYLE)

    def _add_row(self, frm, r: int, item: dict):
        key = item['key']
        typ = item['type']
        label = item['label'] + (" (restart)" if item.get('restart') else "")
        tip = item.get('tip', '')
        default = self.defaults.get(key)
        if default is not None:
            tip += f"\n\nDefault: {default}"
        widgets = []

        changed = ttk.Label(frm, text=" ", width=2, foreground="#e0a030")
        changed.grid(row=r, column=2, sticky="W")
        self.changed_lbl[key] = changed
        widgets.append(changed)

        if typ == 'bool':
            var = tk.BooleanVar(value=bool(self.config.get(key, default)))
            w = ttk.Checkbutton(frm, text=label, variable=var)
            w.grid(row=r, column=0, columnspan=2, sticky="W", padx=2, pady=2)
            widgets.append(w)
        else:
            lab = ttk.Label(frm, text=label + ":")
            lab.grid(row=r, column=0, sticky="W", padx=2, pady=2)
            widgets.append(lab)
            ToolTip(lab, msg=tip, **TIP_STYLE)
            if typ == 'choice':
                choices = _locale_choices() if item.get('choices') == 'locales' else list(item['choices'])
                var = tk.StringVar(value=str(self.config.get(key, default)))
                w = ttk.Combobox(frm, textvariable=var, values=choices, width=10, state="readonly")
            elif typ in ('int', 'float'):
                var = tk.StringVar(value=self._fmt(self.config.get(key, default), typ))
                w = ttk.Spinbox(frm, textvariable=var, width=9, justify=tk.RIGHT, from_=item.get('min', 0),
                                to=item.get('max', 100000), increment=item.get('step', 1 if typ == 'int' else 0.1))
            else:
                var = tk.StringVar(value=str(self.config.get(key, default) or ''))
                w = ttk.Entry(frm, textvariable=var, width=12, justify=tk.RIGHT)
            w.grid(row=r, column=1, sticky="E", padx=2, pady=2)
            widgets.append(w)
            if typ in ('choice', 'int', 'float'):
                # The mouse wheel over a dropdown/number field must scroll the page and NOT change the value
                # (2026-10-20 18:09: scrolling the settings changed 'Language' to 'ru').
                w.bind('<MouseWheel>', self._on_wheel_widget)
                w.bind('<Button-4>', self._on_wheel_widget)
                w.bind('<Button-5>', self._on_wheel_widget)
        ToolTip(w, msg=tip, **TIP_STYLE)

        self.vars[key] = var
        self.rows[key] = widgets
        self.row_text[key] = (item['label'] + " " + item.get('tip', '') + " " + key + " " + item['section']).lower()
        if typ == 'str':
            # Text (e.g. hotkey names) is applied when the field is left or Enter is pressed, not while typing
            # (a half typed hotkey name 'p' of 'pgup' would be registered as hotkey).
            w.bind('<FocusOut>', lambda e, k=key, it=item: self._on_var(k, it))
            w.bind('<Return>', lambda e, k=key, it=item: self._on_var(k, it))
        else:
            var.trace_add("write", lambda *_, k=key, it=item: self._on_var(k, it))
            if typ in ('int', 'float'):
                # Show the value really used (limited to min/max) when the field is left
                w.bind('<FocusOut>', lambda e, k=key, it=item: self._show_value(k, it))
        self._update_changed(key)

    def _show_value(self, key: str, item: dict):
        self._loading = True
        try:
            self.vars[key].set(self._fmt(self.config.get(key, self.defaults.get(key)), item['type']))
        finally:
            self._loading = False

    @staticmethod
    def _fmt(value, typ):
        if value is None or value == '':
            return '0'
        try:
            if typ == 'int':
                return str(int(float(value)))
            v = float(value)
            return f"{v:g}"
        except (TypeError, ValueError):
            return str(value)

    def _parse(self, item: dict, raw):
        typ = item['type']
        if typ == 'bool':
            return bool(raw)
        if typ == 'int':
            v = int(float(str(raw).replace(',', '.')))
        elif typ == 'float':
            v = float(str(raw).replace(',', '.'))
        else:
            return str(raw)
        if 'min' in item:
            v = max(item['min'], v)
        if 'max' in item:
            v = min(item['max'], v)
        return v

    def _on_var(self, key: str, item: dict):
        if self._loading:
            return
        try:
            value = self._parse(item, self.vars[key].get())
        except (ValueError, tk.TclError):
            return  # incomplete input (e.g. empty field while typing)
        if self.config.get(key) == value:
            self._update_changed(key)
            return
        self.config[key] = value
        self._update_changed(key)
        self._set_dirty(True)
        try:
            self.on_change(key, value)
        except Exception as e:  # never break the GUI because of one setting
            print(f"Setting {key} could not be applied: {e}")

    def _update_changed(self, key: str):
        lbl = self.changed_lbl.get(key)
        if lbl is None:
            return
        differs = key in self.defaults and self.config.get(key) != self.defaults[key]
        lbl.configure(text="●" if differs else " ")

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        if self.on_dirty:
            self.on_dirty(dirty)

    def mark_saved(self):
        self._set_dirty(False)

    # ------------------------------------------------------------------------------------------------------------
    def reload(self):
        """ Shows the values of the config again (e.g. after a value was changed elsewhere). """
        self._loading = True
        try:
            for item in SETTINGS:
                key = item['key']
                if key not in self.vars:
                    continue
                value = self.config.get(key, self.defaults.get(key))
                if item['type'] == 'bool':
                    self.vars[key].set(bool(value))
                elif item['type'] in ('int', 'float'):
                    self.vars[key].set(self._fmt(value, item['type']))
                else:
                    self.vars[key].set(str(value if value is not None else ''))
                self._update_changed(key)
        finally:
            self._loading = False

    def reset_section(self, section: str):
        for key in self.section_keys.get(section, []):
            if key not in self.defaults:
                continue
            item = next(s for s in SETTINGS if s['key'] == key)
            default = self.defaults[key]
            if item['type'] == 'bool':
                self.vars[key].set(bool(default))
            elif item['type'] in ('int', 'float'):
                self.vars[key].set(self._fmt(default, item['type']))
            else:
                self.vars[key].set(str(default))
                self._on_var(key, item)  # text fields are not traced

    def _filter(self):
        text = self.search_var.get().strip().lower()
        for section, frm in self.sections.items():
            visible = 0
            for key in self.section_keys[section]:
                show = not text or all(t in self.row_text[key] for t in text.split())
                for w in self.rows[key]:
                    if show:
                        w.grid()
                    else:
                        w.grid_remove()
                visible += show
            if visible:
                frm.grid()
            else:
                frm.grid_remove()
        self.canvas.yview_moveto(0)
