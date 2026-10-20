from __future__ import annotations
import json
import os
from copy import copy

import cv2

from EDJournal import StationType
from MarketParser import MarketParser
from StatusParser import StatusParser
from time import sleep
import time
import re
import difflib
from EDlogger import logger
from Screen_Regions import Quad, load_calibrated_regions

"""
File:StationServicesInShip.py    

Description:
  TBD 

Author: Stumpii
"""


class EDStationServicesInShip:
    """ Handles Station Services In Ship. """
    def __init__(self, ed_ap, screen, keys, cb):
        self.ap = ed_ap
        self.ocr = ed_ap.ocr
        self.locale = self.ap.locale
        self.screen = screen
        self.keys = keys
        self.ap_ckb = cb
        self.passenger_lounge = PassengerLounge(self, self.ap, self.ocr, self.keys, self.screen, self.ap_ckb)
        self.commodities_market = CommoditiesMarket(self, self.ap, self.ocr, self.keys, self.screen, self.ap_ckb)
        self.status_parser = StatusParser()
        self.market_parser = MarketParser()
        # The rect is top left x, y, and bottom right x, y in fraction of screen resolution
        self.reg = {'commodities_market': {'rect': [0.0, 0.0, 0.25, 0.25]},
                    'station_services': {'rect': [0.10, 0.10, 0.90, 0.85]},
                    'connected_to': {'rect': [0.0, 0.0, 0.25, 0.1]},
                    'title': {'rect': [0.0, 0.0, 1.0, 1.0]},
                    'commodity_column': {'rect': [0.0, 0.0, 1.0, 1.0]},
                    'buy_qty_box': {'rect': [0.0, 0.0, 1.0, 1.0]},
                    'sell_qty_box': {'rect': [0.0, 0.0, 1.0, 1.0]},
                    'commodity_name': {'rect': [0.0, 0.0, 1.0, 1.0]},
                    }

        # Load custom regions from file
        load_calibrated_regions('EDStationServicesInShip', self.reg)

    def goto_station_services(self) -> bool:
        """ Goto Station Services. """
        # Go to cockpit view
        self.ap.ship_control.goto_cockpit_view()

        self.keys.send("UI_Up", repeat=3)  # go to very top (refuel line)
        self.keys.send("UI_Down")  # station services
        self.keys.send("UI_Select")  # station services

        if self.ap.debug_overlay:
            stn_svcs = Quad.from_rect(self.reg['station_services']['rect'])
            self.ap.overlay.overlay_quad_pct('stn_svcs', stn_svcs, (0, 255, 0), 2, 5)
            self.ap.overlay.overlay_paint()

        # Wait for screen to appear
        res = self.ocr.wait_for_text(self.ap, [self.locale["STN_SVCS_CONNECTED_TO"]], self.reg['connected_to'], timeout=15)

        # Store image
        # image = self.screen.get_screen_rect_pct(scl_reg['rect'])
        # cv2.imwrite(f'test/station-services/station-services.png', image)

        # Return OCR result.
        return res

    def goto_construction_services(self) -> bool:
        """ Goto Construction Services. This is for an Orbital Construction Site. """
        # Go to cockpit view
        self.ap.ship_control.goto_cockpit_view()

        self.keys.send("UI_Up", repeat=3)  # go to very top (refuel line)
        self.keys.send("UI_Down")  # station services
        self.keys.send("UI_Select")  # station services

        # TODO - replace with OCR from OCR branch?
        sleep(3)  # wait for new menu to finish rendering

        return True

    def determine_commodities_location(self) -> str:
        """ Get the services layout as the layout may be different per station.
        There is probably a better way to do this!
        @return: The string of the positions (i.e. RRD for Right-Right-Down).
        """
        station_type = self.ap.jn.ship_state()['exp_station_type']
        # CONNECTED TO menu is different between stations and fleet carriers
        if station_type == StationType.FleetCarrier:
            # Fleet Carrier COMMODITIES MARKET location top right, with:
            # uni cart, redemption, tritium depot, shipyard, crew lounge
            return "RR"

        elif station_type == StationType.SquadronCarrier:
            # Fleet Carrier COMMODITIES MARKET location top right, with:
            # uni cart, redemption, tritium depot, shipyard, crew lounge
            return "RD"

        elif station_type == StationType.Outpost:
            # Outpost COMMODITIES MARKET location in middle column
            return "R"

        else:
            # Orbital station COMMODITIES MARKET location bottom left
            return "D"

    def goto_commodities_market(self) -> bool:
        """ Go to the COMMODITIES market. """
        # Go down to station services
        res = self.goto_station_services()
        if not res:
            return False

        # Try to determine commodities button on the services screen. Have seen it below Mission Board and too
        # right of the mission board.
        res = self.determine_commodities_location()
        if res == "":
            logger.warning("Unable to find COMMODITIES MARKET button on Station Services screen.")
            return False

        self.ap_ckb('log+vce', "Connecting to commodities market.")
        try:
            market_mtime_before = self.market_parser.get_file_modified_time()
        except Exception:
            market_mtime_before = None

        # Select Mission Board
        if res == "RR":
            # Fleet Carrier COMMODITIES MARKET location top right, with:
            # uni cart, redemption, tritium depot, shipyard, crew lounge
            self.keys.send('UI_Right', repeat=2)
            self.keys.send('UI_Select')  # Select Commodities

        elif res == "RD":
            # Squadron Fleet Carrier COMMODITIES MARKET location right and one down
            self.keys.send('UI_Right')
            self.keys.send('UI_Down')
            self.keys.send('UI_Select')  # Select Commodities

        elif res == "R":
            # Outpost COMMODITIES MARKET location in middle column
            self.keys.send('UI_Right')
            self.keys.send('UI_Select')  # Select Commodities

        elif res == "D":
            # Orbital station COMMODITIES MARKET location bottom left
            self.keys.send('UI_Down')
            self.keys.send('UI_Select')  # Select Commodities

        if self.ap.debug_overlay:
            mkt = Quad.from_rect(self.reg['commodities_market']['rect'])
            self.ap.overlay.overlay_quad_pct('commodities_market', mkt, (0, 255, 0), 2, 5)
            self.ap.overlay.overlay_paint()

        # Wait for screen to appear. The game writes Market.json when the market is opened, that is a fast and
        # reliable confirmation. The OCR check of the title (slow, depends on the calibration and failed on
        # 3440x1440 every time, costing 15 s per station) is only the fallback.
        if market_mtime_before is not None:
            t0 = time.time()
            while time.time() - t0 < 6.0:
                sleep(0.25)
                try:
                    if self.market_parser.get_file_modified_time() != market_mtime_before:
                        logger.debug("Commodities market confirmed by Market.json update.")
                        sleep(1.0)  # let the screen finish building
                        return True
                except Exception:
                    break
        res = self.ocr.wait_for_text(self.ap, [self.locale["COMMODITIES_MARKET"]], self.reg['title'], timeout=10)
        return res

    @staticmethod
    def sell_to_colonisation_ship(ap):
        """ Sell all cargo to a colonisation/construction ship.
        """
        ap.keys.send('UI_Left', repeat=3)  # Go to table
        ap.keys.send('UI_Down', hold=2)  # Go to bottom
        ap.keys.send('UI_Up')  # Select RESET/CONFIRM TRANSFER/TRANSFER ALL
        ap.keys.send('UI_Left', repeat=2)  # Go to RESET
        ap.keys.send('UI_Right', repeat=2)  # Go to TRANSFER ALL
        ap.keys.send('UI_Select')  # Select TRANSFER ALL
        sleep(0.5)

        ap.keys.send('UI_Left')  # Go to CONFIRM TRANSFER
        ap.keys.send('UI_Select')  # Select CONFIRM TRANSFER
        sleep(2)

        ap.keys.send('UI_Down')  # Go to EXIT
        ap.keys.send('UI_Select')  # Select EXIT

        sleep(2)  # give time to popdown menu


class PassengerLounge:
    def __init__(self, station_services_in_ship: EDStationServicesInShip, ed_ap, ocr, keys, screen, cb):
        self.parent = station_services_in_ship
        self.ap = ed_ap
        self.ocr = ocr
        self.keys = keys
        self.screen = screen
        self.ap_ckb = cb

        # The rect is top left x, y, and bottom right x, y in fraction of screen resolution
        # Nav Panel region covers the entire navigation panel.
        self.reg = {'no_cmpl_missions': {'rect': [0.47, 0.77, 0.675, 0.85]},
                    'mission_dest_col': {'rect': [0.47, 0.41, 0.64, 0.85]},
                    'complete_mission_col': {'rect': [0.47, 0.22, 0.675, 0.85]}}

        self.no_cmpl_missions_row_width = 384  # Buy/sell item width in pixels at 1920x1080
        self.no_cmpl_missions_row_height = 70  # Buy/sell item height in pixels at 1920x1080
        self.mission_dest_row_width = 326  # Buy/sell item width in pixels at 1920x1080
        self.mission_dest_row_height = 70  # Buy/sell item height in pixels at 1920x1080
        self.complete_mission_row_width = 384  # Buy/sell item width in pixels at 1920x1080
        self.complete_mission_row_height = 70  # Buy/sell item height in pixels at 1920x1080


class CommoditiesMarket:
    def __init__(self, station_services_in_ship: EDStationServicesInShip, ed_ap, ocr, keys, screen, cb):
        self.parent = station_services_in_ship
        self.ap = ed_ap
        self.ocr = ocr
        self.keys = keys
        self.screen = screen
        self.ap_ckb = cb

        self.market_parser = MarketParser()
        # The reg rect is top left x, y, and bottom right x, y in fraction of screen resolution at 1920x1080
        self.reg = {'cargo_col': {'rect': [0.13, 0.227, 0.19, 0.90]},
                    'commodity_name_col': {'rect': [0.19, 0.227, 0.41, 0.90]},
                    'supply_demand_col': {'rect': [0.42, 0.227, 0.49, 0.90]},
                    # Large name of the highlighted commodity in the info panel right of the list
                    # 0.70 cut off the start of the name ('TICAPPLIANCES' for DOMESTIC APPLIANCES, 'SILVER' not
                    # readable, 2026-10-20 18:29/18:45). 0.678 still cut 'PE' of PERFORMANCE ENHANCERS (20:13).
                    'selected_name': {'rect': [0.655, 0.183, 0.99, 0.228]},
                    # Title of the BUY/SELL COMMODITY dialog ('SELL COMMODITY' at x 0.27-0.41, y 0.20-0.23 in
                    # the video of session 2026-10-20_16-57-51). Without the dialog only the list header is there.
                    'dialog_title': {'rect': [0.25, 0.185, 0.52, 0.240]}}
        self.last_select_failed = False  # the last buy/sell could not select the commodity in the list
        self.last_select_info = ''  # how the last list selection was checked (for the market test)
        self.last_dialog_info = ''  # what happened with the BUY/SELL dialog after the last transaction
        self.commodity_row_width = 422  # Buy/sell item width in pixels at 1920x1080
        self.commodity_row_height = 35  # Buy/sell item height in pixels at 1920x1080

    @staticmethod
    def _norm(txt: str) -> str:
        return re.sub(r'[^A-Z0-9]', '', (txt or '').upper())

    def _selected_commodity_name(self) -> str | None:
        """ OCR of the name of the highlighted commodity (info panel right of the list). The panel fades in after
        the highlight moved, so a second read is done if the first one is empty. """
        for attempt in range(2):
            try:
                img = self.screen.get_screen_rect_pct(self.reg['selected_name']['rect'])
                txt = self.ocr.image_simple_ocr(img, 'commodity_selected') if img is not None else None
            except Exception as e:
                logger.debug(f"_selected_commodity_name: {e}")
                txt = None
            if txt:
                return " ".join(str(t) for t in txt)
            sleep(0.5)
        return None

    # Words of the BUY/SELL dialog title in the supported game languages
    DIALOG_MARKERS = ('COMMODITY', 'WARE', 'MARCHANDISE', 'MERCANC', 'ТОВАР')

    def _dialog_open(self) -> bool | None:
        """ True if the BUY/SELL COMMODITY dialog is open, False if not, None if the area could not be read. """
        try:
            img = self.screen.get_screen_rect_pct(self.reg['dialog_title']['rect'])
            txt = self.ocr.image_simple_ocr(img, 'commodity_dialog') if img is not None else None
        except Exception as e:
            logger.debug(f"_dialog_open: {e}")
            return None
        joined = " ".join(str(t) for t in (txt or [])).upper()
        found = any(m in joined for m in self.DIALOG_MARKERS)
        logger.debug(f"Market dialog check: {txt} -> {'open' if found else 'closed'}")
        return found

    def in_station_menu(self) -> bool:
        """ True if the station menu ('CONNECTED TO ...') is shown instead of the commodities market. """
        try:
            found, _ = self.ocr.is_text_in_region(self.ap.locale["STN_SVCS_CONNECTED_TO"],
                                                  self.parent.reg['connected_to'])
            return bool(found)
        except Exception as e:
            logger.debug(f"in_station_menu: {e}")
            return False

    def ensure_market_open(self) -> bool:
        """ Makes sure the commodities market is shown (and not the station menu). Before, an UI_Back after a
        transaction left the market when the game had already closed the dialog itself; the following keys
        then went into the station menu and opened the mission board (video 2026-10-20 17:22). """
        if not self.in_station_menu():
            return True
        self.ap_ckb('log', "Commodities market was left, opening it again.")
        return self.parent.goto_commodities_market()

    def _close_dialog_after_transaction(self, keys):
        """ After buying/selling the game closes the dialog itself (videos 2026-10-20), but it has also been seen
        staying open (0/0, CANCEL selected, video 2026-10-19). UI_Back only if it is still open: a blind UI_Back
        leaves the market when the dialog is already closed. """
        sleep(1.0)
        backs = 0
        for _ in range(2):
            state = self._dialog_open()
            if state:
                logger.debug("Market dialog still open, closing it with UI_Back.")
                keys.send('UI_Back')
                backs += 1
                sleep(0.8)
                continue
            break
        if state is None:
            logger.debug("Market dialog state unknown (not readable), no UI_Back.")
            self.last_dialog_info = "dialog state not readable, no UI_Back"
        elif backs:
            self.last_dialog_info = f"dialog stayed open, closed with {backs}x UI_Back"
        else:
            self.last_dialog_info = "dialog closed by the game"

    def _match_item(self, ocr_name: str, items: list) -> int | None:
        """ Index of the list item that best matches the OCR text, or None. """
        n = self._norm(ocr_name)
        if not n:
            return None
        best, best_i = 0.0, None
        for i, it in enumerate(items):
            m = self._norm(it['Name_Localised'])
            r = 1.0 if m == n else difflib.SequenceMatcher(None, m, n).ratio()
            if r > best:
                best, best_i = r, i
        return best_i if best >= 0.8 else None

    def _goto_list_item(self, keys, items: list, index: int, name: str) -> bool:
        """ Moves the list highlight to items[index] and checks it with OCR of the info panel.
        Counting key presses alone is not reliable: at Orbital Sanctum one of 37 'down' presses got lost and
        EDAP opened the buy dialog of LITHIUM instead of SILVER (video 2026-10-19). If the OCR shows another item
        of the list, the difference is corrected with up/down. If the name can not be read at all, the counted
        position is used as before. Returns False only if the right item could not be reached. """
        n = len(items)
        per_item = 0.2  # one 'down' press incl. pause
        # 1. Where is the highlight now? Usually at the top of the list after entering it: if the name can be read,
        #    the 5 s 'hold up' is not needed.
        sleep(0.4)
        cur = self._selected_commodity_name()
        cur_i = self._match_item(cur, items) if cur else None
        if cur_i is not None:
            direct = abs(index - cur_i) * per_item
            bottom_hold = max(3.0, 0.08 * n)
            via_bottom = bottom_hold + 1.0 + (n - 1 - index) * per_item
            if via_bottom < direct - 2.0:
                # Item far down the list: go to the bottom and count up (Rutile at 82 of 85 needed 81 presses, 16 s)
                keys.send('UI_Down', hold=bottom_hold)
                sleep(0.6)
                cur = self._selected_commodity_name()
                cur_i2 = self._match_item(cur, items) if cur else None
                start_i = cur_i2 if cur_i2 is not None else n - 1
                logger.debug(f"Market list: from the bottom (at {start_i + 1} of {n}), moving {index - start_i:+d}.")
                self._move(keys, index - start_i)
            else:
                logger.debug(f"Market list: highlight at '{items[cur_i]['Name_Localised']}', moving "
                             f"{index - cur_i:+d} to '{name}'.")
                self._move(keys, index - cur_i)
        else:
            # 2. Name not readable: counted from the top as before
            keys.send('UI_Up', hold=5.0)  # go up to top of list
            sleep(1.0)
            if index > 0:
                keys.send('UI_Down', hold=0.08, repeat=index, repeat_delay=0.12)
        corrected = 0
        stepped = 0
        max_steps = 30
        attempt = 0
        while attempt < 4:
            sleep(0.7)
            cur = self._selected_commodity_name()
            if cur is None:
                if stepped:
                    sleep(0.5)
                    cur = self._selected_commodity_name()
                if cur is None:
                    if stepped:
                        self.last_select_info = "FAILED: name not readable while searching the list"
                        return False
                    logger.debug(f"Market list: selected commodity not readable, using counted position for '{name}'.")
                    self.last_select_info = "name not readable, counted position used"
                    return True
            if self._norm(name) and self._norm(name) == self._norm(cur):
                self.last_select_info = f"OCR confirmed ('{cur}')" + (f", corrected {corrected}x" if corrected else "")
                return True
            cur_i = self._match_item(cur, items)
            if cur_i is None:
                if self._norm(name) in self._norm(cur):
                    self.last_select_info = f"OCR confirmed ('{cur}')"
                    return True
                # A commodity of this market that is not in EDAP's list: the game shows more items in the list than
                # EDAP counts (PERFORMANCE ENHANCERS with stock 0 in the BUY list at Stiegler Dock, 2026-10-20 20:13,
                # all positions after it were off by one and Bertrandite was never bought). Step towards the target
                # one item at a time and read the name after every step.
                all_items = self._all_items_sorted()
                j = self._match_item(cur, all_items)
                t = next((k for k, it in enumerate(all_items)
                          if self._norm(it['Name_Localised']) == self._norm(name)), None)
                if j is not None and j == t:
                    self.last_select_info = f"OCR confirmed ('{cur}')"
                    return True
                if j is not None and t is not None and j != t and stepped < max_steps:
                    step = 1 if t > j else -1
                    logger.info(f"Market list: '{all_items[j]['Name_Localised']}' (not in EDAP's list) selected, "
                                f"stepping {'down' if step > 0 else 'up'} to '{name}'.")
                    self._move(keys, step)
                    stepped += 1
                    corrected += 1
                    continue
                # A text that is no commodity: are we still in the market? ('NEUTBAL'/'CORDIAI' were the
                # reputation of the station menu, EDAP had left the market and opened the mission board.)
                if self.in_station_menu():
                    self.ap_ckb('log', f"Market list: not in the commodities market (read '{cur}').")
                    self.last_select_info = f"FAILED: not in the market (read '{cur}')"
                    return False
                if j is not None:
                    # A known commodity, but not the target: buying here would buy the wrong one.
                    self.last_select_info = f"FAILED: '{cur}' selected instead of '{name}'"
                    return False
                logger.debug(f"Market list: OCR '{cur}' does not match a list item, using counted position.")
                self.last_select_info = f"OCR '{cur}' is no list item, counted position used"
                return True
            if cur_i == index:
                logger.debug(f"Market list: '{name}' selected (OCR '{cur}').")
                self.last_select_info = f"OCR confirmed ('{cur}')" + (f", corrected {corrected}x" if corrected else "")
                return True
            corrected += 1
            attempt += 1
            delta = index - cur_i
            if attempt >= 3 and abs(delta) <= 3:
                # The same small offset again (items in the game list that EDAP does not know): single steps
                delta = 1 if delta > 0 else -1
            logger.info(f"Market list: '{items[cur_i]['Name_Localised']}' selected instead of '{name}', "
                        f"correcting by {delta:+d}.")
            if delta > 0:
                keys.send('UI_Down', hold=0.08, repeat=delta, repeat_delay=0.15)
            else:
                keys.send('UI_Up', hold=0.08, repeat=-delta, repeat_delay=0.15)
            if attempt >= 3 and stepped < max_steps:
                attempt = 2  # keep stepping while the OCR shows progress, limited by max_steps
                stepped += 1
        self.last_select_info = "FAILED: could not reach the item after 4 corrections"
        return False

    def _all_items_sorted(self) -> list:
        """ All commodities of Market.json in the order of the game list (category, then name), including the
        ones EDAP does not count as buyable/sellable. """
        data = self.market_parser.current_data or {}
        items = [i for i in data.get('Items', []) if i.get('Name_Localised')]
        items = sorted(items, key=lambda x: x['Name_Localised'].lower())
        return sorted(items, key=lambda x: (x.get('Category_Localised') or '').lower())

    @staticmethod
    def _move(keys, delta: int):
        if delta > 0:
            keys.send('UI_Down', hold=0.08, repeat=delta, repeat_delay=0.12)
        elif delta < 0:
            keys.send('UI_Up', hold=0.08, repeat=-delta, repeat_delay=0.12)

    def select_buy(self, keys) -> bool:
        """ Select Buy. Assumes on Commodities Market screen. """
        if not self.ensure_market_open():
            return False

        # Select Buy
        keys.send("UI_Left", repeat=2)
        keys.send("UI_Up", repeat=4)

        keys.send("UI_Select")  # Select Buy

        sleep(0.5)  # give time to bring up list
        keys.send('UI_Right')  # Go to top of commodities list
        return True

    def select_sell(self, keys) -> bool:
        """ Select Sell. Assumes on Commodities Market screen. """
        if not self.ensure_market_open():
            return False

        # Select Buy
        keys.send("UI_Left", repeat=2)
        keys.send("UI_Up", repeat=4)

        keys.send("UI_Down")
        keys.send("UI_Select")  # Select Sell

        sleep(0.5)  # give time to bring up list
        keys.send('UI_Right')  # Go to top of commodities list
        return True

    def buy_commodity(self, keys, name: str, qty: int, free_cargo: int) -> tuple[bool, int]:
        """ Buy qty of commodity. If qty >= 9999 then buy as much as possible.
        Assumed to be in the commodities buy screen in the list. """

        # If we are updating requirement count, me might have all the qty we need
        if qty <= 0:
            return False, 0

        # Determine if station sells the commodity!
        self.market_parser.get_market_data()
        if not self.market_parser.can_buy_item(name):
            self.ap_ckb('log+vce', f"'{name}' is not sold or has no stock at {self.market_parser.get_market_name()}.")
            logger.debug(f"Item '{name}' is not sold or has no stock at {self.market_parser.get_market_name()}.")
            return False, 0

        # Find commodity in market and return the index
        index = -1
        stock = 0
        buyable_items = self.market_parser.get_buyable_items()
        if buyable_items is not None:
            for i, value in enumerate(buyable_items):
                if value['Name_Localised'].upper() == name.upper():
                    index = i
                    stock = value['Stock']
                    logger.debug(f"Execute trade: Buy {name} (want {qty} of {stock} avail.) at position {index + 1}.")
                    break

        # Actual qty we can sell
        act_qty = min(qty, stock, free_cargo)

        # See if we buy all and if so, remove the item to update the list, as the item will be removed
        # from the commodities screen, but the market.json will not be updated.
        buy_all = act_qty == stock
        if buy_all:
            for i, value in enumerate(self.market_parser.current_data['Items']):
                if value['Name_Localised'].upper() == name.upper():
                    # Set the stock bracket to 0, so it does not get included in available commodities list.
                    self.market_parser.current_data['Items'][i]['StockBracket'] = 0

        if index > -1:
            self.last_select_failed = False
            if not self._goto_list_item(keys, buyable_items, index, name):
                self.last_select_failed = True
                self.ap_ckb('log+vce', f"Could not select {name} in the market list, not buying.")
                return False, 0

            # # Get the goods panel image
            # goods_panel = self.capture_goods_panel()
            # if goods_panel is None:
            #     return False, 0
            #
            # # Find the selected item/menu (solid orange)
            # img_selected, quad = self.ocr.get_highlighted_item_in_image(goods_panel,
            #                                                             self.parent.sub_reg_size['commodity_name']['width'],
            #                                                             self.parent.sub_reg_size['commodity_name']['height'])
            # # Check if end of list.
            # if img_selected is None:
            #     # logger.debug(f"Off end of list. Did not find '{dst_name}' in list.")
            #     return False, 0
            #
            # if self.ap.debug_overlay:
            #     # Scale the selected item down to the scale of the tab bar
            #     loc_pnl_quad = Quad.from_rect(self.parent.sub_reg['location_panel']['rect'])
            #
            #     # Overlay OCR result
            #     self.ap.overlay.overlay_quad_pix('nav_panel_item', q_out, (0, 255, 0), 2)
            #     self.ap.overlay.overlay_paint()
            #
            #     # OCR the selected item
            #     sim_match = 0.8  # Similarity match 0.0 - 1.0 for 0% - 100%)
            #     ocr_textlist = self.ocr.image_simple_ocr(img_selected)
            #     if ocr_textlist is not None:
            #         if self.ap.debug_overlay:
            #             # Overlay OCR result
            #             self.ap.overlay.overlay_floating_text('nav_panel_item_text', f'{str(ocr_textlist)}',
            #                                                   q_out.left, q_out.top - 25, (0, 255, 0))
            #             self.ap.overlay.overlay_paint()

            sleep(0.75)
            keys.send('UI_Select')  # Select that commodity

            if self.ap.debug_overlay:
                q = Quad.from_rect(self.parent.reg['buy_qty_box']['rect'])
                self.ap.overlay.overlay_quad_pct('buy_qty_box', q, (0, 255, 0), 2, 5)
                self.ap.overlay.overlay_paint()

            sleep(0.5)  # give time to popup
            keys.send('UI_Up', repeat=2)  # go up to quantity to buy (may not default to this)
            # Log the planned quantity
            self.ap_ckb('log+vce', f"Buying {act_qty} units of {name}.")
            logger.info(f"Attempting to buy {act_qty} units of {name}")
            # Increment count
            if qty >= 9999 or qty >= stock or qty >= free_cargo:
                keys.send("UI_Right", hold=4)
            else:
                keys.send("UI_Right", hold=0.04, repeat=act_qty)
            keys.send('UI_Down')
            keys.send('UI_Select')  # Select Buy
            sleep(1.5)  # transaction
            self._close_dialog_after_transaction(keys)

        return True, act_qty

    def sell_commodity(self, keys, name: str, qty: int, cargo_parser) -> tuple[bool, int]:
        """ Sell qty of commodity. If qty >= 9999 then sell as much as possible.
        Assumed to be in the commodities sell screen in the list.
        @param keys: Keys class for sending keystrokes.
        @param name: Name of the commodity.
        @param qty: Quantity to sell.
        @param cargo_parser: Current cargo to check if rare or demand=1 items exist in hold.
        @return: Sale successful (T/F) and Qty.
        """

        # If we are updating requirement count, me might have sold all we have
        if qty <= 0:
            return False, 0



        # Determine if station buys the commodity!
        self.market_parser.get_market_data()
        if not self.market_parser.can_sell_item(name):
            self.ap_ckb('log+vce', f"'{name}' is not bought at {self.market_parser.get_market_name()}.")
            logger.debug(f"Item '{name}' is not bought at {self.market_parser.get_market_name()}.")
            return False, 0

        # Find commodity in market and return the index
        index = -1
        demand = 0
        sellable_items = self.market_parser.get_sellable_items(cargo_parser)
        if sellable_items is not None:
            for i, value in enumerate(sellable_items):
                if value['Name_Localised'].upper() == name.upper():
                    index = i
                    demand = value['Demand']
                    logger.debug(f"Execute trade: Sell {name} ({qty} of {demand} demanded) at position {index + 1}.")
                    break

        # Check how many of the item do we have.
        qty_in_cargo = 9999
        if cargo_parser.get_item(name) is not None:
            cargo_item = cargo_parser.get_item(name)
            qty_in_cargo = cargo_item['Count']

        # Qty we can sell. Unlike buying, we can sell more than the demand
        # But maybe not at all stations!
        act_qty = min(qty, qty_in_cargo)

        if index > -1:
            self.last_select_failed = False
            if not self._goto_list_item(keys, sellable_items, index, name):
                self.last_select_failed = True
                self.ap_ckb('log+vce', f"Could not select {name} in the market list, not selling.")
                return False, 0

            sleep(0.75)
            keys.send('UI_Select')  # Select that commodity

            if self.ap.debug_overlay:
                q = Quad.from_rect(self.parent.reg['sell_qty_box']['rect'])
                self.ap.overlay.overlay_quad_pct('sell_qty_box', q, (0, 255, 0), 2, 5)
                self.ap.overlay.overlay_paint()

            sleep(0.5)  # give time for popup
            keys.send('UI_Up', repeat=2)  # make sure at top

            # Sell all if quantity is 9999 or if we are selling
            if act_qty >= 9999 or qty_in_cargo <= act_qty:
                self.ap_ckb('log+vce', f"Selling all our units of {name}.")
                logger.info(f"Attempting to sell all our units of {name}")
                keys.send("UI_Right", hold=4)
            else:
                self.ap_ckb('log+vce', f"Selling {act_qty} units of {name}.")
                logger.info(f"Attempting to sell {act_qty} units of {name}")
                keys.send('UI_Left', hold=4.0)  # Clear quantity to 0
                keys.send("UI_Right", hold=0.04, repeat=act_qty)

            keys.send('UI_Down')  # Down to the Sell button (already assume sell all)
            keys.send('UI_Select')  # Select to Sell all
            sleep(1.5)  # transaction
            self._close_dialog_after_transaction(keys)

        return True, act_qty

    def capture_goods_panel(self):
        """ Get the location panel from within the nav panel.
        Returns an image, or None.
        """
        # Scale the regions based on the target resolution.
        region = self.parent.reg['commodity_column']
        img = self.ocr.capture_region_pct(region)
        if img is None:
            return False

        if self.ap.debug_overlay:
            # Offset to match the nav panel offset
            q = Quad.from_rect(self.parent.reg['commodity_column']['rect'])
            self.ap.overlay.overlay_quad_pix('capture_goods_panel', q, (0, 255, 0), 2, 5)
            self.ap.overlay.overlay_paint()

        return img


def dummy_cb(msg, body=None):
    pass


# Usage Example
if __name__ == "__main__":
    from ED_AP import EDAutopilot
    test_ed_ap = EDAutopilot(cb=dummy_cb)
    test_ed_ap.keys.activate_window = True
    svcs = EDStationServicesInShip(test_ed_ap, test_ed_ap.scr, test_ed_ap.keys, test_ed_ap.ap_ckb)
    # svcs.goto_station_services()
    # svcs.goto_commodities_market()

    while 1:
        load_calibrated_regions('EDStationServicesInShip', svcs.reg)

        for key, value in svcs.reg.items():
            commodities_market = Quad.from_rect(svcs.reg[key]['rect'])
            test_ed_ap.overlay.overlay_quad_pct(key, commodities_market, (0, 255, 0), 2, 7)

        # commodities_market = Quad.from_rect(svcs.reg['commodities_market']['rect'])
        # test_ed_ap.overlay.overlay_quad_pct('commodities_market', commodities_market, (0, 255, 0), 2, 7)
        #
        # commodity_column = Quad.from_rect(svcs.reg['commodity_column']['rect'])
        # test_ed_ap.overlay.overlay_quad_pct('commodity_column', commodity_column, (0, 255, 0), 2, 7)
        #
        # buy_qty_box = Quad.from_rect(svcs.reg['buy_qty_box']['rect'])
        # test_ed_ap.overlay.overlay_quad_pct('buy_qty_box', buy_qty_box, (0, 255, 0), 2, 7)

        test_ed_ap.overlay.overlay_paint()

        sleep(0.5)
