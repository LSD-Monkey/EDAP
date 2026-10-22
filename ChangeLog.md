# 10/22/2026 v1.9.4 b40 - reconnect after a connection error
- NEW reconnect (fail-safe of Waypoint Assist, setting 'AutoReconnect', on by default), the sequence of the
  recording 2026-10-22 11:49:
  1. 'CONNECTION ERROR ... Press OK to return to the main menu': UI_Select (OK is selected), wait for the main menu
     (journal: Music 'MainMenu', ~35 s 'LOADING GAME').
  2. Main menu: UI_Up to CONTINUE, UI_Select. The game mode screen is checked by OCR (else UI_Back, next try).
  3. Game mode 'ReconnectMode' (Solo, or Open): UI_Left to OPEN PLAY, UI_Right 2x to SOLO PLAY.
  4. UI_Select every 8 s while the cards show 'CAN'T CONNECT TO FRONTIER SERVERS', until the journal shows
     'Commander'/'LoadGame' (max. 5 min), then wait for the ship (Status.json).
  Failed attempts are repeated after 1, 2, 4, 8, 10, 10 ... minutes. A closed game can not be started by EDAP.
- Fail-safe: before jumping out and back after a failure, the screen is checked for a connection error dialog.

# 10/21/2026 v1.9.4 b39 - trade search: carriers
- Trade tab: the age of BOTH prices is checked for every station (buy price at the seller and sell price at the
  buyer). A market row without a date is no longer treated as fresh (warning with the field names in the log).
  The details of a route show the age of each price ('Gold buy 25 min, sell 3 h').
- Fleet carriers: stricter price age (new field next to 'Fleet carriers', default 6 h, setting
  'TradeCarrierMaxAgeHours'); a carrier price without a date is not used. Carriers in the results are checked
  against the EDSM station list of their system: carriers that are no longer there are removed ('carrier left the
  system' in the skipped list). If EDSM can not be reached, or lists no carrier at all, the routes are kept.
- Docking refused for good (carrier with restricted docking access, ship too large, hostile, offences): the
  fail-safe takes another trade route at once instead of jumping out and back first. The reason is now part of
  the 'Docking failed' message.

# 10/21/2026 v1.9.4 b38 - fail-safe: Waypoint Assist never stops
- NEW sell other cargo first (setting 'TradePreSellMinTons', default 100 t, 0 = off): when a trade route is started
  with more cargo on board than that which the route does not sell, EDAP searches the stations nearby that buy it
  (Ardent, Trade tab filters and radius, ship pad size), takes the one with the highest revenue for the whole load
  (among those within 3% of the best: the closest), flies there, sells it and then starts the route.
- NEW fail-safe for Waypoint Assist / trade routes (setting 'WaypointNeverStop', on by default). Instead of
  stopping on an error (station not reached, trade failed, Galaxy Map / Nav Panel failed, jump failed, any
  exception) it escalates:
  1. 'WaypointRecoveryJumps' (3) times: jump to a neighbour system (the one the ship came from, else the nearest
     from EDSM), then the route continues and flies back.
  2. Still failing: leave the system and wait 'WaypointRecoveryWait' (30) minutes, then try again.
  3. Still failing: start another trade route ('WaypointRecoveryNewRoute') found with the Trade tab filters around
     the current system, without the stations of the failed route (saved as waypoints/trade_*.json).
  The stages start again once a waypoint is completed.
- NEW fuel stop: low fuel no longer stops the route. Below 'RefuelStopPercent' (25%) during the jumps, or when the
  fuel check says the route can not be flown, the ship flies to the nearest station with a fitting landing pad
  (Ardent: stations trading hydrogen fuel, fewest jumps, close to the star; without internet a station with
  refuel from the journals), docks (refuel + repair) and continues. Full tank but route too long: it flies anyway
  and makes the fuel stop on the way.
- Main menu / connection lost / game closed: Waypoint Assist waits until the game is playable again instead of
  stopping. STOP by the user always stops.

# 10/21/2026 v1.9.4 b37
- Trade tab: fleet carriers are shown with their name ('Legacy of caliban N6H-0XW' instead of 'N6H-0XW'). The
  market data (EDDN/Ardent) only has the call sign; the names come from your journals (every carrier seen in a
  system, FSSSignalDiscovered). Carriers never seen keep the call sign.
- Nav Panel: a fleet carrier is also found by its call sign alone ('N6H-0XW' finds the row 'LEGACY OF CALIBAN
  N6H-0XW', OCR mix-ups like 0/O tolerated). The same for the destination check of the Supercruise Assist.

# 10/21/2026 v1.9.4 b36
- FIX Waypoint Assist hung for 5.5 hours (log 2026-10-21 00:52): the ship dropped out of supercruise at the star
  LHS 1582 A on the way to Riazuddin Reach. EDAP pressed 'Supercruise' while the FSD was cooling down, the key was
  ignored and EDAP waited without a time limit for the jump (pirates attacked the ship meanwhile, hull 60%).
  Entering supercruise now waits for the FSD cooldown, presses 'Supercruise' again if the FSD does not charge
  (never while charging, that would cancel it), up to 4 times, and gives up after that or after 'SCEngageTimeout'
  (new setting, 120 s) mass locked. The station is then tried again, after 'Attempts to reach a station' Waypoint
  Assist stops.
- NEW star avoidance during Supercruise Assist (setting 'SCStarAheadPercent', default 12%, 0 = off): if a star
  covers that much of the view ahead (centre of the screen, brightness > 125) after aligning to the destination or
  twice in a row while the SCA flies, EDAP pitches up 90 deg, flies the 'Line of sight escape' time and activates
  the SCA again. Values from the recording 2026-10-21 08:41: flying into the red M star 56-69%, normal
  supercruise 0-1%.
- NEW escape after an emergency drop at a star ('EMERGENCY STOP - TOO CLOSE!', recording 2026-10-21 08:41):
  EDAP no longer throttles up towards the star. During the FSD cooldown (~45 s) it turns away from the star, then
  presses 'Supercruise', aligns with the 'ESCAPE VECTOR' shown on the compass while the FSD charges (heat rises
  fast: 90% -> 159% in 14 s), and throttles up to 100% once aligned ('THROTTLE UP TO ENGAGE'). If the charge is
  lost, it charges again; after 45 s without success it counts as a failed attempt.

# 10/20/2026 v1.9.4 b35
- FIX market: wrong commodity selected, Waypoint Assist stopped at Stiegler Dock (log 2026-10-20 20:14). The BUY list
  of the game also showed PERFORMANCE ENHANCERS (stock 0, not buyable, so not counted by EDAP). Every item after it
  was one position further down than EDAP counted, Bertrandite was never reached and nothing was bought. The OCR
  read the wrong item, but as it was not in EDAP's list the counted position was used anyway.
  Now the read name is also compared with all commodities of the market: if it is one that EDAP does not count,
  EDAP steps towards the target one item at a time and reads the name after every step. A known but wrong
  commodity is never bought any more. Repeated small offsets are corrected with single steps.
- NEW setting 'Attempts to buy a commodity' (TradeBuyAttempts, Waypoint Assist section, default 2, 1-5): how often a
  purchase is tried (market left and entered again in between) before Waypoint Assist stops.
- FIX market: the name region still cut off the start of long names ('RFORMANCEENHANCERS'): 0.678 -> 0.655.

# 10/20/2026 v1.9.4 b34
- FIX 'Waypoint Assist stopped: main menu, game closed or not in the ship' right after starting a trade route
  (log 2026-10-20 19:44): EDAP was started before the game. The journal reader opened the new journal of the game,
  but kept the name of the old one (current_log). The game state check then read the old journal, which ends with
  'Shutdown'. In addition the new journal was opened and read from the start again every second ('Opening new
  Journal' in the log). The reader now remembers the new journal; the game state check always reads the newest one.

# 10/20/2026 v1.9.4 b33 - faster trading (analysis of the 18:14 recording)
- FIX settings: the mouse wheel over a dropdown or number field changed the value while scrolling ('Language'
  became 'ru' at 18:09). Now the wheel only scrolls, everywhere in the GUI.
- FIX market: the commodity name region started too far right ('TICAPPLIANCES', 'SILVER' not readable): 0.70 ->
  0.678.
- Throttle keys: the 'repeat' argument was used as hold time, every throttle change held the key 1 s (3 s after
  each jump). Now 0.25 s ('ThrottleKeyHold'), ~8 s per jump.
- FSD charge during the alignment ('FSDChargeWhileAligning'): the charge (~15 s) starts after the star avoidance,
  the charged FSD waits until the ship points at the target. jump() does not press the key again.
- Without fuel scoop only 8 s past the star after a jump ('StarPassTimeNoScoop', was 17 s). After the jump 2 short
  throttle presses + 0.5 s instead of 3 s hold + 1 s.
- Compass align: big sideways offsets are turned with roll + pitch when that is faster than yaw (Type-9 yaw
  5.5 deg/s, pitch 12-13 deg/s); rolls go to the nearer of 12/6 o'clock (max. 90 deg).
- Station target: with the in-game SC Assist the station is searched only once in the Nav Panel (was twice).
- Nav Panel: no 3 s wait for the focus when the panel is closed (docking request, SC Assist activation).
- SC Assist: no OCR in the last seconds before the drop (km or < 50 Mm), the drop is detected at once; no fixed
  4 s + 5 s wait after the drop.
- Docking: request at once after the drop, again every 3 s while 'too far away'; 'DockApproachTime' is the max.
  time at 100 % before 50 %. Contacts list top: 1 s hold instead of 2 s.
- Market: the highlighted commodity is read first; known position -> no 5 s 'hold up'; items far down the list
  are reached from the bottom.
- Waypoint Assist: after the trade the launch starts first and the route is plotted in the galaxy map while the
  docking computer flies out ('PlotRouteWhileUndocking').
- After the launch: while mass locked the next target is rolled onto the pitch axis ('PreRollAfterUndock');
  mass lock checked every 0.25 s.
- Galaxy map: shorter waits and key presses (~6 s).
- Random pause factor default 0.5.
- Trade tab: all sellers x all buyers of every commodity are paired (numpy) instead of only the 60 cheapest/most
  expensive of the area; round trips may fly back empty; 80 commodities by default; times per jump and per station
  are learned from your journals for the profit per hour.

# 10/20/2026 v1.9.4 b32
- Trade tab reworked like the Inara trade route search: searches the area around a reference system (your
  location) instead of only from the current station. Settings: max. distance to the start, max. distance between
  the stations, max. star distance, cargo, min. supply/demand, price age, pad size, jump range, number of
  commodities, fleet carriers / megaships / planetary ports / Odyssey settlements yes/no, round trips or one way,
  sort order. For every commodity the sellers and buyers in the area are loaded (Ardent Insight API) and combined
  to trades and round trips. Results with distance to start, profit per trip/hour and price age; start directly.

# 10/20/2026 v1.9.4 b31
- New Trade tab: finds the best round trips from a start station (like the Inara trade routes) and starts one
  directly. Start market from Market.json (docked) or the Ardent Insight API (EDDN data), buyers of every export
  within the max. distance, best return commodity per destination, profit per trip and estimated profit per hour
  (jumps by laden jump range, supercruise by arrival distance, docking/trading). Filters: distance, arrival
  distance, data age, pad size, planetary. 'Start trade route' writes waypoints/trade_<A>_<B>.json (A, B, REPEAT),
  loads it and starts Waypoint Assist. See docs/Trade.md.

# 10/20/2026 v1.9.4 b30
- New Market Test (Debug/Test tab): enter a commodity (the dropdown lists what the last opened market sells) and a
  quantity, tick 'Run Market Test'. EDAP opens the commodities market of the station you are docked at, buys the
  commodity once and optionally sells it again, using the same functions as the trade of Waypoint Assist. Every
  step is checked and logged as '[Market test] OK/FAIL/INFO ...': market opened, BUY/SELL selected, commodity
  found in the list (OCR confirmed / counted position / failed), cargo before -> after, what happened with the
  dialog, still in the market. Summary at the end. Untick or STOP ALL stops it.
- Market Test with a full hold (or not enough free space) and the commodity on board: sells the quantity first and
  buys it back (the order of the trade route). Before it stopped with 'no free cargo space'.

# 10/20/2026 v1.9.4 b29 (video analysis of session 2026-10-20_16-57-51)
- FIX trade: after a sale/purchase the game now closes the BUY/SELL dialog itself. The UI_Back added in b24 then
  left the commodities market, the following 'select BUY' keys opened the MISSION BOARD in the station menu and
  the 37 'down' presses went there (17:22, Orbital Sanctum; same at 16:57, Macgregor Orbital). The OCR read the
  station reputation ('NEUTBAL', 'CORDIAI') instead of a commodity, EDAP still used the counted position.
  - UI_Back only if the dialog is still open (OCR of the dialog title, new region 'dialog_title').
  - Before selecting BUY/SELL: if the station menu ('CONNECTED TO') is shown, the market is opened again.
  - If the highlighted name is no commodity and the station menu is shown, the selection fails and the purchase
    is retried after re-entering the market (instead of buying 'blind').
- Market list: the commodity name is read a second time if the first read is empty (panel fades in).

# 10/20/2026 v1.9.4 b28 - GUI rework
- Main tab: MODE list with a STOP ALL button and a live STATUS panel (running assist, activity, run time, system /
  station, ship, fuel bar, cargo, waypoint file and next waypoint, jumps). Log with auto-scroll on/off, Clear and
  Open log file; the log list keeps max. 5000 lines (long sessions made the GUI slow). The run time of an assist
  is logged when it stops.
- New Ship tab: SunPitchUp time, roll/pitch/yaw auto-tune with short instructions, throttle and 'Align to Target'
  test buttons, rate curve editor.
- New Settings tab built from one settings table (EDAPSettingsTab.py): 10 sections, search field, tooltip with the
  default value for every setting, marker for values that differ from the default, 'Reset section', changes are
  active at once ('Save All Settings *' shows unsaved changes, closing asks to save). Hotkey fields are applied
  when the field is left (no half typed hotkeys), invalid hotkeys are reported instead of breaking the others.
- Many settings that could only be changed in AP.json are now in the GUI: all Supercruise Assist, docking,
  departure, Waypoint Assist and safety settings, language, OCR, galaxy map delay.
- New settings: 'SCAssistMaxActivations' (5), 'WaypointRestartDelay' (10 s), 'RandomnessScale' (1.0).
- Waypoint Assist asks for a waypoint file when none is loaded instead of starting and stopping at once.
- 'Load All Settings' now really reloads AP.json (before only the ship configs).
- FIX: every click on a mode checkbox saved AP.json (CV view handling) and set the log level again.
- AP.json defaults are defined once (EDAutopilot.default_config()), missing entries get their default automatically.
- docs/Settings.md generated from the settings table.

# 10/20/2026 v1.9.4 b27 (log analysis 2026-10-20: 43 min productive, then 3 h stuck)
- In-game SC Assist: throttle 50 % after the SCA is activated (and aligned). With throttle 0 the SCA sometimes
  never started (distance stayed at 76.8 Ls for 13 minutes).
- SC Assist progress watchdog: the distance under the destination name ('MACGREGOR ORBITAL 76.8Ls') is read with
  the line of sight OCR. If it does not change for 'SCAssistStallTime' (default 60 s): 1st time compass align +
  throttle 50 %, 2nd time re-activate the SCA, 3rd time give up.
- Game connection check ('GameConnectionCheck', default on): every assist stops (like the stop button, no
  auto-restart, no further key presses) when
  - 'CONNECTION ERROR ... matchmaking server' is on screen (checked during SC Assist and whenever the Nav Panel
    does not open),
  - the journal shows the main menu or the game was closed,
  - Status.json reports Flags 0 (not in a ship, not on foot) for 20 s.
  Before, EDAP kept trying for 2 hours after the connection was lost (09:05).
- FIX endless loop in Waypoint Assist: 'Unable to activate in-game Supercruise Assist ... Stopping.' did not stop,
  the waypoint loop started the next attempt at once (697 attempts, 09:52 - 11:59). sc_assist() now returns a
  result, Waypoint Assist stops after 'WaypointStationRetries' (default 3) failed attempts in a row.
- Fuel check before the route ('FuelRouteCheck', default on, ships without fuel scoop): the fuel use per jump is
  learned from the FSDJump events of the recent journals (same ship, similar cargo, fuel = k * dist^p), the jump
  distances come from NavRoute.json. Stops before the jump if the fuel is not enough, warns if the arrival fuel
  will be below the abort threshold. (Kakmbutan route: about 57 t of 64 t, arrival with 11 %.)
- Low fuel abort ('FuelThreasholdAbortAP') only while there are jumps left; in the destination system EDAP
  continues to the station instead of stopping just before it.

# 10/20/2026 v1.9.4 b26
- FIX hard crash ('Windows fatal exception: access violation', crash.log 2026-10-20 08:48): PaddleOCR is not
  thread safe, but the engine thread (Nav Panel) and the SC monitoring thread (disengage text) used the same
  instance at the same time -> 'OCR failed: Unknown exception' -> re-initialisation while the other thread was
  still inside predict() -> process crash. All PaddleOCR calls and the re-initialisation are serialised with a
  lock now. Probably also the cause of earlier silent crashes during OCR.

# 10/20/2026 v1.9.4 b25
- Waypoint Assist restarts itself after an error instead of stopping (log 2026-10-20 08:32: 'mnvr_to_target
  failed 5 times'). 10 s pause, throttle 0, then it continues from the current position. Max.
  'WaypointAutoRestarts' (default 3) restarts in a row (counter is reset after 20 min). A stop by the user is
  never restarted.
- FIX compass align: reported 'failed - exhausted all retries' although the last correction had aligned the ship
  (yaw -0.37, pitch 0.35). The position is now checked after every try.
- Compass align: if the compass is not detected, every 2nd try pitches up 45 deg instead of only rolling (a big
  star in front - 'sun avoid failsafe timeout' - hid the compass for 3 minutes). The 'unable to detect compass'
  loops read the compass again instead of logging 20x without doing anything.
- Target align: if the target reticle is not found but the compass says aligned, EDAP jumps instead of failing.

# 10/20/2026 v1.9.4 b24 (video analysis of session 2026-10-19_23-28-31)
- FIX trade (root cause of the failed Rutile purchase): after selling, the SELL COMMODITY dialog stays open
  (0/0, CANCEL selected). The 'select BUY' keys went into the dialog, EDAP stayed in the SELL list and 'bought'
  nothing. The sell and buy dialogs are now closed with UI_Back after the transaction.
- FIX trade: the highlighted commodity is checked by OCR of the info panel ('selected_name' region) and corrected
  with up/down if it differs (one of 37 'down' presses got lost: LITHIUM instead of SILVER). Down presses are
  slower (0.08 s hold, 0.12 s gap). If the name is not readable, the counted position is used as before.
- FIX alignment: if compass and target reticle disagree by > 10 deg, the compass is used. The reticle is the
  *selected target* (here the planet Kakmbutan 6), not necessarily the destination; EDAP aligned to the planet and
  the in-game SCA waited with 'ALIGN WITH TARGET DESTINATION' until the user aligned by hand.
- SC Assist: 'ALIGN WITH TARGET DESTINATION' (read by the existing OCR check) triggers a compass align.
- Docking approach at 100% throttle (drop at ~11.5 km, docking possible < 7.5 km), 50% before requesting docking.

# 10/20/2026 v1.9.4 b23 (analysis of datalogger session 2026-10-19_23-28-31)
- FIX trade: the purchase is verified via the cargo count in Status.json. EDAP logged 'Bought 752 units of
  Rutile' although nothing was bought (no MarketBuy in the journal, cargo 0) and flew the route empty. Now: if
  the cargo did not change, the market is left and entered again and the purchase is retried once; if it still
  fails, Waypoint Assist stops while docked instead of flying empty.
- Commodities market: confirmed by the Market.json update (written by the game when the market opens) instead of
  waiting 15 s for an OCR check that never succeeded on 3440x1440. OCR is only the fallback.
- Docking: request while still approaching at 50% throttle and ask again every ~6 s on 'too far away' (was
  stop, fly 10 s, stop, ask: 3 denials and up to 2:20 min after the drop). Throttle 0 when granted or given up.
- SC Assist monitor: no HUD OCR while Elite is not the active window (the 'SUPERCRUISE ASSIST ACTIVE' check was
  switched off after Discord was in front for 43 s).
- Auto-tune: no learning below 1 deg or above 90 deg; below 5 deg points are stored in 1 deg steps (0.25 deg
  steps produced neighbouring points like 2.0: 4.6 / 2.25: 14.4 deg/s). Existing fine points are merged.

# 10/19/2026 v1.9.4 b22
- Auto-tune RPY reworked:
  - The result of a movement is measured after the ship has stopped turning (compass reading stable, max. 3 s).
    It was measured 0.5-0.75 s after the key release; heavy ships still turn then, so the learned rate was too
    low and the ship kept oscillating around the target.
  - New measurements are blended 50/50 with an existing curve point instead of overwriting it.
  - Learned curves are saved to configs/ship_configs.json automatically (max. every 20 s). Before they were lost
    on restart unless 'Save All Settings' was clicked.

# 10/19/2026 v1.9.4 b21
- FIX GUI freeze (white window): the GUI buttons '0/50/100% Throttle' and 'Align to Target' ran in the Tk main
  thread. After clicking a button the EDAP window is the active window, so the key sender paused ('Elite is not
  the active window') inside the GUI thread and the window froze until Elite was clicked again. 'Align to
  Target' clicked during a running assist also steered in parallel to the assist. Now these actions run in a
  background thread, bring Elite to the front first and are refused while an assist is running.
- EDKeys.wait_for_focus never blocks the Tk main thread (brings Elite to the front instead).
- Log lines from worker threads are written to autopilot.log immediately in the calling thread (correct order
  and timestamps); only the GUI list update is queued for the main thread.

# 10/19/2026 v1.9.4 b20
- FIX crashes: callbacks from worker threads (engine, SCO monitoring, key sender/focus pause, hotkeys) changed
  Tk widgets directly. Tkinter is not thread safe; with several threads logging at the same time (typically
  around the focus pause) the process ended without any traceback. Callbacks from other threads are now queued
  and processed in the Tk main thread (EDAPGui.callback / _process_cb_queue).
- Docking: approach time before requesting docking is configurable ('DockApproachTime', default 20 s, was 12 s).
  On 'too far' denial EDAP flies 10 s (was 5 s) closer before asking again.
- Waypoint Assist: if started while docked at the station of a waypoint, the route continues from that waypoint
  (its trade is done first) instead of undocking and flying to the first open waypoint.

# 10/19/2026 v1.9.4 b19
- FIX steering: auto-tune learned absurd rates (pitch 1492 deg/s, -151073 deg/s at 180 deg) from compass
  readings at large angles and from extrapolation. With these the keys were only tapped for 0.1 s and the ship
  did not turn. Now: points above 100 deg or with implausible rates (Roll 1-200, Pitch 0.5-90, Yaw 0.3-60 deg/s)
  are not learned, and implausible curve values are clamped when the hold time is calculated.
- Crash logging: faulthandler writes the stack of all threads to crash.log on a hard crash (no Python
  traceback in autopilot.log), Tk callback and uncaught exceptions are logged.

# 10/19/2026 v1.9.4 b18
- FIX SC Assist: 'SUPERCRUISE ASSIST ACTIVE' was found by OCR, but the region also contained other HUD text
  (body type, 'DISCOVERED ...'), so the similarity of the whole list was < 0.5 and EDAP re-activated the SCA
  for no reason. Now the text itself is searched (spaces removed).
- Nav Panel: if the destination is not found (e.g. panel opened in the details view), UI_Back and retry once.
  Every list row is logged with its OCR text and similarity.
- Waypoint Assist: after a trade the route to the next system is plotted again (cargo changes the jump range;
  an old route made while empty caused 'FSD failed to charge' x3 with 752 t cargo). If the route already goes
  to the target, PLOT ROUTE clears it first, it is then pressed a 2nd time. Route changes are detected via the
  NavRoute.json timestamp (new NavRouteParser.get_route_stamp()).

# 10/19/2026 v1.9.4 b17
- In-game SC Assist: detects 'MOVE TO OBTAIN LINE OF SIGHT TO TARGET' (target behind a planet/star, OCR region
  'sca_no_los', seen twice in a row). Then: throttle 0, pitch up 90 deg, full throttle for 'SCAssistNoLOSEscapeTime'
  (20 s), throttle 0, re-activate the SCA (aligns to the target again). Max. activations raised from 3 to 5.

# 10/19/2026 v1.9.4 b16
- FIX: Nav Panel scroll_to_top_of_list() held UI_Up until the OCR of the selected row was stable. With slow OCR
  this took 30 s, and if no highlighted row was found it hung forever with UI_Up held (seen when activating the
  SC Assist to Colonia Dream). Now: UI_Down, hold UI_Up 3 s, done.
- find_destination_in_list(): no endless loop any more (no highlighted row -> give up after 5 tries, empty OCR
  -> next row, max. 60 rows / 90 s).

# 10/19/2026 v1.9.4 b15
- Galaxy Map: plot route with the key sequence recorded 5x with success (session 2026-10-19_08-27-25):
  K, Up, Space, type name, Down, Space (suggestion), 'D' (primary UI_Right, restores UI focus), Right Arrow,
  7x Down Arrow, Space. Replaces the 'S' tap and the extra Right/Up presses.

# 10/18/2026 v1.9.4 b14
- Galaxy Map: route plotting rebuilt from the recorded session that worked (2026-10-18_23-17-36):
  search field -> type name -> wait for the suggestion list -> UI_Down + UI_Select (suggestion) -> UI_Right
  (+ extra Right/Up to the top icon) -> 7x UI_Down (PLOT ROUTE) -> UI_Select. ENTER is no longer pressed in the
  search field: it jumps to the system but the UI loses the focus, so all arrow keys after it did nothing.
- Galaxy Map: after selecting the suggestion the primary key of UI_Down (S) is tapped once to bring the UI focus
  back (as in the recorded successful run), only then the arrow keys are used.
- Galaxy Map: removed the slow OCR checks (CARTOGRAPHICS, SYSTEM INFORMATION, PLOT ROUTE took 5-26 s each).

# 10/18/2026 v1.9.4 b13
- FIX: Extended keys (arrow keys, Home/End, Insert/Delete, PgUp/PgDn, right Ctrl/Alt) were sent with the raw
  DirectInput code (e.g. 0xCD), which Windows reads as a key release. They never reached the game. Now sent as
  scancode + KEYEVENTF_EXTENDEDKEY. Affects every bind that uses an arrow key (e.g. UI_Up/Down/Left/Right).
- Galaxy Map: before PLOT ROUTE 8x UI_Right + 8x UI_Up to reach the top icon of the right column from any focus.

# 10/18/2026 v1.9.4 b12
- Galaxy Map: route plotting rebuilt from a recorded session: >| selects the 1st search result (each further
  press the next), then 2x UI_Right, 7x UI_Down (PLOT ROUTE), UI_Select. If the route goes to a wrong system
  the map is reopened and the next search result is used (max. 5). Waits for the SYSTEM INFORMATION panel
  (OCR, else 3 s) before moving right, slower key gaps; CARTOGRAPHICS region widened for 21:9.
- Enable Randomness extended: varied default key hold times and small gaps between key presses (calibrated
  rotation holds unchanged), random pauses before undocking, supercruise entry, FSD jump and trading.

# 10/18/2026 v1.9.4 b11
- Galaxy Map: opening waits on Status.json GuiFocus (fast) instead of 15 s OCR of 'CARTOGRAPHICS'.
- Galaxy Map: waiting for the Nav Route no longer hangs forever (20 s timeout, max. 5 targets tried, CPU busy loop
  removed). On failure a screenshot is saved to debug-output.

# 10/18/2026 v1.9.4 b10
- Fix: trading waited forever for market data when the commodities market could not be opened. The wait is now
  limited to 30 s; existing data of the same station is used, otherwise the trade at this station is skipped.

# 10/18/2026 v1.9.4 b9
- OCR text check accepts text truncated at the region edge (e.g. 'CONNECT' for 'CONNECTED'). Station services
  waited ~15 s for the 'CONNECTED' text on every trade.

# 10/18/2026 v1.9.4 b8
- Waypoint/Single Waypoint: with the Supercruise Assist module, supercruise_to_station no longer requires a visible
  compass before starting SC Assist (it often is not visible after arriving in a system).
- SC Assist uses the exact in-game destination name from Status.json when it matches the waypoint station name
  (e.g. after a bookmark selected it).

# 10/18/2026 v1.9.4 b7
- Nav Panel tab detection: logs what OCR read, falls back to the position of the highlighted tab if OCR fails,
  debug images are written again (test/nav-panel/out is created automatically).
- SC Assist no longer silently falls back to the EDAP steered SC Assist when the in-game SCA cannot be activated
  (ship has the module). New setting 'SCAssistFallbackManual' (default off).

# 10/18/2026 v1.9.4 b6
- Fix: a key binding with an unknown key name was stored as an empty binding. It looked valid but every send of it
  (e.g. HeadLookReset when opening the Nav Panel) and release_all_keys failed with "KeyError: 'key'", which
  stopped SC Assist right after "throttle 0". Unknown keys are now ignored with a warning.
- Added the German (de-DE) key names Key_ä, Key_ö, Key_ü, Key_ß, Key_Acute, Key_Circumflex, Key_Plus, Key_Hash,
  Key_LessThan to the scan code table.
- Assist errors are now also shown in the EDAP log window (previously only in the debug log).

# 10/18/2026 v1.9.4 b5
- SC Assist flow changed: enter supercruise, throttle 0, activate the in-game SCA, then align to the destination
  while standing still, then let the in-game SCA fly and drop. Setting renamed to 'SCAssistAlign'
  (old 'SCAssistAlignBeforeActivate' is migrated).

# 10/18/2026 v1.9.4 b4
- New: key input is paused (not stopped) while Elite is not the active window, e.g. after clicking into EDAP or
  another program. A held key is released and the remaining hold time continues once Elite is active again.
  Setting 'PauseWhenUnfocused' (default on, ignored if 'ActivateEliteEachKey' is on).

# 10/18/2026 v1.9.4 b3
- Fix: stopping an assist while a key is held (e.g. a long pitch) took until the hold time ended (up to minutes).
  Key holds are now interruptible and the key is always released.
- Roll/pitch/yaw key holds are limited to 15 s per movement.
- Auto-tune no longer learns a rate when the ship (almost) did not move. This happened when key presses did not
  reach the game and produced tiny rates and hold times of several minutes.

# 10/18/2026 v1.9.4 b2
- Fix: the engine thread could die silently when a stop request (EDAP_Interrupt) or an error occurred outside of an
  assist's try/except (e.g. during clean-up). Afterwards EDAP ignored all assist starts until restarted. Every engine
  loop iteration is now protected and errors are logged.
- Uncaught exceptions in background threads are now written to autopilot.log (previously only to the console).
- Fixed start_ed_ap.bat (python detection, aborted setup, window stays open on errors).

# 10/18/2026 v1.9.4 b1
- SC Assist now uses the in-game Supercruise Assist module: selects the destination in the Nav Panel (waypoint station
  or current Status.json destination), aligns, activates SUPERCRUISE ASSIST and lets the game fly. EDAP only monitors
  (arrival, interdiction, destination change, timeout) and docks afterwards.
- The previous EDAP steered SC Assist is kept as fallback (`sc_assist_manual`) for ships without the module.
- Nav Panel opens with `FocusLeftPanel` if bound (no need for `UIFocus`/`HeadLookReset`).
- New settings: SCAssistTimeout, SCAssistAlignBeforeActivate, SCAssistCheckActiveOCR.
- New calibration region 'sca_active' and locale key SC_ASSIST_ACTIVE_MSG.
- Added unit tests (test_SCAssist.py) that run without the game.

# 6/13/2026 v1.9.3
- Removed duplicate save all settings buttons.
- Removed test rpy buttons.
- Updated documentation.

- # 6/8/2026 v1.9.2
- Updated packages for Python 3.11.
- Added Supercruise Assist module and status detection (for future use).
- Added additional help pages to github.
- Added 'Online HELP' button to app that takes user to the specific help page.
 
# 5/24/2026 v1.9.1
- Added additional help pages to github.
- Added 'Online HELP' button to app that takes user to the specific help page.

# 5/23/2026 v1.9.0
- Minor update for release.

# 5/23/2026 v1.9.0 b19
- Disengage stays active until disengage check loop is complete.

# 5/17/2026 v1.9.0 b18
- Added throttle dropdown to allow any RPY curve to be edited.
- Deleted RPY rates entry boxes.
- Edit curves button changes selected throttle, not current throttle.

# 5/14/2026 v1.9.0 b17
- Added quick SC disengage, moving key action to detection function.
- Ship moving now always calculates movement error, removing additional checks after the movement.

# 5/11/2026 v1.9.0 b16
- Added auto-tune feature.
- Added Auto-tune RPY checkbox to GUI and ap.json.
- Ship tuning now uses the new combined compass/target detection, allowing tuning greater than 45/30/30 deg for R/P/Y.
- After honking, rotate the ship so that the target is at the top of the compass. When we go past the star, the target will be better aligned.
- Added initial implementation of combined compass and target offset routine which uses both compass and target together to give a better result.
- Added replacement refuel function that provides better control and logging.
- Modified sun avoid to prevent those ships that overshoot the star and pitch down from pitching down if we are not fuel scooping.
- Waypoint Assist now defaults to  station name for OCR if no bookmark index is supplied even when OCR is not the selected bookmark type.
- Perform sun ahead check when starting FSD assist.
- Fixed bug with cvview. Thanks InstaGibb.
- Added additional image checks to OCR.py. Thanks Clippy.
- Added additional checks to Screen.py. Thanks Clippy.
- Added logging of the destination change for a future feature.

# 5/4/2026 v1.9.0 b15
- Adding set throttle log entry.
- Added new ap.json setting 'OPCMobile' to use mobile (light) version of OCR. Thanks Bulli.
- Fix missing hyphen in 'Non-Lethal Weapons'. Thanks Skream.

# 5/2/2026 v1.9.0 b14
- Fixed pitch up to remove the 1.25 multiplier. Thanks Patrick.
- Added 2 sec time delay after setting throttle on surface launch. Thanks Patrick.

# 4/29/2026 v1.9.0 b13
- Breaking Change: Ship PRY rates now stored in float instead of int*10 format. This will require recalibration or manual editing of ships config json file.
- Added Speed0, Speed50, Speed100, SCSpeed0, Speed100 to the ship config to allow each to be tuned.
- Added Set Speed buttons for 0/50/100% for ship tuning.
- Added additional steps to the ship RPY tuning.
- Added Lynx Highliner.

# 4/26/2026 v1.9.0 b12
- Fixed template reload issue. Thanks Patrick.

# 4/25/2026 v1.9.0 b11
- Updated cal doc.
- Quick RPY bug fix.
- Updated readme.
- Included some of Wauxadd's changes (below). Thanks Wauxadd.
- Prevent reload of waypoint file on internal change.
- Reinit OCR on an internal failure.
- Minor change to Status file checking.

# 4/25/2026 v1.9.0 b10
- Changed layout of RPY test buttons.
- Ship RPY now uses the last curve data value instead of defaulting to the default value when after the last curve point.

# 4/19/2026 v1.9.0 b9
- Removed 30 and 45 degree limits from RPY calculation to allow wider range on curves.
- Added 60 deg to default curve.
- Added auto sorting of calibration curves.
- Moved some ship functions to ship control.
- Removed templates that are no longer used (compass and target).
- Removed compass scale and target scale. Not needed with ML.
- Removed calibrate compass.

# 4/12/2026 v1.9.0 b8
- Added a RPY curve editor accessible via 3 new edit buttons under the RPY rates.
- Removed the unused RPY Factor constants and code.
- Updated compass ML model.
- Added some extra logging when checking station names.
- Added extra debug (save input image) for OCR errors. Image saved to ocr_output folder.

# 3/30/2026 v1.9.0 b7
- Fixed some crashes thanks to clippy.
- Fixed issue with loss of target and target occluded at the same time. 

# 3/29/2026 v1.9.0 b6
- Default debug on for new users.
- Added logging of FSS tuning screenshot to debug image folder.
- Added all remaining screen regions into new screen region dictionary to allow user to configure them.
- Improved ML model type selection.
- Enabled ML detection for target occluded.
- Added Kestrel Mk II to data files.
- Fixed ELW Scanning selection not appearing in GUI.
- Updated compass model.

# 2/10/2026 v1.9.0 b5
- Expanded ML for target and compass navpoint.
- Fixed save not working.

# 2/10/2026 v1.9.0 b4
- Added Machine Learning for compass.
- 
# 2/4/2026 v1.9.0 b3
- Improved calibration by adding sub-regions to the calibration tab to allow easier identification of the sub-regions.
- Enable/disable hotkeys now no longer needs a restart.
- Added current station to log when docking.
- Changed detection of colonisation ship.
- Additional OCR replacements.
- Added Squad Carrier to leaving SC code.
- Added cargo test when selling commodities to sell all when cargo is less than sell qty.
- Added button for REPEAT waypoint.
- Added FleetCarrier monitor class.

# 1/4/2026 v1.9.0 b2
- Added load last wp function.
- Added Load Settings button to main form.
- Refactor colonization editor.
- Add Fleet Carrier data to colonization editor.
- Consolidated json reading/writing for ship configs.
- Added Colonization Editor to docs.

# 12/30/2025 v1.9.0 b1
- Added Colonization Tab.

# 12/21/2025 v1.8.0
- Minor update for release.

# 12/6/2025 v1.8.0 b19
- Rewrite of RPY calibration routines.
- RPY movements now uses calibrated sample rates from calibration.
- Updated PaddleOCR to latest version.

# 12/2/2025 v1.8.0 b18
- Added Caspian Explorer.
- Updated readme to include options not on the GUI.

# 11/22/2025 v1.8.0 b17
- Add config parms for FC Leaving Angle and Obital Const Site Angle.
- Added delay for gal map system select to config file.
- Added some additional base types.
- Added more compass debug overlay.
- Reduced compass align multiplier to help PC2 when target is covered by cockpit.
- Increased the margin for P/Y factor reduction.

# 11/8/2025 v1.8.0 b16
- Allow detection of squadron carrier and commodity buy/sell and transfer.

# 11/6/2025 v1.8.0 b15
 - Changed RPY factor calculation.
 - Added automatic factor modification based on overshoot.
 - Simplified saving.
 - Added Plot to Station button to waypoint editor to allow testing of the waypoint bookmark.
 - Disable disengage detection when not in cockpit view.
 - Added Debug_ShowCompassOverlay and Debug_ShowTargetOverlay to config file (not GUI).

# 11/3/2025 v1.8.0 b14
 - Added function to track last EDAP speed command.
 - Added hold > 0 check.
 - Added potential fix for overlay error.
 - Added RPY factors to the ship config file.
 - Added RPY factors to calculate ship movement timings.
 - Better ship config loading.
 - Quicker (but less accurate) target occluded movement.

# 10/25/2025 v1.8.0 b13
 - Updated screenshots for github main page.
 - Added Key class default values to config file for users to tune. Added to Settings tab as well.
 - Added target align tuning values to config file.
 - Increased some delays to improve performance on older computers.

# 10/22/2025 v1.8.0 b12
 - Added sell ALL and buy ALL to the waypoint trader for normal station and FC commodity markets.
 - Added Debug OCR option to enable logging of OCR detection if there are OCR issues.
 - Added Debug Images option to log some images for debug purposes.

# 10/19/2025 v1.8.0 b11
 - In English locale file, changed CONNECTED TO to CONNECTED.
 - Added enable hotkey option (off by default) to help new players with bindings.
 - Disabled target auto calibration (again).
 - More improvements to SC.
 - Enabled overlay for auto calibration.
 - Added time indication for disengage overlay.
 - Added OCR detection for disengage into sco thread.
 - Fixed issue with target scale not being read from save file.
 - Added auto deletion of old log files.
 - Cleared target and compass overlays when moving the ship.
 - Decreased margin for compass align and nav detect is more accurate.

# 10/16/2025 v1.8.0 b10
 - Reduced fallback for gal and sys map.
 - Better detection of Col Ships.
 - Improved sc disengaged image.
 - Improved SC disengage operation.

# 10/12/2025 v1.8.0 b9
 - Added 'ScreenScale' to config as the auto target calibration is now messing with the other template scaling.
 - Moved occluded target code into the target code. This should make occluded state easier to check and test.
 - Changed target regions back to default and increased occluded target filtering.
 - Updated occluded target image to regular target size.
 - Added delay after ship movement in SC assist to allow ship to finish moving. 
 - Added FSD ETA to overlay.
 - Added logging of target offset, before and after for test.
 - Added SC check to interdiction logic. Thanks vasconet.
 - Added nav point correction when target aligned, to zero out any nav point offset errors.
 - When in sc assist and compass is in control, increased the threshold as the compass is less accurate.
 - Added ETA to system to log.

# 10/9/2025 v1.8.0 b8
 - Added Delete All global shopping button.
 - Added Load Construction Commodities button to add construction commodity requirements to global shopping list.
 - Added additional nav_align error checking.
 - Changed sc_assist constants.

# 10/7/2025 v1.8.0 b7
 - Change auto calibration range.
 - Added auto calibrate when first initialising SC instead while in SC.
 - Target align now falls back to compass align automatically to keep on target.
 - Changed target align thresholds.
 - Added wait for removal of mass lock when leaving stations.
 - Added construction requirements logging to 'configs\construction.json' file. Updated when docking with construction site.
 - Fixed bug during auto calibration.
 - Added FOV calculation.
 - Updated calibration docs.
 - Added Type-11 Prospector.

# 9/1/2025 v1.8.0 b6:
 - Updated PaddleOCR.
 - Added screen calibration.

# 9/1/2025 v1.8.0 b5:
 - Updated requirements to remove OCR crash
 - Made fix to Spansh import.
 - Added waypoint editor tab from DankShaman's branch.
 - Fixed error on missing NavRoute.json file.
 - Updated GUI.
 - Added auto calibration (WIP).
 - Improved debug overlay.
 - Improved fallback for ED client window detection.

# 8/19/2025 v1.7.0: General updates.
 - Changed all Parser files to UTF-8 format.
 - Fixed CARTOGRAPHICS detection.
 - Improved key collision reporting.
 - Fixed nav point directly behind us causing ship to roll continually.
 - Added simple OCR detection to Nav Panel tab
 - Reworked internal (right) panel with OCR and debug overlay.
 - Added OCR checks for Gal map and Sys map.
 - Added Debug Overlay option.
 - Fix not selling CMM Composites and any other item with space in name.
 - Improved nav point behind logic.
 - Added new template matching mode with separate H, S and V channel detection.
 - Changed timeout for auto dock.
 - Speed/simplify docking request.
 - Added additional checks when market.json is not available (never been docked at station).
 - Added startup and requirements batch files from Glasses branch.

# 7/28/2025 v1.6.1: Debug_overlay bug.
 - Removed debug_overlay bug.

# 7/28/2025 v1.6.0: Panther Clipper + small improvements.
 - Added quick fix for Robigo issue not selecting the system.
 - Changed logger level on startup to INFO to allow logging of startup info before the user settings are read. Added mostly so we can log the version of EDAP that is started.
 - Updated Russian language file.
 - Moved default ship data from files to EDAP_data.py and included all ships.
 - Deleted unused old config files.
 - Added panther clipper data.
 - Improve disengage check while in a loop.

# 7/3/2025 Stumpii: Small improvements.
 - Added Russian localisation file.
 - Added language selection for OCR.
 - Added localisation to nav panel.
 - Added TCE Integration class.
 - Added OCR to station services screen check.
 - Added fix for Robigo issue not selecting system in gal map.
 - Improved debug for gal map.
 - Separated Station Services and Construction Services because OCR only works for Station Services (Construction Services are not as slow to open).
 - Moved docking cleanup to Nav Panel class.
 - Added OCR test class.
 - Test code for gal map.
 - Prevent gal map being opened twice for no reason.
 - Added region scaling for stations.
 - Added EDNavigationPanel.py for navigation panel code.
 - Disabled build-executable.yml as it always fails.

# 6/1/2025 Stumpii: Bug fix.
 - Removed 'deprecated' warning that does not work in old python versions.

# 5/30/2025 Stumpii: Various minor updates. 
 - Added check for disengage while in target align.
 - Log new file on each startup of EDAP. Store previous runs.
 - Increase scroll up time for buy/sell to make sure at top of list.
 - Attempt to improve status.json file reading that sometimes results in a file error.

# 5/28/2025 Stumpii: Various minor updates.
 - Added cobra-mk5 config file.
 - Added galaxy and system map selection to EDMesg server.
 - Allow more target align tires.
 - Updated waypoints to new format. Removed some no longer required.
 - Renamed capture_region as there was a duplicate.
 - Added debug and improvment to gal map.
 - Changed log message to avoid double timestamp and unnecessary text. Cleans up log file.

# 5/24/2025 Stumpii: Check update crash
 - Fix crash when checking for updates.
 - Updated version.

# 5/20/2025 Stumpii: Waypoints
 - Added new waypoint system. NOTE: This breaks compatibility with the old waypoints, so needs any existing waypoint to be remade.
 - Added EDMesg system.
 - Enabled target occlusion.
 - Added localisation for OCR.
 - A whole slew of other changes. Too many to mention.
 - This has a number of new modules added, so update python modules.

# 4/26/2025 Stumpii: Minor updates.
- Added support for negative sunpitch times.
- Added docking retries to GUI.
- Added better logging for docking and return to nav tab.
- Added reload of templates after calibration.

# 4/8/2025 Stumpii: Added Corsair.
 - Added Corsair to ED_Data and ship config.
 - 
# 3/31/2025 Stumpii: Flags2 bug fix.
 - Added None check for Flags2 giving error when ED is not running.
 - Moved new auto property to the end of the config. Set default value.
 
# 3/30/2025 DopeEx
 - Added DSS Assist mode - activates DSS scanner when changing system with manual jump
 - Added automatic logout to the main menu option when the FSD assist has arrived at the destination and the destination is in space

# 3/30/2025 Stumpii: Minor updates.
 - SCO without OCR, using Status.json
 - Made honk global to prevent premature disabling in fast ships (Dolphin)
 - Added FSD SCO Active flag to status parser.
 - Added time delta and destination data to status parser and simplified general code.
 - Added glide detection for SC Assist to planet surface.

# 3/10/2025 Stumpii: Added System Colonisation Ship support into waypoint system
 - Added System Colonisation Ship support into waypoint system.
 - Updated waypoints doc with new feature.
 - Add compass scaling to test routines.

# 3/9/2025 Stumpii
 - Added logging of key name (key_a) to send log.
 - Modified FSD Jump logic to better handle Braben Tunnels.
 - Changed logging of callbacks to stop assists.
 - Added timestamp to autopilot log.

# 3/8/2025 Stumpii
 - Added button to load TCE (Trade Computer Extension) destination.
 - Added hyperlink to TCE for those that do not know of it.
 - Moved Honk to start when entering a system instead of when leaving to allow commanders to cancel FSD Assist if there is something interesting in the system.
 - Updated requirements text to include Pillow 10.4.

# 3/5/2025 Stumpii
 - Added single waypoint assist feature. A couple of text boxes and checkbox on the debug screen allow you to enter the system name to go to and then check the box to start your travels to that system.
 - Fix to gal map send key that accepts hex values only, not string.
 - Tweak to journal to remove all the if checks when only one type of event may occur at a time.
 - Changed camyaw to cam zoom and added explanation why the shortcut works.
 - Added alt, lat and longitude to status parser for future angle of approach calc.
 - Added NavRouteParser for NavRoute.json files.
 - Added CargoParser for Cargo.json files.
 - Added MarketParser for Market.json files.
 - Added voice messages to assist routines.

# 3/4/205 SumZer0
 - Updated EDKeys.py to add back in the keyboard binding name to the autopilot.log file instead of just the keyboard scancode.  Also handle KeyError exception when dumping bindings to log file

# 3/2/205 Stumpii: Compass update and OCR fix for high CPU
 - Removed the OCR detection of SCO as it was using high CPU. Now it will only use OCR when the disengage template is detected.
 - Lowered discharge threshold so that the discharge template will detect both disengage and sco and use OCR to determine which is active.
 - Added navpoint-behind template and image to detect when nav point is behind us.
 - Added rotate right and yaw right control as nav logic can use both now.
 - Added python 3.9 support to EDKeys update.
 - Added auto activate ED back into EDKeys (was removed in last update).
 - Added CamZoomIn for Gal Map to remove mouse click in the future.
 - Added SCO FSD detection to journal.
 - Added timestamp to status parser.
 - Added log if jumping and not in analysis mode.

# 2/28/2025 DGotshalk/SumZer0
 - Update EDKeys.py
 - Update to EDKeys.py to import the environ module

# 2/1/2025 RatherRude
 - Support all buttons on all keyboard layouts
 - Add hold key, add multiple buttons, add Support for all buttons on all keyboard layouts

# 1/6/2025 Stumpii: Undock from planetary surface
 - Added undocking from planetary surface (i.e. takeoff when not at a docking station). Ship will thrust up, toggle landing gear, rotate roughly 90 deg, boost and SCO out of orbit.
 - Added extra key bindings for undocking.

# 1/6/2025 Stumpii: OCR for SCO detection
 - Added OCR routine.
 - Added SCO active detection using OCR. Detection is performed on a separate thread to prevent the main loop being delayed for processing.
 - Added SCO deactivation is SCO is active and we are low on fuel or high on temperature.
 - Updated requirements for PaddleOCR.
 - Added separate color filter range for SCO text.

# 1/5/2025 Stumpii: Separated target and compass calibration
 - Separated compass from target calibration.
 - Added ship config file that will hold ship data.
 - Moved calibrated screen scaling from resolution file to settings file.
 - Increased range of compass region for the Mandalay.
 - Added additional methods for overlays to add item as rectangle and also to remove overlay items.
 - Updated requirements text file.

# 12/13/2024 Stumpii: Added Cobra Mk V and ship detection
 - Added Cobra Mk V to data file.
 - Fixed defaulting of new AP.json properties on startup.
 - Added AP engine loop delay until GUI started to prevent error logging to listbox too early.
 - Added detection of ship on startup and on journal change.
 - Added warning of no fuel scoop or autopilot on start and on ship change.
 - Added new callback option of log and voice to try to reduce the redundant logging code.
 - Added journal code to return full ship names.
 - Added journal detection of fuel scoop.
 - Added journal modified date detection to avoid reading journal when it has not changed.
 - Added word replacement for some words that are not pronounced correctly by voice engine.

# 11/27/2024 Stumpii: Various minor changes.
 - Fixed minor issue with interdiction timing that would occasionally cause SCO trigger coming out of interdiction.
 - Added detection of other SC drop locations that do not need a request to dock.
 - Get lower case of ship name as journal is inconsistent in places.


# 11/17/2024 Stumpii: Improved launch from planetary base.
 - Updated Mandalay and Python MkII ship turn values.
 - Set voice enable/disable based on loaded setting. Gets rid of the 'Welcome to' speach if voice disabled.
 - Added improved launch from planetary base. Will now head out 90 deg from planet, SC and SCO until out of orbit.
 - Updated status flags.

# 11/10/2024 Stumpii: Various changes.
 - Added SupercruiseDestinationDrop to determine if we drop at signal source and cannot request docking.
 - Only log journal on change, not every request.
 - Removed logging of statusparser.json file timestamp changes.
 - Added Elite Window check.
 - Added option to screen to allow alternate image for testing.
 - Added a couple of screen functions need for OCR.

# 11/3/2024 Stumpii: Added test buttons for ship calibration.
 - Added test buttons for ship calibration.
 - Updated Mandalay.

# 11/2/2024 Stumpii: Added Mandalay.
 - Added Mandalay.

# 10/28/2024 Stumpii: Minor debug additions.
 - Minor debug additions.

# 10/22/2024 Stumpii: Minor updates.
 - Minor updates.

# 10/20/2024 Stumpii: Added logging.
 - To aid debugging, status bar updates are written to the gui log. Also gui log updates are written to the autopilot log.

# 10/13/2024 Stumpii: Fixed FuelScoop detection.
 - Change fuelscoop detection from ModulesInfo.json to the Journal because ModulesInfo.json was not updated by the game enough to be useful.

# 10/6/2024 Stumpii: Various changes:
 - Added status flags and status parser for processing Status.json file.
 - Change interdiction check to check Status.json instead of Journal and image matching.
 - Added interdiction checks when avoiding sun and fuel scooping.
 - Force module into updates by going to the interior panel before undocking.
 - Updated screen region to use the correct monitor.
 - Added code to allow Python 3.9 and maybe earlier to run correctly with a workaround for the changes that use new features.

# 9/30/2024 Stumpii: Various changes:
 - Added ship type and ship size to the journal and ship status.
 - Added ED_data file for constants.
 - Added ModulesInfoParser to detect if fuel scoop is installed. The other parsers will be added as needed.
 - Removed setting speed to 100% when target lost as this happen when target is in front and causes gravity well message.
 - Removed time delay on SC disengage as it was sometimes too slow and overshooting the station.
 - Detection of monitor > 1 and identify which monitor ED is on.

# 9/10/2024 Updated docs and minor fixes.
 - Stumpii: Correction to mouse click.
 - Stumpii: Add hotkey data entry on GUI for Robigo Assist (Pg Up) which is not shown anywhere.
 - Stumpii: Updated docs.

# 8/20/2024 Added debug options to GUI.
 - Stumpii: Added debug/test tab to GUI.
 - Stumpii: Added debug options and log file open to the GUI to make for easier troubleshooting.

# 8/19/2024 Improved calibration and overlay features.
 - Stumpii: Added Floating Test option to the Overlay class to be able to write text anywhere on the screen.
 - Stumpii: Added Clear method to the Overlay class to clear all overlay items.
 - Stumpii: When overlay checkbox unchecked, overlay now clears. The checkbox said restart required, but that does not appear to be the case.
 - Stumpii: Improved text for calibration popup.
 - Stumpii: When performing calibration, the compass and target regions are shown as well as the current and bast matches.
 - Stumpii: Changed regions test function to display all the regions wanted on the Elite client screen.
 - Stumpii: For regions test, the region name is printed within the region box (the reason floating text was added to the Overlay class).

# 8/18/2024 Cleanup - in prep for additional testing changes.
 - Stumpii: Moved most threshold values to Screen_Regions for consisancy throughout the program and match coded and display values.
 - Stumpii: Cleaned up many comments.
 - Stumpii: Moved the one test routine out to its own file. Added more test routines. These are described in the Test_Routines.py file.

# 8/17/2024 New ships and auto focus
 - Stumpii: Added configs for the two new ships (Python Mk2 and Type-8).
 - Stumpii: Added option to refocus Elite client window before each new key press to avoid sending keys to an unwanted window.

# 6/24/2024 Update
 - Stumpii: Added undocking if necessary to start of supercruise assist.
 - Stumpii: Removed speed demands from the nav alignment code. Nav align should just do the alignment, the calling function determine what to do if alignment is successful or not. All but one of the calling routines sets the speed after calling the routine anyway.
 - Stumpii: sc_assist no longer spams 50% speed every iteration of its loop. So pilot is free to control the speed and just let AP do the alignment. Works great for manual 75% throttle at 0:07 from target and when using new SCO in SC.
 - Stumpii: sc_target_align now returns false if the target was found and now is lost and as no other cause was captured, then we went past the target.
 - Stumpii: While in SC, if we fly past the target, keep going for 5 secs, then slow to 50% and turn around using nav_align.

# 6/23/2024 Targetting update
- Stumpii provided change to Nav Offset to include Z axis where Z=+1 for target ahead and Z=-1 for target behind. Use the data to navigate to the target quicker when the target is behind us (pitch up or down depending if target is above/below us).

# 8/6/23 latest mss library causing crash
- if you are seeing:  AttributeError: '_thread._local' object has no attribute 'srcdc'   then you need to downgrade the mss library.  Updated the requirements.txt file accordingly
- pip install mss==8.0.3

# 6/25/2023 Update by EpicStuff
- Made it so that the state of Enable_CV_View is saved to configs/AP.json and loads previously loaded ship config on start.
also autoformatting (removed trailing whitespaces)

# 12/7/2022 Update
- Update to support ED 4.0 menu layout, so this AP works with both Odyssey and Horizon 4.0
- Waypoint processing, after adding System name in Galaxy Map had to add a Mouse click center screen so that keybindings would work when selecting Plot Route icon
- Robigo had to add a setSpeed50 after coming out of FSD in Sothis.  Still some issues with some users where the Robigo loop cannot find Siruis Atmos in the left menu
- No EDAPGui.exe in this update, if there is a demand for it then will make a formal released version

# 05/30/2022 Update
- V1.1.0 Release which includes EDAPGui.exe.  With the binary, one does not need to install all the python packages

# 05/17/2022 Update
- Added hotkey for starting Robigo as defined in config/AP.json file ("HotKey_StartRobigo": "pgup"). Added ability to only do single loop of Robigo run where user will complete and select missions (see config/AP.json "Robigo_Single_Loop": false)
- With single loop set to True, the Robigo Assist will work in Horizons.
  - CMDR would complete and select Missions, set Route to SOTHIS on GalaxyMap and then start the Robigo AP, which will undock, execute the loop and redock and terminate
  - Additional keybindings are required, see autopilot.log for missing keybindings (such as SelectTarget, Supercruise)

# 05/12/2022 Update
- Added a statemachine to Robigo Mines loop.  Will now determine where your ship is at in the loop and start from there.
  You can then stop the Robigo Assist to handle a Interiction and simply restart it to continue with the loop (it will
  pick up where you left off).  No need to start at Robigo Mines.  See docs/Robigo.md for details

# 05/11/2022 Update
- For Waypoints, the completed state is now updated directly in the wp list.  New option to reset the waypoint completion state via button on the GUI.  The idea is to allow picking up where you left off in your waypoint list.  Also, the loading of a waypoint list has been separated from the activation of the waypoint assist.  (DopeEx is fine tuning the Waypoint system)

# 05/09/2022 Update
- Added the Robigo Mines Passenger Mission autopilot.   See docs/Robigo.md for further details

# 05/07/2022 Update
- Major Gui usability improvements
- Add bookmark as station destination option for waypoints
- If not close enough to the station during the first dock attempt, then another short throttle and reattempt docking request
- Fix missing waypoint assist in ap modes
- Add a new version check and discord and changelog links
- This effort brought to you buy DopeEx

# 05/06/2022 Update - Baselined codebase V1.0

# 05/02/2022 Update - thanks CMDRs for providing these updates
- Fix EDkeys.py to null key modifier if using Secondary binding used (see issue #2)
- Fix AP state to account for undocking from Outposts as opposed to Stations

# 04/28/2022 Update
The goal is to show in the overlay all the info that is needed without having to see the gui or have tts enabled.
The following things have been adjusted:
-	ap mode shows the mode in which the ap is currently running
-	ap status shows the same info as the statusline in the gui (align, maneuver, jump etc.)
-	ship status shows continuously the ship status (before partly in ap mode if no ap mode was active)
-	elw scanner shows if an elw was found

Also, the overlay was sometimes very hard to read, so the default font was changed and the option to change the font itself was added in the config.


# 03/07/2022 Update
- Minor update to the ELW image template to help with accuracy of detection
- Updated the AP.json file and added SunBrightThreshold (set to 125) use to detect Sun in front of ship when jumping into a system
- Updated the code to use the SunBrightThreshold configuration item

# 2/26/2022 Update
- Modified Sun low limit threshold to account for star density when close to core of galaxy
- Enlarged region that looks for Sun in support of sun avoidance
- Fixed jump count total on last jump
- Timing tweaks to account for accasional heating around Sun

# 2/24/2022 Update
- Update to Sun avoidance.  The Sun avoidance looks for brightness at the center of the display to go below 5% to know have pitched
  up sufficiently to go over the Sun.  If close to the core of the galaxy, the star density is high and thus the overall brightness
  of the center of the screen is higher so the ship may continue to pitch further up. Adjusted the brightness criteria to account for this.
  Also, if jumping into a non scoopable star, adjusted the brightness threshold to ensure pitching up/over the Sun works.

# 2/23/2022 Update
- Fixed sun avoidance for dark red/non-scoopable stars, will pitch up properly
- Use different screen grab package (mss) which is about 10x faster than ImageGrab.  New requirements.txt file.
  Must perform:  pip install mss
- The disengage popup "PRESS [J] TO DISENGAGE" image now only looks for "TO DISENGAGE" so user can have any key binding
  they want for that function
- Restructure folder.  Subdirectories now includes:  ships/  configs/  and waypoints/
- Fix issue when Saved Games has been moved out of C:
- Add more useful error for unrecognised key
- Add colour to debug images
- Allow for calibrating of larger screens
- Added Journal trap for interdiction, as well image matching from screen
- Waypoint, fixed undocking from Station


# 2/20/2022 Update
## HOWTO's added:
  - HOWTO-Calibration.md
  - HOWTO-RollPitchYaw.md
  - HOWTO-Waypoint.md

## Configurable Settings
  config-AP.json
    - Aded EnableRandomness flag to adjust sleep times
    - OverlayTextEnable flag to show overlay on ED, prototype
    - OverlayTextYOffset the Y location to put overlay (X hardcoded)
    - OverlayTextFontSize allows you to specify size
    - FuelScoopTimeOut how long to wait in fuel scooping before aborting
    - and others

## Autopilot
  - Added Waypoint Assist  (works both in Odyssey and Horisons)
    - Jumps to Systems defined in waypoints.json (or user selected) file
      - Can dock with a station that is defined in the file also (requires X, Y of mouse to select the
        station from the System Map, this too is a little more complex so see separate HowTo)
        - Added GUI Button "Get X, Y Mouse" to help with determining the StationCoord
      - Once docked can perform trades (somewhat complex to setup, will need separate HowTo), Sells first
        then Buys
      - Auto undock to take you to next waypoint system
      - If last line in the waypoint file is "REPEAT", it will loop to top and do it again, forever, otherwise
        Waypoint assist terminates at the end
  - GUI, in statusline, how shows: Distance Jumped, Jumps/Total Jumps, #Refuels, Sec/Jump
  - GUI, added text field for SunPitchUP+Time (in seconds) which adds this number of seconds after
    sun avoidance to continue pitching up.  If your ship heats up easy (like my Cutter), then you will want
    to add a second or two to be pitch away from the Sun
  - While in SC, check for being interdicted, if so take action (submit, booster away), [initial approach]
  - Optimized number of seconds per jump.   Average just under 60 sec/jump, with fuel scooping once in a while at 70 s/j
  - Added Target Occlusion detection.  As you approach the Station it might suddenly show that
    it is behind the Planet.  This will now be detected and repositioning will occurs to go
    around the planet
  - Tuned color ranges for masking the region for better image template matching.  If using anything other
    than default ED HUD color scheme, this AP will not work at all
  - Handled non FGB FOAM star avoidance when jumping into those Systems (for dim red suns),
    so now won't crashed into those
  - Added journal catch to check if game odyssey, capture distance jumped, jumps remaining
  - Added Galaxy and System Map Open for key binding lookup
  - Added total light years traveled for FSD Route Assist and Waypoint Assit
  - Ship configurations provided that contain the values Roll, Pitch, and Yaw for various type ships
    (Only DBX, APSX, Cutter, and Sidewinder tested)

## Update requirements.txt file
  - One new packages is required to be installed, pynput==1.7.6, to support mouse click
