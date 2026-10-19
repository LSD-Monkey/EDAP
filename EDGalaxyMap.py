from __future__ import annotations

import json
import os

from EDAP_data import GuiFocusGalaxyMap
from Screen_Regions import Quad, load_calibrated_regions
from StatusParser import StatusParser
import time
from time import sleep

import cv2
from EDlogger import logger
from pyautogui import typewrite
from directinput import SCANCODE


class EDGalaxyMap:
    """ Handles the Galaxy Map. """
    def __init__(self, ed_ap, screen, keys, cb, is_odyssey=True):
        self.ap = ed_ap
        self.ocr = ed_ap.ocr
        self.is_odyssey = is_odyssey
        self.screen = screen
        self.keys = keys
        self.status_parser = StatusParser()
        self.ap_ckb = cb
        # The rect is top left x, y, and bottom right x, y in fraction of screen resolution
        self.reg = {'full_panel': {'rect': [0.1, 0.1, 0.9, 0.9]},
                    'cartographics': {'rect': [0.0, 0.0, 0.35, 0.12]},
                    'system_info': {'rect': [0.55, 0.08, 0.92, 0.35]},  # 'SYSTEM INFORMATION' + system name
                    'right_menu': {'rect': [0.70, 0.10, 0.95, 0.95]},  # icon column right of the info panel (tooltips)
                    }
        self.SystemSelectDelay = 0.5  # Delay selecting the system when in galaxy map

        # Load custom regions from file
        load_calibrated_regions('EDGalaxyMap', self.reg)

    def set_gal_map_dest_bookmark(self, ap, bookmark_type: str, bookmark_position: int) -> bool:
        """ Set the gal map destination using a bookmark.
        @param ap: ED_AP reference.
        @param bookmark_type: The bookmark type (Favorite, System, Body, Station or Settlement), Favorite
         being the default if no match is made with the other options.
        @param bookmark_position: The position in the bookmark list, starting at 1 for the first bookmark.
        @return: True if bookmark could be selected, else False
        """
        if self.is_odyssey and bookmark_position > 0:
            res = self.goto_galaxy_map()
            if not res:
                return False

            ap.keys.send('UI_Left')  # Go to BOOKMARKS
            sleep(.5)
            ap.keys.send('UI_Select')  # Select BOOKMARKS
            sleep(.25)
            ap.keys.send('UI_Right')  # Go to FAVORITES
            sleep(.25)

            # If bookmark type is Fav, do nothing as this is the first item
            if bookmark_type.lower().startswith("sys"):
                ap.keys.send('UI_Down')  # Go to SYSTEMS
            elif bookmark_type.lower().startswith("bod"):
                ap.keys.send('UI_Down', repeat=2)  # Go to BODIES
            elif bookmark_type.lower().startswith("sta"):
                ap.keys.send('UI_Down', repeat=3)  # Go to STATIONS
            elif bookmark_type.lower().startswith("set"):
                ap.keys.send('UI_Down', repeat=4)  # Go to SETTLEMENTS

            sleep(.25)
            ap.keys.send('UI_Select')  # Select bookmark type, moves you to bookmark list
            sleep(.25)
            ap.keys.send('UI_Down', repeat=bookmark_position - 1)
            sleep(.25)
            ap.keys.send('UI_Select', hold=3.0)

            # Close Galaxy map
            ap.keys.send('GalaxyMapOpen')
            sleep(0.5)
            return True

        return False

    def set_gal_map_destination_text(self, ap, target_name, target_select_cb=None) -> bool:
        """ Call either the Odyssey or Horizons version of the Galactic Map sequence. """
        if not self.is_odyssey:
            return ap.galaxy_map.set_gal_map_destination_text_horizons(ap, target_name, target_select_cb)
        else:
            return ap.galaxy_map.set_gal_map_destination_text_odyssey(ap, target_name)

    def set_gal_map_destination_text_horizons(self, ap, target_name, target_select_cb=None) -> bool:
        """ This sequence for the Horizons. """
        res = self.goto_galaxy_map()
        if not res:
            return False

        ap.keys.send('CycleNextPanel')
        sleep(1)
        ap.keys.send('UI_Select')
        sleep(2)

        typewrite(target_name, interval=0.25)
        sleep(1)

        # send enter key
        ap.keys.send_key('Down', 28)
        sleep(0.05)
        ap.keys.send_key('Up', 28)

        sleep(7)
        ap.keys.send('UI_Right')
        sleep(1)
        ap.keys.send('UI_Select')

        # if got passed through the ship() object, lets call it to see if a target has been
        # selected yet... otherwise we wait.  If long route, it may take a few seconds
        if target_select_cb is not None:
            while not target_select_cb()['target']:
                sleep(1)

        # Close Galaxy map
        ap.keys.send('GalaxyMapOpen')
        sleep(2)
        return True

    def set_gal_map_destination_text_odyssey(self, ap, target_name) -> bool:
        """ This sequence for the Odyssey. """
        res = self.goto_galaxy_map()
        if not res:
            return False

        target_name_uc = target_name.upper()

        # Check if the current nav route is to the target system
        last_nav_route_sys = ap.nav_route.get_last_system()
        last_nav_route_sys_uc = last_nav_route_sys.upper()
        if last_nav_route_sys_uc == target_name_uc:
            # Close Galaxy map
            ap.keys.send('GalaxyMapOpen')
            return True

        # Sequence recorded in game (session 2026-10-18_23-17-36, the one that plotted the route):
        #   UI_Up, UI_Select (open search field) -> type name -> wait for the suggestion list below the field
        #   -> UI_Down (highlight 1st suggestion) -> UI_Select (map flies to the system, SYSTEM INFORMATION
        #   panel opens) -> 'D' (primary UI_Right, restores UI focus) -> UI_Right (icon column right of the panel)
        #   -> 7x UI_Down ('PLOT ROUTE') -> UI_Select.
        # Do NOT press ENTER in the search field: ENTER jumps to the system as well, but the UI loses the focus
        # and all following arrow keys do nothing (that was the reason the route was never plotted).
        # If the plotted route goes to a wrong system, the map is reopened and the next suggestion is used.
        for result_no in range(1, 6):
            if result_no > 1:
                # Reopen the map so the focus starts at a known position again
                ap.keys.send('GalaxyMapOpen')
                sleep(1.5)
                if not self.goto_galaxy_map():
                    return False

            last_nav_route_sys_uc = ap.nav_route.get_last_system().upper() if ap.nav_route is not None else ""
            logger.debug(f"Previous Nav Route dest: {last_nav_route_sys_uc}. Search suggestion no. {result_no}.")

            self._search_system(ap, target_name_uc)

            # Highlight suggestion no. result_no in the list below the search field and select it
            ap.keys.send('UI_Down', repeat=result_no, repeat_delay=0.3)
            sleep(0.3)
            ap.keys.send('UI_Select')
            # The map flies to the system and opens the SYSTEM INFORMATION panel
            sleep(max(self.SystemSelectDelay, 3.0))

            # Sequence designed by the user and recorded 5x in a row with success (session 2026-10-19_08-27-25,
            # NavRoute 0.3-0.8 s after the last UI_Select):
            #   'D' (primary key of UI_Right) -> Right Arrow (UI_Right) -> 7x Down Arrow (UI_Down) -> Space.
            # After selecting the system the UI has no focus; the primary key 'D' brings it back, then the
            # arrow keys work. Do not add extra Right/Up presses (focus may then end up in the left column).
            wake = ap.keys.get_primary_scancode('UI_Right') or SCANCODE['Key_D']
            logger.debug(f"Galaxy Map: tap primary UI_Right key (scancode {wake}) to restore the UI focus.")
            ap.keys.tap_scancode(wake, hold=0.12)
            sleep(0.7)
            ap.keys.send('UI_Right')
            sleep(0.7)
            ap.keys.send('UI_Down', repeat=7, repeat_delay=0.25)
            sleep(0.6)
            ap.keys.send('UI_Select')

            if ap.nav_route is None:
                logger.debug("Unable to check Nav Route, so assuming it is correct.")
                break

            logger.debug("Waiting for Nav Route to update.")
            wait_start = time.time()
            curr_nav_route_sys_uc = last_nav_route_sys_uc
            while time.time() - wait_start < 15:
                sleep(0.5)
                curr_nav_route_sys_uc = ap.nav_route.get_last_system().upper()
                if curr_nav_route_sys_uc != last_nav_route_sys_uc:
                    break

            if curr_nav_route_sys_uc == target_name_uc:
                logger.debug(f"Nav Route correctly updated to {target_name_uc}.")
                break
            if curr_nav_route_sys_uc == last_nav_route_sys_uc:
                # Nothing plotted at all -> the key sequence did not work, retrying will not help
                self._save_debug_screenshot('galmap_no_route')
                self.ap_ckb('log+vce', f"No route plotted to {target_name_uc} (Galaxy Map). "
                                       f"Screenshot saved in debug-output.")
                ap.keys.send('GalaxyMapOpen')
                return False
            logger.debug(f"Nav Route went to wrong system {curr_nav_route_sys_uc}, trying next suggestion.")
        else:
            self._save_debug_screenshot('galmap_wrong_target')
            self.ap_ckb('log+vce', f"Unable to plot a route to {target_name_uc} in the Galaxy Map.")
            ap.keys.send('GalaxyMapOpen')
            return False

        # Close Galaxy map
        ap.keys.send('GalaxyMapOpen')
        sleep(0.5)
        return True

    def _search_system(self, ap, target_name_uc: str):
        """ Galaxy Map must be open with the focus near the search bar (after goto_galaxy_map).
        Opens the search field, types the name and waits for the suggestion list. No ENTER (see above). """
        ap.keys.send('UI_Up')
        sleep(0.2)
        ap.keys.send('UI_Select')  # open search field
        sleep(0.5)

        typewrite(target_name_uc, interval=0.2)
        logger.debug(f"Entered system name: {target_name_uc}.")
        # The suggestion list needs a moment ('TYPE AT LEAST 2 CHARACTERS...' is shown until it is ready)
        sleep(2.5)

    def set_next_system(self, ap, target_system) -> bool:
        """ Sets the next system to jump to, or the final system to jump to.
        If the system is already selected or is selected correctly, returns True,
        otherwise False.
        """
        # Call sequence to select route
        if self.set_gal_map_destination_text(ap, target_system, None):
            return True
        else:
            # Error setting target
            logger.warning("Error setting waypoint, breaking")
            return False

    def _save_debug_screenshot(self, name: str):
        """ Saves a screenshot to debug-output for analysing failures. """
        try:
            os.makedirs('debug-output', exist_ok=True)
            image = self.screen.get_screen_full()
            if image is not None:
                fn = f"debug-output/{name}_{time.strftime('%Y%m%d-%H%M%S')}.png"
                cv2.imwrite(fn, image)
                logger.info(f"Saved debug screenshot {fn}")
        except Exception as e:
            logger.warning(f"Could not save debug screenshot: {e}")

    def goto_galaxy_map(self) -> bool:
        """Open Galaxy Map if we are not there. Waits for map to load. Selects the search bar.
        """
        if self.status_parser.get_gui_focus() != GuiFocusGalaxyMap:
            logger.debug("Opening Galaxy Map")
            # Goto cockpit view
            self.ap.ship_control.goto_cockpit_view()
            # Goto Galaxy Map
            self.keys.send('GalaxyMapOpen')

            if self.ap.debug_overlay:
                stn_svcs = Quad.from_rect(self.reg['full_panel']['rect'])
                self.ap.overlay.overlay_quad_pct('system map', stn_svcs, (0, 255, 0), 2, 5)
                self.ap.overlay.overlay_paint()

            # Wait for the map to open. Status.json GuiFocus is reliable and fast; the OCR check of the
            # 'CARTOGRAPHICS' title depends on the calibration and only costs time if it fails.
            if not self.status_parser.wait_for_gui_focus(GuiFocusGalaxyMap, timeout=10):
                logger.warning("Unable to open Galaxy Map")
                return False
            # No OCR check of the 'CARTOGRAPHICS' title any more: it took several seconds per try and did not
            # work on 21:9 screens. GuiFocus is reliable, the map only needs a moment to accept input.
            sleep(2.0)

            self.keys.send('UI_Up')  # Go up to search bar
            return True
        else:
            logger.debug("Galaxy Map is already open")
            self.keys.send('UI_Left', repeat=2)
            self.keys.send('UI_Up', hold=2)  # Go up to search bar. Allows 1 left to bookmarks.
            return True
