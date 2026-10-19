from __future__ import annotations

import difflib
import json
import logging
import os
import re
import time
from copy import copy
from time import sleep

import cv2
import numpy as np

from EDAP_data import GuiFocusExternalPanel
from EDlogger import logger
from Screen_Regions import Quad, Point, load_calibrated_regions
from StatusParser import StatusParser
from Screen import crop_image_by_pct

"""
File:navPanel.py    

Description:
  TBD 

Author: Stumpii
"""


def image_perspective_transform(image, src_quad: Quad):
    """ Performs warping of the nav panel image and returns the resulting image.
    The warping removes the perspective slanting of all sides so the
    returning image has vertical columns and horizontal rows for matching
    or OCR.
    @param image: The image used to generate the transform.
    @param src_quad: A quad to transform, in percent of the image size.
    @return:
        dst - The transformed image.
        m - The transform used to deskew the image.
        rev - The reverse transform used skew an overlay to match the original.
    """
    # Existing size
    h, w, ch = image.shape

    # Source
    source_coord = src_quad.to_list()
    pts1 = np.float32(source_coord)

    # Destination
    output_coord = [[0, 0], [w, 0], [w, h], [0, h]]
    pts2 = np.float32(output_coord)

    # Calc and perform transform
    m = cv2.getPerspectiveTransform(pts1, pts2)
    dst = cv2.warpPerspective(image, m, (w, h))

    # Calc the reverse transform to allow us to skew any overlays
    rev = cv2.getPerspectiveTransform(pts2, pts1)

    # Return the image and the transforms
    return dst, m, rev


def image_reverse_perspective_transform(image, src_quad: Quad, rev_transform) -> Quad:
    """ Performs warping of points and returns the transformed (warped) points.
    Used to calculate overlay graphics for display over the navigation panek, which is warped.
    @param image: The straightened image from the perspective transform function.
    @param src_quad: A quad to transform, in percent of the image size.
    @param rev_transform: The reverse transform created by the perspective transform function.
    @return: A quad representing the input quad, reverse transformed. Return quad is in pixel relative to the origin
    of the image (0, 0).
    """
    # Existing size
    h, w, ch = image.shape

    # Scale from percent of nav panel to pixels
    q = copy(src_quad)
    q.scale_from_origin(w, h)

    # Source
    source_coord = q.to_list()
    # Convert 2D to 3D array for transform
    src_arr = np.float32(source_coord).reshape(-1, 1, 2)

    # Transform the array of coordinates to the skew of the nav panel
    dst_arr = cv2.perspectiveTransform(src_arr, rev_transform)

    # Convert 3D results to 2D array for results
    dst_arr_2d = dst_arr.reshape(-1, dst_arr.shape[-1])
    # Convert to list of points
    pts = dst_arr_2d.tolist()
    # Create a quad from the points
    q_out = Quad.from_list(pts)
    return q_out


def normalize_destination_name(name: str | None) -> str:
    """ Normalizes a destination name for comparison (upper case, only letters/digits, single spaces).
    The Nav Panel shows names in upper case, Status.json in mixed case, OCR may add/drop punctuation.
    """
    if not name:
        return ""
    name = re.sub(r"[^0-9A-Z]+", " ", name.upper())
    return " ".join(name.split())


def destination_names_match(name_a: str | None, name_b: str | None, sim_match: float = 0.8) -> bool:
    """ Returns True if two destination names are equal or similar enough (0.0 - 1.0). """
    a = normalize_destination_name(name_a)
    b = normalize_destination_name(name_b)
    if a == "" or b == "":
        return False
    if a == b:
        return True
    # Partial names, e.g. 'JAQUES' for 'JAQUES STATION' (whole words only, min. 4 chars)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 4 and f" {shorter} " in f" {longer} ":
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= sim_match


def rects_to_quadrilateral(rect_tlbr: Quad, rect_bltr: Quad) -> Quad:
    """
    Convert two rectangles that cover the points of the nav panel to a quad.
    rect - [L, T, R, B]
    The panel is rotated slightly anti-clockwise
    """
    q = Quad(Point(rect_tlbr.left, rect_tlbr.top),
             Point(rect_bltr.right, rect_bltr.top),
             Point(rect_tlbr.right, rect_tlbr.bottom),
             Point(rect_bltr.left, rect_bltr.bottom))
    return q


class EDNavigationPanel:
    """ The Navigation (Left hand) Ship Status Panel. """

    def __init__(self, ed_ap, screen, keys, cb):
        self.ap = ed_ap
        self.ocr = ed_ap.ocr
        self.screen = screen
        self.keys = keys
        self.ap_ckb = cb
        self.locale = self.ap.locale
        self.status_parser = StatusParser()

        self.navigation_tab_text = self.locale["NAV_PNL_TAB_NAVIGATION"]
        self.transactions_tab_text = self.locale["NAV_PNL_TAB_TRANSACTIONS"]
        self.contacts_tab_text = self.locale["NAV_PNL_TAB_CONTACTS"]
        self.target_tab_text = self.locale["NAV_PNL_TAB_TARGET"]

        # The rect is [L, T, R, B], top left x, y, and bottom right x, y in fraction of screen resolution
        # Nav Panel region covers the entire navigation panel.
        self.reg = {'panel_bounds1': {'rect': [0.0, 0.2, 0.7, 0.35]},
                    'panel_bounds2': {'rect': [0.0, 0.2, 0.7, 0.35]},
                    }
        self.sub_reg = {'tab_bar': {'rect': [0.0, 0.0, 1.0, 0.08]},
                        'location_panel': {'rect': [0.2218, 0.3, 0.8, 1.0]},
                        'nav_pnl_tab': {'rect': [0.0, 0.0, 0.23, 0.7]},
                        'nav_pnl_location': {'rect': [0.0, 0.0, 1.0, 0.08]},
                        }
        self.panel_quad_pct = Quad()
        self.panel_quad_pix = Quad()
        self.panel = None
        self._transform = None  # Warp transform to deskew the Nav panel
        self._rev_transform = None  # Reverse warp transform to skew to match the Nav panel

        # Debug images of the panel are written here (cv2.imwrite silently fails if the folder does not exist)
        os.makedirs('test/nav-panel/out', exist_ok=True)

        # Load custom regions from file
        load_calibrated_regions('EDNavigationPanel', self.reg)

        self.customize_regions()

    def customize_regions(self):
        # Produce quadrilateral from the two bounds rectangles
        reg1 = Quad.from_rect(self.reg['panel_bounds1']['rect'])
        reg2 = Quad.from_rect(self.reg['panel_bounds2']['rect'])
        self.panel_quad_pct = rects_to_quadrilateral(reg1, reg2)
        self.panel_quad_pix = copy(self.panel_quad_pct)
        self.panel_quad_pix.scale_from_origin(self.ap.scr.screen_width, self.ap.scr.screen_height)

    def capture_panel_straightened(self):
        """ Grab the image based on the panel coordinates.
        Returns an unfiltered image, either from screenshot or provided image, or None if an image cannot
        be grabbed.
        """
        if self.panel_quad_pct is None:
            logger.warning(f"Nav Panel Calibration has not been performed. Cannot continue.")
            self.ap_ckb('log', 'Nav Panel Calibration has not been performed. Cannot continue.')
            return None

        # Get the nav panel image based on the region
        image = self.screen.get_screen(self.panel_quad_pix.left, self.panel_quad_pix.top,
                                       self.panel_quad_pix.right, self.panel_quad_pix.bottom, rgb=False)
        cv2.imwrite(f'test/nav-panel/out/nav_panel_original.png', image)

        # Offset the panel co-ords to match the cropped image (i.e. starting at 0,0)
        panel_quad_pix_off = copy(self.panel_quad_pix)
        panel_quad_pix_off.offset(-panel_quad_pix_off.left, -panel_quad_pix_off.top)

        # Straighten the image
        straightened, trans, rev_trans = image_perspective_transform(image, panel_quad_pix_off)
        # Store the transforms
        self._transform = trans
        self._rev_transform = rev_trans
        # Write the file
        cv2.imwrite(f'test/nav-panel/out/nav_panel_straight.png', straightened)

        if self.ap.debug_overlay:
            self.ap.overlay.overlay_quad_pct('nav_panel_active', self.panel_quad_pct, (0, 255, 0), 2, 5)
            self.ap.overlay.overlay_paint()

        return straightened

    def capture_tab_bar(self):
        """ Get the tab bar (NAVIGATION/TRANSACTIONS/CONTACTS/TARGET).
        Returns an image, or None.
        """
        # Scale the regions based on the target resolution.
        self.panel = self.capture_panel_straightened()
        if self.panel is None:
            return None

        # Convert region rect to quad
        tab_bar_quad = Quad.from_rect(self.sub_reg['tab_bar']['rect'])
        # Crop the image to the extents of the quad
        tab_bar = crop_image_by_pct(self.panel, tab_bar_quad)
        cv2.imwrite(f'test/nav-panel/out/tab_bar.png', tab_bar)

        if self.ap.debug_overlay:
            # Transform the array of coordinates to the skew of the nav panel
            q_out = image_reverse_perspective_transform(self.panel, tab_bar_quad, self._rev_transform)
            # Offset to match the nav panel offset
            q_out.offset(self.panel_quad_pix.left, self.panel_quad_pix.top)

            self.ap.overlay.overlay_quad_pix('nav_panel_tab_bar', q_out, (0, 255, 0), 2, 5)
            self.ap.overlay.overlay_paint()

        return tab_bar

    def capture_location_panel(self):
        """ Get the location panel from within the nav panel.
        Returns an image, or None.
        """
        # Scale the regions based on the target resolution.
        nav_panel = self.capture_panel_straightened()
        if nav_panel is None:
            return None

        # Convert region rect to quad
        location_panel_quad = Quad.from_rect(self.sub_reg['location_panel']['rect'])
        # Crop the image to the extents of the quad
        location_panel = crop_image_by_pct(nav_panel, location_panel_quad)
        cv2.imwrite(f'test/nav-panel/out/location_panel.png', location_panel)

        if self.ap.debug_overlay:
            # Transform the array of coordinates to the skew of the nav panel
            q_out = image_reverse_perspective_transform(nav_panel, location_panel_quad, self._rev_transform)
            # Offset to match the nav panel offset
            q_out.offset(self.panel_quad_pix.left, self.panel_quad_pix.top)

            self.ap.overlay.overlay_quad_pix('nav_panel_location_panel', q_out, (0, 255, 0), 2, 5)
            self.ap.overlay.overlay_paint()

        return location_panel

    def show_panel(self):
        """ Shows the Nav Panel. Opens the Nav Panel if not already open.
        Returns True if successful, else False.
        """
        # Is nav panel active?
        active, active_tab_name = self.is_panel_active()
        if active:
            # Store image
            image = self.screen.get_screen_full()
            cv2.imwrite(f'test/nav-panel/nav_panel_full.png', image)
            return active, active_tab_name
        else:
            print("Open Nav Panel")
            self.ap.ship_control.goto_cockpit_view()
            if self.keys.has_binding("HeadLookReset"):
                self.keys.send("HeadLookReset")

            if self.keys.has_binding('FocusLeftPanel'):
                # Direct binding (default key '1'). Works without UIFocus/HeadLookReset being bound.
                self.keys.send('FocusLeftPanel')
            else:
                self.keys.send('UIFocus', state=1)
                self.keys.send('UI_Left')
                self.keys.send('UIFocus', state=0)
            # Wait for the panel open animation, inputs sent during the animation may be lost.
            sleep(1.0)

            # Check if it opened
            active, active_tab_name = self.is_panel_active()
            if active:
                # Store image
                image = self.screen.get_screen_full()
                cv2.imwrite(f'test/nav-panel/nav_panel_full.png', image)
                return active, active_tab_name
            else:
                return False, ""

    def hide_panel(self):
        """ Hides the Nav Panel if open.
        """
        # Is nav panel active?
        if self.status_parser.get_gui_focus() == GuiFocusExternalPanel:
            self.ap.ship_control.goto_cockpit_view()

    def is_panel_active(self) -> (bool, str):
        """ Determine if the Nav Panel is open and if so, which tab is active.
            Returns True if active, False if not and also the string of the tab name.
        """
        # Check if nav panel is open
        if not self.status_parser.wait_for_gui_focus(GuiFocusExternalPanel, 3):
            logger.debug("is_nav_panel_active: right panel not focused")
            return False, ""

        # Try this 'n' times before giving up
        tab_text = ""
        tabs = [self.navigation_tab_text, self.transactions_tab_text, self.contacts_tab_text, self.target_tab_text]
        for i in range(10):
            # Is open, so proceed
            tab_bar = self.capture_tab_bar()
            if tab_bar is None:
                return False, ""

            # Find the highlighted (solid orange) tab
            item = Quad.from_rect(self.sub_reg['nav_pnl_tab']['rect'])
            img_selected, quad = self.ocr.get_highlighted_item_in_image(tab_bar, item)
            if img_selected is None:
                logger.debug(f"is_nav_panel_active: try {i + 1}: no highlighted tab found in the tab bar "
                             f"(check the Nav Panel calibration, see test/nav-panel/out/tab_bar.png)")
            else:
                # 1. OCR of the highlighted tab
                ocr_textlist = self.ocr.image_simple_ocr(img_selected, 'nav panel tab')
                for tab in tabs:
                    if tab != "?" and tab in str(ocr_textlist).upper():
                        tab_text = tab
                        break
                logger.debug(f"is_nav_panel_active: try {i + 1}: OCR {ocr_textlist} at x={quad.left:.2f}-"
                             f"{quad.right:.2f} -> '{tab_text}'")

                # 2. Fallback: position of the highlighted tab. The tab bar always has the order
                #    NAVIGATION | TRANSACTIONS | CONTACTS | > | TARGET
                if tab_text == "":
                    centre = (quad.left + quad.right) / 2
                    idx = 0 if centre < 0.28 else 1 if centre < 0.49 else 2 if centre < 0.72 else 3
                    tab_text = tabs[idx]
                    logger.debug(f"is_nav_panel_active: OCR failed, tab from position (centre {centre:.2f}): "
                                 f"'{tab_text}'")

                if self.ap.debug_overlay:
                    tab_bar_quad = Quad.from_rect(self.sub_reg['tab_bar']['rect'])
                    q = copy(quad)
                    q.scale_from_origin(tab_bar_quad.width, tab_bar_quad.height)
                    q_out = image_reverse_perspective_transform(self.panel, q, self._rev_transform)
                    q_out.offset(self.panel_quad_pix.left, self.panel_quad_pix.top)
                    self.ap.overlay.overlay_floating_text('nav_panel_item_text', f'{tab_text}', q_out.left,
                                                          q_out.top - 25, (0, 255, 0))
                    self.ap.overlay.overlay_quad_pix('nav_panel_item', q_out, (0, 255, 0), 2)
                    self.ap.overlay.overlay_paint()

                if tab_text != "":
                    break

            # Wait and retry
            sleep(1)

            # In case we are on a picture tab, cycle to the next tab
            self.keys.send('CycleNextPanel')

        # Return Tab text or nothing
        if tab_text != "":
            return True, tab_text
        else:
            return False, ""

    def show_navigation_tab(self) -> bool | None:
        """ Shows the NAVIGATION tab of the Nav Panel. Opens the Nav Panel if not already open.
        Returns True if successful, else False.
        """
        # Show nav panel
        active, active_tab_name = self.show_panel()
        if active is None:
            return None
        if not active:
            print("Nav Panel could not be opened")
            return False
        elif active_tab_name is self.navigation_tab_text:
            # Do nothing
            return True
        elif active_tab_name is self.transactions_tab_text:
            self.keys.send('CycleNextPanel', repeat=3)
            return True
        elif active_tab_name is self.contacts_tab_text:
            self.keys.send('CycleNextPanel', repeat=2)
            return True
        elif active_tab_name is self.target_tab_text:
            self.keys.send('CycleNextPanel', repeat=2)
            return True

    def show_contacts_tab(self) -> bool | None:
        """ Shows the CONTACTS tab of the Nav Panel. Opens the Nav Panel if not already open.
        Returns True if successful, else False.
        """
        # Show nav panel
        active, active_tab_name = self.show_panel()
        if active is None:
            return None
        if not active:
            print("Nav Panel could not be opened")
            return False
        elif active_tab_name is self.navigation_tab_text:
            self.keys.send('CycleNextPanel', repeat=2)
            return True
        elif active_tab_name is self.transactions_tab_text:
            self.keys.send('CycleNextPanel')
            return True
        elif active_tab_name is self.contacts_tab_text:
            # Do nothing
            return True
        elif active_tab_name is self.target_tab_text:
            self.keys.send('CycleNextPanel', repeat=3)
            return True

    def lock_destination(self, dst_name) -> bool:
        """ Checks if destination is already locked and if not, Opens Nav Panel, Navigation Tab,
        scrolls locations and if the requested location is found, lock onto destination. Close Nav Panel.
        Returns True if the destination is already locked, or if it is successfully locked.
        """
        # Checks if the desired destination is already locked
        status = self.status_parser.get_cleaned_data()
        if status['Destination_Name']:
            cur_dest = status['Destination_Name']
            # print(f"wanted dest: {dst_name}. Current dest: {cur_dest}")
            if cur_dest.upper() == dst_name.upper():
                return True

        res = self.show_navigation_tab()
        if not res:
            print("Nav Panel could not be opened")
            return False

        found = self.find_destination_in_list(dst_name)
        if found:
            self.keys.send("UI_Select", repeat=2)  # Select it and lock target
        else:
            return False

        self.hide_panel()
        return found

    def get_status_destination(self) -> str:
        """ Returns the current in-game destination name from Status.json ('' if none).
        Note: ED does not always clear this when a destination is unlocked. """
        status = self.status_parser.get_cleaned_data()
        return status.get('Destination_Name', '') or ''

    def destination_matches(self, dst_name: str, sim_match: float = 0.8) -> bool:
        """ True if the in-game destination (Status.json) matches dst_name. """
        return destination_names_match(self.get_status_destination(), dst_name, sim_match)

    def wait_for_destination(self, dst_name: str, timeout: float = 5.0) -> bool:
        """ Waits until the Status.json destination matches dst_name. Status.json lags the game by ~0.5-1 s. """
        start = time.time()
        while (time.time() - start) < timeout:
            if self.destination_matches(dst_name):
                return True
            sleep(0.25)
        return False

    def activate_supercruise_assist(self, dst_name: str) -> bool:
        """ Selects dst_name in the Nav Panel (NAVIGATION tab) and activates the in-game Supercruise Assist.

        The details view of a list entry has the same buttons for all destination types
        (stations, carriers, bodies, signal sources):
            [ LOCK DESTINATION ] [ SUPERCRUISE ASSIST ]
                          BACK
        LOCK DESTINATION is pre-selected. Selecting SUPERCRUISE ASSIST also locks the destination, which is
        verified via Status.json (Destination.Name). In normal space the game then charges the FSD itself.

        Returns True if the destination is locked afterwards, else False. Panel is closed in all cases.
        """
        res = self.show_navigation_tab()
        if not res:
            logger.warning("activate_supercruise_assist: Nav Panel could not be opened")
            self.hide_panel()
            return False

        found = self.find_destination_in_list(dst_name)
        if not found:
            logger.warning(f"activate_supercruise_assist: '{dst_name}' not found in Nav Panel list")
            self.hide_panel()
            return False

        self.keys.send("UI_Select")  # Open the details view of the destination
        sleep(0.8)  # Details view animation
        self.keys.send("UI_Right")  # LOCK DESTINATION -> SUPERCRUISE ASSIST
        sleep(0.3)
        self.keys.send("UI_Select")  # Activate Supercruise Assist (also locks the destination)

        locked = self.wait_for_destination(dst_name, timeout=5.0)
        if not locked:
            logger.warning(f"activate_supercruise_assist: Status.json destination is "
                           f"'{self.get_status_destination()}', expected '{dst_name}'")

        self.hide_panel()
        return locked

    def request_docking(self) -> bool:
        """ Try to request docking with OCR.
        """
        res = self.show_contacts_tab()
        if res is None:
            return False
        if not res:
            print("Contacts Panel could not be opened")
            return False

        # On the CONTACT TAB, go to top selection, do this 4 seconds to ensure at top
        # then go right, which will be "REQUEST DOCKING" and select it
        self.keys.send("UI_Down")  # go down
        self.keys.send('UI_Up', hold=2)  # got to top row
        self.keys.send('UI_Right')
        self.keys.send('UI_Select')
        sleep(0.3)

        self.hide_panel()
        return True

    def scroll_to_top_of_list(self, hold_time: float = 3.0) -> bool | None:
        """ Scrolls to the top of the list by holding 'up' for a fixed time (like request_docking does).
        The former version held 'up' until the OCR of the selected row did not change 3 times. With slow OCR
        (3440x1440) that took 30 s, and when no highlighted row was found it waited forever with 'up' held.
        """
        self.keys.send("UI_Down")  # go down in case we are at the top and don't want to go to the bottom
        self.keys.send("UI_Up", hold=hold_time)  # held key is always released (also on stop)
        sleep(0.3)
        return True

    def find_destination_in_list(self, dst_name) -> bool:
        # tries is the number of rows to go through to find the item looking for
        # the Nav Panel should be filtered to reduce the number of rows in the list
        q_out = None

        # Scroll to top of list
        res = self.scroll_to_top_of_list()
        if not res:
            logger.debug(f"Unable to scroll to top of list.")
            return False

        y_last = -1
        in_list = False  # Have we seen one item yet? Prevents quiting if we have not selected the first item.
        no_highlight = 0
        start_time = time.time()
        rows = 0
        while 1:
            # Safety: never loop forever (no highlighted row found, very long list, ...)
            if time.time() - start_time > 90 or rows > 60:
                logger.warning(f"find_destination_in_list: giving up after {rows} rows / "
                               f"{time.time() - start_time:.0f} s. Did not find '{dst_name}'.")
                return False

            # Get the location panel image
            loc_panel = self.capture_location_panel()
            if loc_panel is None:
                return False

            # Find the selected item/menu (solid orange)
            item = Quad.from_rect(self.sub_reg['nav_pnl_location']['rect'])
            img_selected, quad = self.ocr.get_highlighted_item_in_image(loc_panel, item)

            # Check if end of list.
            if img_selected is None and in_list:
                logger.debug(f"Off end of list. Did not find '{dst_name}' in list.")
                return False
            if img_selected is None:
                # No highlighted row (yet). Do not wait forever.
                no_highlight += 1
                if no_highlight > 5:
                    logger.debug(f"No highlighted row in the Nav Panel list. Did not find '{dst_name}'.")
                    return False
                sleep(0.3)
                continue

            if self.ap.debug_overlay:
                # Scale the selected item down to the scale of the tab bar
                loc_pnl_quad = Quad.from_rect(self.sub_reg['location_panel']['rect'])
                q = copy(quad)
                # Convert to a percentage of the nav panel
                q.scale_from_origin(loc_pnl_quad.width, loc_pnl_quad.height)
                q.offset(loc_pnl_quad.left, loc_pnl_quad.top)

                # Transform the array of coordinates to the skew of the nav panel
                q_out = image_reverse_perspective_transform(self.panel, q, self._rev_transform)
                # Offset to match the nav panel offset
                q_out.offset(self.panel_quad_pix.left, self.panel_quad_pix.top)

                # Overlay OCR result
                # self.ap.overlay.overlay_floating_text('nav_panel_item_text', f'{str(ocr_textlist)}', q_out.left, q_out.top - 25, (0, 255, 0))
                self.ap.overlay.overlay_quad_pix('nav_panel_item', q_out, (0, 255, 0), 2)
                self.ap.overlay.overlay_paint()

            # Check if this item is above the last item (we cycled to top). The quad is a percent decimal (0.0 - 1.0).
            if quad.top < y_last - 0.1:
                logger.debug(f"Cycled back to top. Did not find '{dst_name}' in list.")
                return False
            else:
                y_last = quad.top

            # OCR the selected item
            sim_match = 0.8  # Similarity match 0.0 - 1.0 for 0% - 100%)
            ocr_textlist = self.ocr.image_simple_ocr(img_selected)
            if ocr_textlist is not None:
                sim = self.ocr.string_similarity(f"['{dst_name.upper()}']", str(ocr_textlist))

                if self.ap.debug_overlay:
                    # Overlay OCR result
                    self.ap.overlay.overlay_floating_text('nav_panel_item_text', f'{str(ocr_textlist)} {round(sim, 4)} > {sim_match}',
                                                          q_out.left, q_out.top - 25, (0, 255, 0))
                    self.ap.overlay.overlay_paint()

                #print(f"Similarity of ['{dst_name.upper()}'] and {str(ocr_textlist)} is {sim}")
                if sim > sim_match:
                    logger.debug(f"Found '{dst_name}' in list.")
                    return True
                else:
                    in_list = True
                    rows += 1
                    self.keys.send("UI_Down")  # up to next item
            else:
                # OCR returned nothing for the highlighted row: go on to the next row instead of looping
                rows += 1
                self.keys.send("UI_Down")


def dummy_cb(msg, body=None):
    pass


# Usage Example
if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)  # Default to log all debug when running this file.
    from ED_AP import EDAutopilot

    ap = EDAutopilot(cb=dummy_cb)
    ap.keys.activate_window = True  # Helps with single steps testing

    from Screen import set_focus_elite_window, crop_image_by_pct

    set_focus_elite_window()
    nav_pnl = EDNavigationPanel(ap, ap.scr, ap.keys, dummy_cb)
    nav_pnl.request_docking()
