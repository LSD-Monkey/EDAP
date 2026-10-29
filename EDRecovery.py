from __future__ import annotations

"""
Fail-safe for Waypoint Assist / trade routes ('WaypointNeverStop'). Waypoint Assist does not stop any more when
something goes wrong, it escalates:

  1. 'WaypointRecoveryJumps' times (default 3): jump to a neighbour system, the waypoint loop then flies back and
     navigates again (a new instance of the system, new Nav Panel list, new docking queue, ...).
  2. Still failing: jump out of the system and wait 'WaypointRecoveryWait' minutes (default 30), then try again.
  3. Still failing after the wait: start another trade route ('WaypointRecoveryNewRoute') found with the filters of
     the Trade tab, around the current system, without the stations of the failed route.
  The stages start again as soon as a waypoint is completed.

Low fuel (route check or below 'RefuelStopPercent' during the jumps): fly to the nearest station with a fitting
landing pad, dock (EDAP refuels and repairs on docking), then continue the route.

Game not playable (main menu, connection lost, closed): wait until it is playable again instead of stopping.
A STOP by the user always stops.
"""

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from time import sleep

from EDAP_data import FlagsBeingInterdicted, FlagsDocked, FlagsSupercruise
from EDlogger import logger

SORT_KEYS = {
    "Profit per hour": ('profit_hour', True),
    "Profit per trip": ('profit_trip', True),
    "Distance between stations": ('distance', False),
    "Distance to start": ('dist_to_start', False),
}


def _is_interrupt(e: BaseException) -> bool:
    """ EDAP_Interrupt / EDAP_GameNotRunning (STOP by the user, game gone) must never be swallowed. """
    return any(c.__name__ in ('EDAP_Interrupt', 'EDAP_GameNotRunning') for c in type(e).__mro__)


class WaypointRecovery:
    def __init__(self, ap):
        self.ap = ap
        self.stage_jumps = 0  # jump out/back attempts in the current stage
        self.waited = False  # the long wait was done in this stage
        self.last_progress = None
        self.failed_targets: set[str] = set()  # neighbour systems that could not be reached
        self.bad_stations: set[str] = set()  # stations of routes given up (not chosen for a new route)

    # ------------------------------------------------------------------------------------------------------------
    def log(self, msg: str, voice: bool = False):
        self.ap.ap_ckb('log+vce' if voice else 'log', msg)

    def _cfg(self, key, default):
        try:
            return type(default)(self.ap.config.get(key, default))
        except Exception:
            return default

    def _state(self) -> dict:
        return self.ap.jn.ship_state()

    def _journal_dir(self) -> str | None:
        cur = getattr(self.ap.jn, 'current_log', None)
        return os.path.dirname(cur) if cur else None

    def reset(self):
        self.stage_jumps = 0
        self.waited = False

    def _check_progress(self):
        p = getattr(self.ap.waypoint, 'progress_cnt', 0)
        if self.last_progress is not None and p != self.last_progress:
            logger.debug("fail-safe: waypoint progress since the last failure, stages reset")
            self.reset()
        self.last_progress = p

    # ------------------------------------------------------------------------------------------------------------
    def handle_failure(self, reason: str | None):
        """ Called by the engine when Waypoint Assist aborted. Does the next fail-safe step and returns; the
        engine then starts Waypoint Assist again. """
        reason = reason or 'unknown'
        self._check_progress()
        self.ap.update_ap_status("Fail-safe")

        # A failure is often a 'CONNECTION ERROR' dialog on screen (the journal/status do not always show it)
        if not self.ap.game_is_playable() or self._connection_error_on_screen():
            self.wait_for_game()
            return

        if reason == 'low_fuel':
            if not self.refuel_stop():
                # No station found / not reachable: treat like any other failure
                reason = 'refuel stop failed'
            else:
                return

        # Docking refused for good (carrier with restricted docking access, too large, hostile): jumping out and
        # back or waiting does not help, take another route at once.
        if any(k in reason for k in ('RestrictedAccess', 'TooLarge', 'Hostile', 'Offences')) and \
                self._cfg('WaypointRecoveryNewRoute', True):
            self.log(f"Fail-safe: docking not possible ({reason}). Searching another trade route.", True)
            if self.start_new_route():
                self.reset()
                return

        n = max(1, self._cfg('WaypointRecoveryJumps', 3))
        if self.stage_jumps < n:
            self.stage_jumps += 1
            self.log(f"Fail-safe {self.stage_jumps}/{n} ({reason}): jumping to a neighbour system, then back and "
                     f"trying again.", True)
            if not self.jump_out():
                self.log("Fail-safe: could not jump out, trying again in 30 s.")
                sleep(30)
            return

        wait_min = max(1, self._cfg('WaypointRecoveryWait', 30))
        if not self.waited:
            self.log(f"Fail-safe: still failing after {n} attempts ({reason}). Leaving the system and waiting "
                     f"{wait_min} minutes.", True)
            self.jump_out()
            self.wait_minutes(wait_min)
            self.waited = True
            return

        # Still failing after the wait
        if self._cfg('WaypointRecoveryNewRoute', True):
            self.log(f"Fail-safe: still failing after the wait ({reason}). Searching another trade route.", True)
            if self.start_new_route():
                self.reset()
                return
            self.log("Fail-safe: no other trade route found.", True)
        self.log(f"Fail-safe: waiting {wait_min} minutes, then starting again.", True)
        self.wait_minutes(wait_min)
        self.stage_jumps = 0

    # ------------------------------------------------------------------------------------------------------------
    def wait_for_game(self):
        """ The game is not playable (main menu, connection lost, closed): reconnect ('AutoReconnect', the sequence
        of the recording 2026-10-22 11:49) or wait until it is playable again. """
        self.log("Fail-safe: game not in flight (connection error, main menu or closed). "
                 + ("Reconnecting." if self._cfg('AutoReconnect', True) else
                    "Waiting until it is playable again (STOP to cancel)."), True)
        t0 = time.time()
        last_log = t0
        attempt = 0
        next_try = 0.0
        while True:
            self.ap.update_ap_status(f"Waiting for the game ({int((time.time() - t0) / 60)} min)")
            try:
                if self.ap.game_is_playable() and not self._connection_error_on_screen(quick=True):
                    break
            except Exception as e:
                if _is_interrupt(e):
                    raise
            if self._cfg('AutoReconnect', True) and time.time() >= next_try:
                attempt += 1
                try:
                    if self.reconnect(attempt):
                        break
                except Exception as e:
                    if _is_interrupt(e):
                        raise
                    logger.exception("reconnect")
                    self.log(f"Reconnect failed: {e}")
                # Servers down for longer: try again after 1, 2, 4 ... max. 10 minutes
                next_try = time.time() + min(600, 60 * 2 ** min(attempt - 1, 4))
            if time.time() - last_log > 600:
                last_log = time.time()
                self.log(f"Fail-safe: still waiting for the game ({int((time.time() - t0) / 60)} min).")
            sleep(10)
        self.log("Game is playable again, continuing Waypoint Assist in 15 s.", True)
        sleep(15)
        self._after_login()

    def _after_login(self):
        """ After a login the ship is never in supercruise (normal space, or docked): reset what EDAP remembered
        from before the logout, so the route starts with 'enter supercruise' and not with SC actions. """
        ap = self.ap
        try:
            ap.stop_sco_monitoring()
        except Exception as e:
            if _is_interrupt(e):
                raise
        ap._launched_early = False
        try:
            st = ap.jn.ship_state()
            docked = ap.status.get_flag(FlagsDocked)
            if not docked:
                st['status'] = 'in_space'
            st['interdicted'] = False
            st['sc_exit_body_type'] = ''
            st['SupercruiseDestinationDrop_type'] = None
            in_sc = ap.status.get_flag(FlagsSupercruise)
            self.log("After login: " + ("docked." if docked else
                                        ("in supercruise." if in_sc else "normal space, not in supercruise.")))
            if not docked and not in_sc:
                ap.set_throttle_0()
        except Exception as e:
            if _is_interrupt(e):
                raise
            logger.warning(f"after login: {e}")

    # --- Reconnect --------------------------------------------------------------------------------------------
    # Recording 2026-10-22 11:49:
    #   1. 'CONNECTION ERROR - Could not connect to transaction server. Press OK to return to the main menu.' with OK
    #      selected -> UI_Select. 'LOADING GAME' ~35 s, then the main menu (journal: Music 'MainMenu').
    #   2. Main menu: CONTINUE is the top item -> UI_Up a few times, UI_Select.
    #   3. Game mode screen: OPEN PLAY | PRIVATE GROUP | SOLO PLAY | ARENA | TRAINING, OPEN PLAY highlighted.
    #      UI_Right 2x = SOLO PLAY. While the cards show 'CAN'T CONNECT TO FRONTIER SERVERS' a select does
    #      nothing; once the servers are back the cards turn orange and UI_Select loads the game (journal:
    #      'Commander', 'LoadGame' ~30 s later).
    MODE_INDEX = {'open': 0, 'open play': 0, 'solo': 2, 'solo play': 2}

    def _ocr_screen(self, rect=(0.15, 0.15, 0.85, 0.85), scale: float = 1.0) -> str:
        """ Upper case text of a screen region without spaces ('' if not readable). scale < 1 makes the OCR of
        large regions much faster (big menu texts stay readable). """
        try:
            img = self.ap.scr.get_screen_rect_pct(list(rect))
            if img is not None and scale != 1.0:
                import cv2
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            txt = self.ap.ocr.image_simple_ocr(img, 'reconnect') if img is not None else None
        except Exception as e:
            if _is_interrupt(e):
                raise
            logger.debug(f"reconnect OCR: {e}")
            return ''
        joined = re.sub(r'[^A-Z]', '', " ".join(str(t) for t in (txt or [])).upper())
        logger.debug(f"Reconnect OCR: {joined[:200]}")
        return joined

    def _connection_error_on_screen(self, quick: bool = False) -> bool:
        if not self._cfg('GameConnectionCheck', True):
            return False
        if quick and self.ap.game_is_playable():
            # only look when something else hints at a problem (OCR is slow)
            return False
        t = self._ocr_screen((0.25, 0.25, 0.75, 0.75))
        return any(m in t for m in ('CONNECTIONERROR', 'RETURNTOTHEMAINMENU', 'COULDNOTCONNECT',
                                    'VERBINDUNGSFEHLER'))

    def _journal_events_since(self, since_utc: float, names: tuple[str, ...]) -> bool:
        """ True if one of the journal events was written after since_utc (epoch). """
        try:
            from datetime import datetime
            path = self.ap.jn.get_latest_log() or self.ap.jn.current_log
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 16384))
                lines = f.read().decode('utf-8', errors='ignore').splitlines()
            for line in reversed(lines):
                if not any(f'"{n}"' in line for n in names):
                    continue
                try:
                    ev = json.loads(line)
                    ts = datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp()
                except Exception:
                    continue
                if ev.get('event') in names and ts >= since_utc - 2:
                    return True
        except Exception as e:
            logger.debug(f"journal events: {e}")
        return False

    def _wait_main_menu(self, timeout: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.ap._journal_tail_game_state() == 'main_menu':
                return True
            sleep(2)
        return False

    # --- Respawn after the ship was destroyed ----------------------------------------------------------------------
    # Recording 2026-10-22 17:44 (Type-9 crashed into the planet George Pantazis A 6, journal 'Died', then Music
    # 'MainMenu'):
    #   1. INCIDENT REPORT: buttons 'EXIT TO MAIN MENU' | 'CONTINUE' at the bottom -> UI_Right (CONTINUE), UI_Select.
    #   2. REDEPLOYMENT SUMMARY: VESSEL SELECTION highlighted -> UI_Right (REDEPLOY LOCATION), UI_Down (FINANCIAL
    #      SUPPORT), UI_Right (REDEPLOY button), UI_Select -> 'CONFIRM AND REDEPLOY' highlighted -> UI_Select.
    #   3. Journal 'Resurrect' (Option 'rebuy'), 'Location' docked at the redeploy station ~8 s later.
    def died_pending(self) -> bool:
        """ True if the journal shows 'Died' after the last 'Resurrect'/'LoadGame'. """
        try:
            path = self.ap.jn.get_latest_log() or self.ap.jn.current_log
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().decode('utf-8', errors='ignore').splitlines()
        except Exception:
            return False
        for line in reversed(lines):
            if '"event":"Resurrect"' in line.replace(' ', '') or '"event":"LoadGame"' in line.replace(' ', ''):
                return False
            if '"event":"Died"' in line.replace(' ', ''):
                return True
        return False

    def respawn(self, attempt: int = 1) -> bool:
        """ Rebuy screens as in the recording 2026-10-29 14:22 (the ship selection is never opened):
          SHIP DESTROYED ........ CONTINUE is selected -> UI_Select
          INCIDENT REPORT ....... ~5 s 'LOADING REPORT' (title already shown, keys would be lost), then CONTINUE is
                                  highlighted -> UI_Right (stays on CONTINUE), UI_Select
          REDEPLOYMENT SUMMARY .. VESSEL SELECTION highlighted -> UI_Right, UI_Down, UI_Right to the REDEPLOY button.
                                  Each step is checked with the highlight (orange block): UI_Select only when the
                                  REDEPLOY button is highlighted. A UI_Select on VESSEL SELECTION opened CHOOSE VESSEL
                                  before, and its UI_Right chose GET FREE SHIP (5 Type-9 lost, 2026-10-27/29).
          CONFIRM AND REDEPLOY .. UI_Select
        Only small regions are read with OCR (the full screen took 60 s). """
        ap, keys = self.ap, self.ap.keys
        self.log(f"The ship was destroyed. Rebuy and redeploy (attempt {attempt}).", True)
        ap.update_ap_status(f"Respawn ({attempt})")
        t0 = time.time()
        allow_free = bool(self._cfg('RespawnAllowFreeShip', False))
        while time.time() - t0 < 240:
            if not self.died_pending():
                break  # 'Resurrect' written
            title = self._ocr_screen((0.0, 0.0, 0.6, 0.14), scale=0.5)
            if 'CHOOSEVESSEL' in title:
                self.log("Respawn: ship selection open, leaving it without a choice (UI_Back).")
                keys.send('UI_Back')
                sleep(2)
                continue
            if 'REDEPLOYMENTSUMMARY' in title:
                bottom = self._ocr_screen((0.5, 0.7, 1.0, 1.0), scale=0.5)
                if 'CONFIRMANDREDEPLOY' in bottom:
                    self.log("Respawn: confirm and redeploy.")
                    keys.send('UI_Select')
                    sleep(4)
                    continue
                if self._summary_is_free_ship() and not allow_free:
                    self.log("Respawn: the redeployment offers only the FREE Sidewinder (own ship lost / rebuy not "
                             "affordable?). Not confirming, please decide in the game.", True)
                    sleep(30)
                    continue
                if self._goto_redeploy_button():
                    keys.send('UI_Select')  # REDEPLOY -> 'CONFIRM AND REDEPLOY'
                    sleep(2)
                else:
                    sleep(2)
                continue
            if 'INCIDENTREPORT' in title:
                box = self._highlight_box()
                if box is None or box[4] < 3.0:
                    sleep(1.5)  # 'LOADING REPORT': no button yet
                    continue
                keys.send('UI_Right')  # CONTINUE (right of 'EXIT TO MAIN MENU')
                sleep(0.6)
                keys.send('UI_Select')
                sleep(4)
                continue
            centre = self._ocr_screen((0.25, 0.25, 0.75, 0.8), scale=0.5)
            if 'SHIPDESTROYED' in centre or 'DESTROYED' in centre:
                keys.send('UI_Select')  # CONTINUE
                sleep(4)
                continue
            logger.debug(f"respawn: screen not recognised ({(title + '|' + centre)[:100]})")
            sleep(2)
        # Wait for the new ship
        while time.time() - t0 < 300:
            if not self.died_pending() and ap.game_is_playable():
                sleep(5)
                st = ap.jn.ship_state()
                option = self._last_resurrect_option()
                self.log(f"Redeployed ({option}) at {st.get('cur_station') or '?'} ({st.get('cur_star_system') or '?'}) "
                         f"in a {st.get('type') or '?'}. The cargo is lost.", True)
                if option == 'free' and not allow_free:
                    # Never fly a trade route in a free Sidewinder (it died 4 more times on 2026-10-27)
                    self.log("Redeployed in a FREE ship, the own ship is lost. Waypoint Assist stops, please check "
                             "the shipyard.", True)
                    from ED_AP import EDAP_Interrupt
                    raise EDAP_Interrupt()
                return True
            sleep(3)
        self.log("Respawn: not back in the ship yet, trying again.")
        return False

    def _highlight_box(self):
        """ The highlighted menu element = the largest solid orange block on the screen.
        Returns (cx, cy, w, h, aspect) in screen fractions, or None. """
        try:
            import cv2
            import numpy as np
            img = self.ap.scr.get_screen_rect_pct([0.0, 0.0, 1.0, 1.0])
            if img is None:
                return None
            img = cv2.resize(img, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)[:, :, :3].astype(int)
            a, b, c = img[:, :, 0], img[:, :, 1], img[:, :, 2]
            mid = (b > 60) & (b < 180)
            mask = (((a > 190) & mid & (c < 90)) | ((c > 190) & mid & (a < 90))).astype(np.uint8)
            n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            if n <= 1:
                return None
            i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            x, y, w, h, area = stats[i]
            H, W = mask.shape
            if area < 0.0015 * H * W:
                return None
            return ((x + w / 2) / W, (y + h / 2) / H, w / W, h / H, (w / W * W) / max(1, h))
        except Exception as e:
            if _is_interrupt(e):
                raise
            logger.debug(f"highlight box: {e}")
            return None

    def _is_redeploy_highlighted(self, box) -> bool:
        # REDEPLOY: wide flat button on the right (tiles are about square, 'BACK TO REPORT' is on the left)
        return box is not None and box[4] > 4.0 and box[0] > 0.5 and box[1] > 0.7

    def _goto_redeploy_button(self) -> bool:
        """ From VESSEL SELECTION (highlighted after loading): right, down, right. Checked after every key, never
        a UI_Select here. """
        keys = self.ap.keys
        box = None
        for _ in range(10):
            box = self._highlight_box()
            if box is not None:
                break
            sleep(0.5)  # tiles still loading
        # (box None: a white highlighted tile, e.g. REDEPLOY LOCATION - the moves below still lead to REDEPLOY)
        moves = ['UI_Right', 'UI_Down', 'UI_Right', 'UI_Down', 'UI_Right', 'UI_Down', 'UI_Right']
        for k in [None] + moves:
            if k:
                keys.send(k)
                sleep(0.6)
                box = self._highlight_box()
            if self._is_redeploy_highlighted(box):
                return True
        logger.debug(f"respawn: REDEPLOY button not reached (highlight {box})")
        return False

    def _summary_is_free_ship(self) -> bool:
        """ REDEPLOYMENT SUMMARY / confirmation: is the free Sidewinder selected? (vessel tile and the warning
        'CHOOSING A FREE SIDEWINDER WILL CAUSE THE PERMANENT LOSS OF YOUR DESTROYED SHIP') """
        t = self._ocr_screen((0.0, 0.12, 0.7, 0.9), scale=0.5)
        return 'CHOOSINGAFREE' in t or 'PERMANENTLOSS' in t or ('SIDEWINDER' in t and 'FREE' in t)

    def _last_resurrect_option(self) -> str:
        try:
            path = self.ap.jn.get_latest_log() or self.ap.jn.current_log
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().decode('utf-8', errors='ignore').splitlines()
            for line in reversed(lines):
                if '"Resurrect"' in line:
                    return json.loads(line).get('Option', '?')
        except Exception:
            pass
        return '?'

    def reconnect(self, attempt: int = 1) -> bool:
        """ Connection error dialog -> main menu -> CONTINUE -> game mode -> load the game. Returns True when the
        ship is back (Status.json flags). """
        ap, keys = self.ap, self.ap.keys
        try:
            from Screen import set_focus_elite_window
            set_focus_elite_window()
        except Exception:
            pass
        # Ship destroyed (journal 'Died', e.g. crashed into a planet): the rebuy screens, not the main menu
        if self.died_pending():
            return self.respawn(attempt)
        state = ap._journal_tail_game_state()
        if state == 'shutdown':
            self.log("Reconnect: the game was closed, it can not be started by EDAP. Waiting.")
            return False
        self.log(f"Reconnect attempt {attempt}.")
        ap.update_ap_status(f"Reconnecting ({attempt})")

        # 1. Connection error dialog: OK
        if state != 'main_menu':
            if self._connection_error_on_screen():
                self.log("Reconnect: 'CONNECTION ERROR' shown, pressing OK.", True)
                keys.send('UI_Select')
            elif not ap.game_is_playable():
                # No dialog read, but not in the game (e.g. dialog in another language): OK is selected anyway
                keys.send('UI_Select')
            else:
                return True
            if not self._wait_main_menu(180):
                self.log("Reconnect: main menu not reached.")
                return ap.game_is_playable()
            sleep(5)  # menu fades in

        # 2. Main menu: CONTINUE (top item)
        keys.send('UI_Up', repeat=6)
        sleep(0.8)
        keys.send('UI_Select')
        sleep(4)
        txt = self._ocr_screen((0.0, 0.2, 1.0, 0.9))
        if not any(m in txt for m in ('SOLOPLAY', 'OPENPLAY', 'PRIVATEGROUP', 'ARENA')):
            # Not the game mode screen (another menu item was selected?): back and try again next time
            self.log("Reconnect: game mode screen not found, back to the main menu.")
            keys.send('UI_Back')
            sleep(2)
            return False

        # 3. Game mode: Solo (default) or Open
        idx = self.MODE_INDEX.get(str(ap.config.get('ReconnectMode', 'Solo')).lower(), 2)
        keys.send('UI_Left', repeat=5)
        sleep(0.5)
        if idx:
            keys.send('UI_Right', repeat=idx)
        sleep(1)

        # 4. Select until the game loads (servers may need a while to come back)
        t0 = time.time()
        logged_servers = False
        while time.time() - t0 < 300:
            if self._journal_events_since(t0, ('Commander', 'LoadGame')):
                break
            keys.send('UI_Select')
            sleep(8)
            if self._journal_events_since(t0, ('Commander', 'LoadGame')):
                break
            if not logged_servers and 'CANTCONNECT' in self._ocr_screen((0.0, 0.2, 1.0, 0.9)):
                logged_servers = True
                self.log("Reconnect: 'CAN'T CONNECT TO FRONTIER SERVERS', waiting for the servers.", True)
        else:
            self.log("Reconnect: the game did not load within 5 minutes, back to the main menu.")
            keys.send('UI_Back')
            return False

        self.log("Reconnect: game is loading.", True)
        t1 = time.time()
        while time.time() - t1 < 180:
            sleep(3)
            if ap.game_is_playable():
                sleep(5)
                self.log("Reconnect: back in the ship.", True)
                return True
        self.log("Reconnect: game loaded, but the ship state is not back yet.")
        return ap.game_is_playable()

    def wait_minutes(self, minutes: float):
        """ Waits with throttle 0; reacts on interdictions. """
        try:
            self.ap.set_throttle_0()
        except Exception as e:
            if _is_interrupt(e):
                raise
        end = time.time() + minutes * 60
        while time.time() < end:
            left = int((end - time.time()) / 60) + 1
            self.ap.update_ap_status(f"Fail-safe: waiting {left} min")
            try:
                if self.ap.status.get_flag(FlagsBeingInterdicted):
                    self.ap.interdiction_check()
                    self.ap.set_throttle_0()
            except Exception as e:
                if _is_interrupt(e):
                    raise
                logger.warning(f"fail-safe wait: {e}")
            sleep(5)

    # ------------------------------------------------------------------------------------------------------------
    def _plot_and_jump(self, system: str) -> bool:
        ap = self.ap
        ap._launched_early = False
        if not ap.galaxy_map.set_gal_map_destination_text(ap, system, ap.jn.ship_state, force=True):
            self.log(f"Fail-safe: could not target {system} in the Galaxy Map.")
            return False
        ap.keys.send('TargetNextRouteSystem')
        ok = ap.jump_to_system(ap.scrReg)
        cur = (self._state().get('cur_star_system') or '').upper()
        return bool(ok) and cur == system.upper()

    def jump_out(self) -> bool:
        """ Jumps to a neighbour system (the waypoint loop flies back afterwards). """
        cur = (self._state().get('cur_star_system') or '').upper()
        for target in self.neighbour_systems(cur):
            if target.upper() in self.failed_targets:
                continue
            self.log(f"Fail-safe: jumping to {target}.")
            try:
                if self._plot_and_jump(target):
                    return True
            except Exception as e:
                if _is_interrupt(e):
                    raise
                logger.warning(f"fail-safe jump to {target}: {e}")
            self.failed_targets.add(target.upper())
            if (self._state().get('cur_star_system') or '').upper() != cur:
                return True  # left the system anyway
        self.failed_targets.clear()
        return False

    def neighbour_systems(self, cur: str) -> list[str]:
        """ Systems one jump away: the system we came from (journal), then the nearest systems from EDSM. """
        out = []
        prev = self._previous_system(cur)
        if prev:
            out.append(prev)
        for name in self._edsm_sphere(cur, radius=min(20.0, max(5.0, self._jump_range() * 0.8))):
            if name.upper() != cur and name not in out:
                out.append(name)
            if len(out) >= 5:
                break
        return out

    def _previous_system(self, cur: str) -> str | None:
        """ The system of the last jump into the current system (one jump away, the ship got here from there). """
        jd = self._journal_dir()
        if not jd:
            return None
        try:
            files = sorted((os.path.join(jd, f) for f in os.listdir(jd)
                            if f.startswith('Journal.') and f.endswith('.log')), key=os.path.getmtime)[-6:]
        except Exception:
            return None
        systems = []
        for fn in files:
            try:
                with open(fn, encoding='utf-8', errors='ignore') as fh:
                    for line in fh:
                        if '"FSDJump"' in line or '"Location"' in line or '"CarrierJump"' in line:
                            try:
                                ev = json.loads(line)
                            except Exception:
                                continue
                            sysname = ev.get('StarSystem')
                            if sysname and (not systems or systems[-1] != sysname):
                                systems.append(sysname)
            except Exception:
                continue
        for i in range(len(systems) - 1, 0, -1):
            if systems[i].upper() == cur and systems[i - 1].upper() != cur:
                return systems[i - 1]
        for s in reversed(systems):
            if s.upper() != cur:
                return s
        return None

    @staticmethod
    def _edsm_sphere(system: str, radius: float) -> list[str]:
        if not system:
            return []
        url = ("https://www.edsm.net/api-v1/sphere-systems?" +
               urllib.parse.urlencode({'systemName': system, 'radius': f"{radius:.0f}", 'minRadius': 1}))
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'EDAP-FailSafe/1.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8') or '[]')
            if not isinstance(data, list):
                return []
            data.sort(key=lambda d: d.get('distance') or 999)
            return [d['name'] for d in data if d.get('name')]
        except Exception as e:
            logger.warning(f"fail-safe: EDSM neighbour systems: {e}")
            return []

    def _jump_range(self) -> float:
        """ Laden jump range from the recent jumps in the journal. """
        try:
            from EDFuelPlanner import collect_jump_samples
            samples, ship_id = collect_jump_samples(self._journal_dir(), max_files=15)
            samples = [s for s in samples if ship_id is None or s['ship_id'] == ship_id]
            if samples:
                cargo = max(s['cargo'] for s in samples)
                laden = [s['dist'] for s in samples if s['cargo'] >= 0.8 * cargo] or [s['dist'] for s in samples]
                return max(laden)
        except Exception as e:
            logger.debug(f"fail-safe: jump range: {e}")
        return 15.0

    def _need_pad(self) -> int:
        return {'S': 1, 'M': 2, 'L': 3}.get((self._state().get('ship_size') or 'L').upper(), 3)

    # ------------------------------------------------------------------------------------------------------------
    def refuel_stop(self) -> bool:
        """ Flies to the nearest station with a fitting pad and docks there (refuel + repair on docking). """
        ap = self.ap
        pct = self._state().get('fuel_percent')
        st = self.find_refuel_station()
        if not st:
            self.log("Low fuel: no station for a fuel stop found.", True)
            return False
        self.log(f"Low fuel ({pct}%). Fuel stop at {st['station']} in {st['system']} "
                 f"({st['distance']:.1f} ly, {st['arrival_ls']:.0f} Ls).", True)
        ap.update_ap_status(f"Fuel stop: {st['station']}")
        cur = (self._state().get('cur_star_system') or '').upper()
        if st['system'].upper() != cur:
            if not self._plot_and_jump(st['system']):
                self.log(f"Fuel stop: could not reach {st['system']}.", True)
                return False
        ok = ap.supercruise_to_station(ap.scrReg, st['station'])
        sleep(2)
        if not ap.status.get_flag(FlagsDocked):
            self.log(f"Fuel stop: not docked at {st['station']}.", True)
            return False
        sleep(3)
        self.log(f"Fuel stop done, fuel {self._state().get('fuel_percent')}%. Continuing the route.", True)
        if not ok:
            logger.debug('fuel stop: supercruise_to_station returned False, but docked')
        return True

    def find_refuel_station(self) -> dict | None:
        cur = self._state().get('cur_star_system') or ''
        need_pad = self._need_pad()
        jr = self._jump_range()
        cands = {}
        try:
            from EDTradeFinder import (ArdentClient, pad_size, _norm, CARRIER_TYPES, EXCLUDED_TYPES, MEGASHIP_TYPES,
                                       SETTLEMENT_TYPES, PLANETARY_TYPES)
            client = ArdentClient()
            radius = min(500.0, max(20.0, jr * 4))
            # Hydrogen fuel is bought or sold by almost every station with a market (and these refuel)
            for kind in ('exports', 'imports'):
                try:
                    rows = client.nearby(kind, cur, 'hydrogenfuel', radius, 1, 90, False) or []
                except Exception as e:
                    logger.warning(f"fuel stop: Ardent {kind}: {e}")
                    rows = []
                for r in rows:
                    t = _norm(r.get('stationType') or '')
                    if t in EXCLUDED_TYPES or t in CARRIER_TYPES or t in MEGASHIP_TYPES or t in SETTLEMENT_TYPES:
                        continue
                    pad = pad_size(r.get('maxLandingPadSize'), t)
                    if pad is None or pad < need_pad:
                        continue
                    arrival = float(r.get('distanceToArrival') or 0)
                    if arrival > 8000:
                        continue
                    dist = float(r.get('distance') or 0)
                    key = f"{r.get('systemName')}|{r.get('stationName')}"
                    cands[key] = {'system': r.get('systemName'), 'station': r.get('stationName'),
                                  'distance': dist, 'arrival_ls': arrival, 'planetary': t in PLANETARY_TYPES}
        except Exception as e:
            logger.warning(f"fuel stop: station search failed: {e}")
        if cands:
            def score(c):
                jumps = 0 if c['distance'] < 0.1 else math.ceil(c['distance'] / max(jr, 1.0))
                return (jumps, c['planetary'], c['arrival_ls'])
            return min(cands.values(), key=score)
        return self._refuel_station_from_journal(cur)

    def _refuel_station_from_journal(self, cur: str) -> dict | None:
        """ Fallback without internet: a station with refuel the ship docked at, preferably in this system. """
        jd = self._journal_dir()
        if not jd:
            return None
        best = None
        try:
            files = sorted((os.path.join(jd, f) for f in os.listdir(jd)
                            if f.startswith('Journal.') and f.endswith('.log')), key=os.path.getmtime)[-20:]
            for fn in files:
                with open(fn, encoding='utf-8', errors='ignore') as fh:
                    for line in fh:
                        if '"Docked"' not in line:
                            continue
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if 'refuel' not in [s.lower() for s in ev.get('StationServices', [])]:
                            continue
                        st = {'system': ev.get('StarSystem'), 'station': ev.get('StationName'),
                              'distance': 0.0 if (ev.get('StarSystem') or '').upper() == cur.upper() else 99.0,
                              'arrival_ls': float(ev.get('DistFromStarLS') or 0)}
                        if best is None or st['distance'] <= best['distance']:
                            best = st
        except Exception as e:
            logger.debug(f"fuel stop: journal fallback: {e}")
        return best

    # ------------------------------------------------------------------------------------------------------------
    def start_new_route(self) -> bool:
        """ Searches trade routes around the current system with the Trade tab filters and loads the best one that
        does not use a station of the failed route. """
        ap = self.ap
        cfg = ap.config
        try:
            from EDTradeFinder import TradeFinder, route_to_waypoints, learn_timing, load_carrier_names
        except Exception as e:
            logger.warning(f"new route: {e}")
            return False
        for wp in (getattr(ap.waypoint, 'waypoints', {}) or {}).values():
            if isinstance(wp, dict) and wp.get('StationName'):
                self.bad_stations.add(wp['StationName'].upper())
        cur = self._state().get('cur_star_system') or ''
        cargo = int(self._state().get('cargo_capacity') or 0) or 100
        jd = self._journal_dir()
        params = dict(ref_system=cur, cargo=cargo,
                      max_start_distance=float(cfg.get('TradeSearchRadius', 50)),
                      max_hop_distance=float(cfg.get('TradeMaxHopDistance', 50)),
                      min_volume=int(cfg.get('TradeMinVolume', 0)),
                      max_arrival_ls=float(cfg.get('TradeMaxArrivalLs', 5000)),
                      max_age_hours=float(cfg.get('TradeMaxAgeHours', 24)),
                      min_pad=self._need_pad(),
                      carriers=bool(cfg.get('TradeIncludeCarriers', False)),
                      megaships=bool(cfg.get('TradeIncludeMegaships', False)),
                      planetary=bool(cfg.get('TradeIncludePlanetary', False)),
                      settlements=bool(cfg.get('TradeIncludeSettlements', False)),
                      round_trips=cfg.get('TradeMode', 'Round trips') == 'Round trips',
                      commodity_count=int(cfg.get('TradeCommodityCount', 80)),
                      jump_range=self._jump_range(),
                      secs_per_jump=float(cfg.get('TradeSecsPerJump', 75)),
                      secs_station=float(cfg.get('TradeSecsPerStation', 340)),
                      carrier_max_age_hours=float(cfg.get('TradeCarrierMaxAgeHours', 6)))
        try:
            if jd:
                load_carrier_names(jd)
                timing = learn_timing(jd)
                if timing:
                    params['secs_per_jump'] = timing['secs_per_jump']
                    params['secs_station'] = timing['secs_station']
            ap.update_ap_status("Fail-safe: searching a trade route")
            routes = TradeFinder(progress=lambda m: logger.debug(f"new route: {m}")).find_routes(**params)
        except Exception as e:
            if _is_interrupt(e):
                raise
            self.log(f"Fail-safe: trade route search failed: {e}")
            return False
        key, desc = SORT_KEYS.get(cfg.get('TradeSortBy', 'Profit per hour'), ('profit_hour', True))
        routes = sorted(routes, key=lambda r: r.get(key) or 0, reverse=desc)
        for r in routes:
            if (r.get('start_station') or '').upper() in self.bad_stations or \
                    (r.get('station') or '').upper() in self.bad_stations:
                continue
            name = re.sub(r'[^A-Za-z0-9]+', '_', f"trade_{r['start_station']}_{r['station']}").strip('_')[:80]
            os.makedirs('./waypoints', exist_ok=True)
            path = os.path.join('./waypoints', name + ".json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(route_to_waypoints(r), f, indent=4)
            if not ap.waypoint.load_waypoint_file(path):
                continue
            ap.waypoint.progress_cnt = getattr(ap.waypoint, 'progress_cnt', 0) + 1
            self.last_progress = ap.waypoint.progress_cnt
            self.log(f"Fail-safe: new trade route {r['start_station']} ({r['start_system']}) -> {r['station']} "
                     f"({r['system']}), {r.get('out_name')}, ~{(r.get('profit_hour') or 0) / 1e6:.1f} M cr/h. "
                     f"Saved as waypoints/{name}.json.", True)
            return True
        return False


# ----------------------------------------------------------------------------------------------------------------
def presell_cargo(ap) -> bool:
    """ Start of a trade route with cargo on board that the route does not sell ('TradePreSellMinTons', default
    100 t): sell it first at the most profitable station nearby, then start the route. The station with the highest
    revenue for the whole load is chosen; among stations within 3% of the best revenue the closest one.
    Returns True if something was sold (or nothing had to be done). Never raises except on STOP. """
    try:
        return _presell_cargo(ap)
    except Exception as e:
        if _is_interrupt(e):
            raise
        logger.exception("presell cargo")
        ap.ap_ckb('log', f"Selling the cargo first failed: {e}. Starting the route anyway.")
        return False


def _presell_cargo(ap) -> bool:
    from CargoParser import CargoParser
    from EDTradeFinder import ArdentClient, TradeFinder, display_name, _norm

    cfg = ap.config
    min_tons = int(cfg.get('TradePreSellMinTons', 100) or 0)
    if min_tons <= 0:
        return True
    wps = getattr(ap.waypoint, 'waypoints', {}) or {}
    route_sells, is_trade = set(), False
    for k, wp in wps.items():
        if not isinstance(wp, dict) or k == 'GlobalShoppingList':
            continue
        if wp.get('SellCommodities') or wp.get('BuyCommodities'):
            is_trade = True
        for name in (wp.get('SellCommodities') or {}):
            route_sells.add(_norm(name))
    if not is_trade or 'all' in route_sells:
        return True

    cp = CargoParser()
    cp.get_cargo_data()
    foreign = []
    for it in cp.get_items() or []:
        sym = it.get('Name') or ''
        loc = it.get('Name_Localised') or display_name(sym)
        cnt = int(it.get('Count') or 0) - int(it.get('Stolen') or 0)
        if cnt > 0 and _norm(sym) not in route_sells and _norm(loc) not in route_sells:
            foreign.append({'sym': _norm(sym), 'name': loc, 'count': cnt})
    tons = sum(f['count'] for f in foreign)
    if tons < min_tons:
        if tons:
            ap.ap_ckb('log', f"{tons} t cargo that the route does not sell (below {min_tons} t), starting the route.")
        return True

    rec = WaypointRecovery(ap)
    cur = ap.jn.ship_state().get('cur_star_system') or ''
    what = ", ".join(f"{f['count']} t {f['name']}" for f in foreign)
    ap.ap_ckb('log+vce', f"Cargo on board that the route does not sell: {what}. Selling it first.")
    ap.update_ap_status("Selling the cargo first")

    filt = dict(carriers=bool(cfg.get('TradeIncludeCarriers', False)),
                megaships=bool(cfg.get('TradeIncludeMegaships', False)),
                planetary=bool(cfg.get('TradeIncludePlanetary', False)),
                settlements=bool(cfg.get('TradeIncludeSettlements', False)),
                min_pad=rec._need_pad(), max_arrival_ls=float(cfg.get('TradeMaxArrivalLs', 5000)),
                max_age_hours=max(48.0, float(cfg.get('TradeMaxAgeHours', 24))),
                carrier_max_age_hours=float(cfg.get('TradeCarrierMaxAgeHours', 6)))
    radius = min(200.0, float(cfg.get('TradeSearchRadius', 50)))
    client = ArdentClient()
    finder = TradeFinder(client)
    stations: dict[str, dict] = {}
    for f in foreign:
        rows = []
        for min_vol in (f['count'], 1):
            try:
                rows = client.nearby('imports', cur, f['sym'], radius, min_vol, filt['max_age_hours'] / 24.0,
                                     filt['carriers']) or []
            except Exception as e:
                logger.warning(f"presell: Ardent imports {f['sym']}: {e}")
                rows = []
            if rows:
                break
        for r in rows:
            price = int(r.get('sellPrice') or 0)
            if price <= 0 or finder.station_reject_reason(r, filt):
                continue
            key = f"{r.get('systemName')}|{r.get('stationName')}"
            st = stations.setdefault(key, {'system': r.get('systemName'), 'station': r.get('stationName'),
                                           'distance': float(r.get('distance') or 0),
                                           'arrival_ls': float(r.get('distanceToArrival') or 0),
                                           'revenue': 0, 'sells': {}})
            qty = min(f['count'], int(r.get('demand') or f['count']) or f['count'])
            st['revenue'] += price * qty
            st['sells'][f['name']] = price
    if not stations:
        ap.ap_ckb('log+vce', "No station nearby buys the cargo. Starting the route.")
        return False
    best_rev = max(s['revenue'] for s in stations.values())
    good = [s for s in stations.values() if s['revenue'] >= 0.97 * best_rev]
    best = min(good, key=lambda s: (s['distance'], s['arrival_ls']))
    prices = ", ".join(f"{n} {p:,} cr" for n, p in best['sells'].items())
    ap.ap_ckb('log+vce', f"Selling at {best['station']} in {best['system']} ({best['distance']:.1f} ly, "
                         f"{best['arrival_ls']:.0f} Ls): {prices}, about {best['revenue'] / 1e6:.1f} M cr.")

    # Fly there (unless docked at that station already)
    from EDAP_data import FlagsDocked
    state = ap.jn.ship_state()
    here = (ap.status.get_flag(FlagsDocked) and (state.get('cur_station') or '').upper() == best['station'].upper()
            and (state.get('cur_star_system') or '').upper() == best['system'].upper())
    if not here:
        if best['system'].upper() != cur.upper() and not rec._plot_and_jump(best['system']):
            ap.ap_ckb('log+vce', f"Could not reach {best['system']} to sell the cargo. Starting the route.")
            return False
        ap.supercruise_to_station(ap.scrReg, best['station'])
        sleep(2)
        if not ap.status.get_flag(FlagsDocked):
            ap.ap_ckb('log+vce', f"Not docked at {best['station']}, cargo not sold. Starting the route.")
            return False

    # Sell with the normal trade code (temporary waypoint)
    wp = ap.waypoint
    key = '_PRESELL'
    wps[key] = {"SystemName": best['system'], "StationName": best['station'],
                "SellCommodities": {f['name']: 9999 for f in foreign}, "BuyCommodities": {},
                "FleetCarrierTransfer": False, "UpdateCommodityCount": False, "Skip": True, "Completed": True}
    try:
        wp.execute_trade(ap, key)
    finally:
        wps.pop(key, None)
    left = int(ap.status.get_cleaned_data().get('Cargo') or 0)
    ap.ap_ckb('log+vce', f"Cargo sold, {left} t left on board. Starting the trade route.")
    return True
