from __future__ import annotations

import os
import time
from time import sleep
from CargoParser import CargoParser
from EDAP_data import *
from EDJournal import StationType
from EDKeys import EDKeys
from EDlogger import logger
from EDTradeAdapt import adapt_buy_list
from EDFuelPlanner import estimate_route_fuel
import json
from MarketParser import MarketParser
from MousePt import MousePoint
from pathlib import Path

"""
File: EDWayPoint.py    

Description:
   Class will load file called waypoints.json which contains a list of System name to jump to.
   Provides methods to select a waypoint pass into it.  

Author: sumzer0@yahoo.com
"""


class EDWayPoint:
    def __init__(self, ed_ap, cb, is_odyssey=True):
        self.ap = ed_ap
        self.ap_ckb = cb
        # self.is_odyssey = is_odyssey
        self.filename = ''
        self.stats_log = {'Colonisation': 0, 'Construction': 0, 'Fleet Carrier': 0, 'Station': 0}
        self.waypoints = {}
        self._replot_after_trade = False  # set after a trade: plot the route to the next system again
        self.num_waypoints = 0
        self.step = 0
        #  { "Ninabin": {"DockWithTarget": false, "TradeSeq": None, "Completed": false} }
        # for i, key in enumerate(self.waypoints):
        # self.waypoints[target]['DockWithTarget'] == True ... then go into SC Assist
        # self.waypoints[target]['Completed'] == True
        # if docked and self.waypoints[target]['Completed'] == False
        #    execute_seq(self.waypoints[target]['TradeSeq'])

        # ss = self._read_waypoints()
        #
        # # if we read it then point to it, otherwise use the default table above
        # if ss is not None:
        #     self.waypoints = ss
        #     logger.debug("EDWayPoint: read json:" + str(ss))
        #
        # self.num_waypoints = len(self.waypoints)

        # print("waypoints: "+str(self.waypoints))

        # self.mouse = MousePoint()
        self.market_parser = MarketParser()
        self.cargo_parser = CargoParser()

    def load_waypoint_file(self, filename='./waypoints/waypoints.json') -> bool:
        if not os.path.exists(filename):
            return False

        ss = self._read_waypoints(filename)

        if ss is not None:
            self.waypoints = ss
            self.num_waypoints = len(self.waypoints)
            self.filename = filename
            self.ap.config['WaypointFilepath'] = filename
            self.ap_ckb('log', f"Loaded Waypoint file: {filename}")
            logger.debug("EDWayPoint: read json:" + str(ss))
            return True

        self.ap_ckb('log', f"Waypoint file is invalid. Check log file for details.")
        return False

    def _read_waypoints(self, filename='./waypoints/waypoints.json'):
        if not os.path.exists(filename):
            return None

        s = None
        self.ap.config['WaypointFilepath'] = filename
        try:
            with open(filename, "r") as fp:
                s = json.load(fp)

            # Perform any checks on the data returned
            # Check if the waypoint data contains the 'GlobalShoppingList' (new requirement)
            if 'GlobalShoppingList' not in s:
                # self.ap_ckb('log', f"Waypoint file is invalid. Check log file for details.")
                logger.warning(f"Waypoint file {filename} is invalid or old version. "
                               f"It does not contain a 'GlobalShoppingList' waypoint.")
                s = None

            # Check the
            err = False
            for key, value in s.items():
                if key == 'GlobalShoppingList':
                    # Special case
                    if 'BuyCommodities' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'BuyCommodities'.")
                        err = True
                    if 'UpdateCommodityCount' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'UpdateCommodityCount'.")
                        err = True
                    if 'Skip' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'Skip'.")
                        err = True
                else:
                    # All other cases
                    if 'SystemName' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'SystemName'.")
                        err = True
                    if 'StationName' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'StationName'.")
                        err = True
                    if 'GalaxyBookmarkType' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'GalaxyBookmarkType'.")
                        err = True
                    if 'GalaxyBookmarkNumber' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'GalaxyBookmarkNumber'.")
                        err = True
                    if 'SystemBookmarkType' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'SystemBookmarkType'.")
                        err = True
                    if 'SystemBookmarkNumber' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'SystemBookmarkNumber'.")
                        err = True
                    if 'SellCommodities' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'SellCommodities'.")
                        err = True
                    if 'BuyCommodities' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'BuyCommodities'.")
                        err = True
                    if 'UpdateCommodityCount' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'UpdateCommodityCount'.")
                        err = True
                    if 'FleetCarrierTransfer' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'FleetCarrierTransfer'.")
                        err = True
                    if 'Skip' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'Skip'.")
                        err = True
                    if 'Completed' not in value:
                        logger.warning(f"Waypoint file key '{key}' does not contain 'Completed'.")
                        err = True

            if err:
                s = None

        except Exception as e:
            logger.warning("EDWayPoint.py read_waypoints error :" + str(e))

        return s

    def write_waypoints(self, data, filename='./waypoints/waypoints.json'):
        if data is None:
            data = self.waypoints
        try:
            self.ap.config['WaypointFilepath'] = filename
            with open(filename, "w") as fp:
                json.dump(data, fp, indent=4)
        except Exception as e:
            logger.warning("EDWayPoint.py write_waypoints error:" + str(e))

    def mark_waypoint_complete(self, key):
        self.waypoints[key]['Completed'] = True
        self.write_waypoints(data=None, filename='./waypoints/' + Path(self.filename).name)

    def get_waypoint(self) -> tuple[str, dict] | tuple[None, None]:
        """ Returns the next waypoint list or None if we are at the end of the waypoints.
        """
        dest_key = "-1"

        # loop back to beginning if last record is "REPEAT"
        while dest_key == "-1":
            for i, key in enumerate(self.waypoints):
                # skip records we already processed
                if i < self.step:
                    continue

                # if this entry is REPEAT (and not skipped), mark them all as Completed = False
                if ((self.waypoints[key].get('SystemName', "").upper() == "REPEAT")
                        and not self.waypoints[key]['Skip']):
                    self.mark_all_waypoints_not_complete()
                    break

                # if this step is marked to skip... i.e. completed, go to next step
                if (key == "GlobalShoppingList" or self.waypoints[key]['Completed']
                        or self.waypoints[key]['Skip']):
                    continue

                # This is the next uncompleted step
                self.step = i
                dest_key = key
                break
            else:
                return None, None

        return dest_key, self.waypoints[dest_key]

    def _start_at_docked_station(self):
        """ When Waypoint Assist is started while docked at the station of a waypoint, that waypoint becomes the
        current one: all waypoints before it are marked completed, it and all after it are marked open. The normal
        loop then sees 'Already at target Station' and executes the trade of this waypoint. """
        try:
            if not self.ap.status.get_flag(FlagsDocked):
                return
            cur_system = self.ap.jn.ship_state()['cur_star_system'].upper()
            cur_station = self.ap.jn.ship_state()['cur_station'].upper()
        except Exception as e:
            logger.warning(f"_start_at_docked_station: {e}")
            return
        if not cur_station:
            return

        keys = list(self.waypoints.keys())
        match_idx = None
        for i, key in enumerate(keys):
            wp = self.waypoints[key]
            if key == "GlobalShoppingList" or wp.get('Skip', False):
                continue
            wp_system = wp.get('SystemName', '').upper()
            wp_station = wp.get('StationName', '').upper()
            if wp_system == "REPEAT" or not wp_station:
                continue
            # Fleet/Squadron carriers: the journal only reports the ID (ABC-123) at the end of the name
            same_station = (wp_station == cur_station or wp_station.endswith(cur_station))
            same_system = (wp_system == "" or wp_system == cur_system)
            if same_station and same_system:
                match_idx = i
                break

        if match_idx is None:
            self.ap_ckb('log', f"Docked at {cur_station}, which is not a station of this waypoint file.")
            return

        changed = False
        for i, key in enumerate(keys):
            if key == "GlobalShoppingList" or 'Completed' not in self.waypoints[key]:
                continue
            should_be_completed = i < match_idx
            if self.waypoints[key]['Completed'] != should_be_completed:
                self.waypoints[key]['Completed'] = should_be_completed
                changed = True
        if changed:
            self.write_waypoints(data=None, filename='./waypoints/' + Path(self.filename).name)

        self.ap_ckb('log+vce', f"Already docked at waypoint station {cur_station}. "
                               f"Continuing the route from here.")

    def mark_all_waypoints_not_complete(self):
        for j, tkey in enumerate(self.waypoints):
            # Ensure 'Completed' key exists before trying to set it
            if 'Completed' in self.waypoints[tkey]:
                self.waypoints[tkey]['Completed'] = False
            else:
                # Handle legacy format where 'Completed' might be missing
                # Or log a warning if the structure is unexpected
                logger.warning(f"Waypoint {tkey} missing 'Completed' key during reset.")
            self.step = 0
        self.write_waypoints(data=None, filename='./waypoints/' + Path(self.filename).name)
        self.log_stats()

    def log_stats(self):
        calc1 = 1.5 ** self.stats_log['Colonisation']
        calc2 = 1.5 ** self.stats_log['Construction']
        sleep(max(calc1, calc2))

    def _buy_verified(self, ap, name: str, qty_to_buy: int, free_cargo: int) -> int:
        """ Buys and checks the cargo count in Status.json afterwards. Before, 'Bought 752 units' was logged even
        when nothing was bought (no MarketBuy, cargo 0) and the ship flew the whole route empty.
        On failure the market is left and entered again and the purchase is tried once more.
        Returns the quantity actually bought. """
        mkt = self.ap.stn_svcs_in_ship.commodities_market
        attempts = max(1, int(self.ap.config.get('TradeBuyAttempts', 2) or 2))
        for attempt in range(1, attempts + 1):
            before = int(ap.status.get_cleaned_data()['Cargo'])
            ts = ap.status.current_data['timestamp']
            mkt.last_select_failed = False
            result, qty = mkt.buy_commodity(ap.keys, name, qty_to_buy, free_cargo)
            if qty <= 0 and not mkt.last_select_failed:
                return 0  # nothing to buy / not sold here (already logged)
            if qty > 0:
                ap.status.wait_for_file_change(ts, 6)
                sleep(0.5)
            after = int(ap.status.get_cleaned_data()['Cargo'])
            bought = after - before
            if bought > 0:
                if bought < qty:
                    self.ap_ckb('log', f"Bought only {bought} of {qty} units of {name}.")
                return bought
            if mkt.last_select_failed:
                self.ap_ckb('log+vce', f"Could not select {name} in the market.")
            else:
                self.ap_ckb('log+vce', f"Purchase of {name} not confirmed, cargo unchanged ({after} t).")
            if attempt < attempts:
                self.ap_ckb('log', f"Leaving and re-entering the market, trying again ({attempt + 1}/{attempts}).")
                ap.keys.send('UI_Back', repeat=4)
                sleep(2)
                self.ap.stn_svcs_in_ship.goto_commodities_market()
                sleep(1)
                mkt.select_buy(ap.keys)
        self._trade_failed = True
        self.ap_ckb('log+vce', f"Unable to buy {name}.")
        return 0

    def execute_trade(self, ap, dest_key):
        # Get trade commodities from waypoint
        sell_commodities = self.waypoints[dest_key]['SellCommodities']
        buy_commodities = self.waypoints[dest_key]['BuyCommodities']
        fleetcarrier_transfer = self.waypoints[dest_key]['FleetCarrierTransfer']
        global_buy_commodities = self.waypoints['GlobalShoppingList']['BuyCommodities']

        self._trade_failed = False
        if len(sell_commodities) == 0 and len(buy_commodities) == 0 and len(global_buy_commodities) == 0:
            return

        ap.random_pause(4.0, 1.0)  # optional (EnableRandomness): do not start trading at a fixed time after docking

        # Does this place have commodities service?
        # From the journal, this works for stations (incl. outpost), colonisation ship and megaships
        if ap.jn.ship_state()['StationServices'] is not None:
            if 'commodities' not in ap.jn.ship_state()['StationServices']:
                self.ap_ckb('log', f"No commodities market at docked location.")
                return
        else:
            self.ap_ckb('log', f"No station services at docked location.")
            return

        # Determine type of station we are at
        station_type = ap.jn.ship_state()['exp_station_type']

        if station_type == StationType.ColonisationShip or station_type == StationType.SpaceConstructionDepot:
            if station_type == StationType.ColonisationShip:
                # Colonisation Ship
                self.stats_log['Colonisation'] = self.stats_log['Colonisation'] + 1
                self.ap_ckb('log', f"Executing trade with Colonisation Ship.")
                logger.debug(f"Execute Trade: On Colonisation Ship")
            if station_type == StationType.SpaceConstructionDepot:
                # Construction Ship
                self.stats_log['Construction'] = self.stats_log['Construction'] + 1
                self.ap_ckb('log', f"Executing trade with Orbital Construction Ship.")
                logger.debug(f"Execute Trade: On Orbital Construction Site")

            # Go to station services
            self.ap.stn_svcs_in_ship.goto_construction_services()

            # --------- SELL ----------
            if len(sell_commodities) > 0:
                # Sell all to colonisation/construction ship
                self.sell_to_colonisation_ship(ap)

        elif (station_type == StationType.FleetCarrier and fleetcarrier_transfer or
              station_type == StationType.SquadronCarrier and fleetcarrier_transfer):
            # Fleet Carrier in Transfer mode
            self.stats_log['Fleet Carrier'] = self.stats_log['Fleet Carrier'] + 1
            # --------- SELL ----------
            if len(sell_commodities) > 0:
                # Transfer to Fleet Carrier
                self.ap.internal_panel.transfer_to_fleetcarrier(ap)

            # --------- BUY ----------
            if len(buy_commodities) > 0:
                self.ap.internal_panel.transfer_from_fleetcarrier(ap, buy_commodities)

        else:
            # Regular Station or Fleet Carrier or Squadron Carrier in Buy/Sell mode
            self.ap_ckb('log', "Executing trade.")
            logger.debug(f"Execute Trade: On Regular Station")
            self.stats_log['Station'] = self.stats_log['Station'] + 1

            market_time_old = ""
            data = self.market_parser.get_market_data()
            if data is not None:
                market_time_old = self.market_parser.current_data['timestamp']

            # Go to the Station Commodities Market
            res = self.ap.stn_svcs_in_ship.goto_commodities_market()
            if not res:
                # The market may still have opened (only the OCR check failed). The Market.json wait below decides.
                self.ap_ckb('log', "Commodities market not confirmed by OCR (check Station Services calibration). "
                                   "Waiting for market data.")
                logger.warning("execute_trade: goto_commodities_market returned False")

            # # CONNECTED TO menu is different between stations and fleet carriers
            # if fleet_carrier:
            #     # Fleet Carrier COMMODITIES MARKET location top right, with:
            #     # uni cart, redemption, trit depot, shipyard, crew lounge
            #     ap.keys.send('UI_Right', repeat=2)
            #     ap.keys.send('UI_Select')  # Select Commodities
            #
            # elif outpost:
            #     # Outpost COMMODITIES MARKET location in middle column
            #     ap.keys.send('UI_Right')
            #     ap.keys.send('UI_Select')  # Select Commodities
            #
            # else:
            #     # Orbital station COMMODITIES MARKET location bottom left
            #     ap.keys.send('UI_Down')
            #     ap.keys.send('UI_Select')  # Select Commodities

            self.ap_ckb('log+vce', "Downloading commodities data from market.")

            # Wait for market to update
            market_time_new = ""
            data = self.market_parser.get_market_data()
            if data is not None:
                market_time_new = self.market_parser.current_data['timestamp']

            # The game writes Market.json when the market is opened. Wait for it, but not forever.
            wait_start = time.time()
            while market_time_new == market_time_old:
                if time.time() - wait_start > 30:
                    # No new data. Use the existing file only if it belongs to this station.
                    if data is not None and data.get('MarketID') == ap.jn.ship_state().get('MarketID'):
                        logger.info("execute_trade: no new market data after 30 s, using existing data of this station")
                        break
                    self.ap_ckb('log+vce', "No market data received. Skipping trade at this station.")
                    logger.warning("execute_trade: Market.json not updated within 30 s")
                    self.ap.ship_control.goto_cockpit_view()
                    return
                market_time_new = ""
                data = self.market_parser.get_market_data()
                if data is not None:
                    market_time_new = self.market_parser.current_data['timestamp']
                sleep(1)  # wait for new menu to finish rendering

            cargo_capacity = ap.jn.ship_state()['cargo_capacity']
            logger.info(f"Execute trade: Ship's max cargo capacity: {cargo_capacity}")

            # --------- SELL ----------
            if len(sell_commodities) > 0:
                # Select the SELL option
                self.ap.stn_svcs_in_ship.commodities_market.select_sell(ap.keys)

                for i, key in enumerate(sell_commodities):
                    # Check if we have any of the item to sell
                    self.cargo_parser.get_cargo_data()
                    cargo_parser_timestamp = self.cargo_parser.current_data['timestamp']

                    # Check if we want to sell ALL commodities
                    if key == "ALL":
                        for cargo_item in self.cargo_parser.get_items():
                            name = cargo_item.get('Name')
                            name_loc = cargo_item.get('Name_Localised', name)

                            # Sell all we have of the commodity
                            result, qty = self.ap.stn_svcs_in_ship.commodities_market.sell_commodity(ap.keys, name_loc, sell_commodities[key], self.cargo_parser)

                            # If we sold any goods, wait for cargo parser file to update with cargo available to sell
                            if qty > 0:
                                self.cargo_parser.wait_for_file_change(cargo_parser_timestamp, 5)

                                # Check if we have any of the item to sell
                                self.cargo_parser.get_cargo_data()
                                cargo_parser_timestamp = self.cargo_parser.current_data['timestamp']
                    else:
                        cargo_item = self.cargo_parser.get_item(key)
                        if cargo_item is None:
                            logger.info(f"Unable to sell {key}. None in cargo hold.")
                            continue

                        # Sell the commodity
                        result, qty = self.ap.stn_svcs_in_ship.commodities_market.sell_commodity(ap.keys, key, sell_commodities[key], self.cargo_parser)

                        # Update counts if necessary
                        if qty > 0 and self.waypoints[dest_key]['UpdateCommodityCount']:
                            sell_commodities[key] = sell_commodities[key] - qty

                # Save changes
                self.write_waypoints(data=None, filename='./waypoints/' + Path(self.filename).name)

            sleep(1)

            # --------- BUY ----------
            # Supply of the planned commodity gone or prices changed: fill the hold with the best ones now
            try:
                if adapt_buy_list(self, ap, dest_key):
                    buy_commodities = self.waypoints[dest_key]['BuyCommodities']
            except Exception as e:
                if type(e).__name__ in ('EDAP_Interrupt', 'EDAP_GameNotRunning'):
                    raise
                logger.warning(f"trade adapt failed: {e}")
            # --------- BUY ----------
            if len(buy_commodities) > 0 or len(global_buy_commodities) > 0:
                # Select the BUY option
                self.ap.stn_svcs_in_ship.commodities_market.select_buy(ap.keys)

                # Go through buy commodities list
                for i, key in enumerate(buy_commodities):
                    # Check if we want to buy ALL commodities. Makes sense for buying from FCs.
                    if key == "ALL":
                        # Go through all buyable items
                        buyable_items = self.market_parser.get_buyable_items()
                        if buyable_items is not None:
                            for ii, value in enumerate(buyable_items):
                                name = value['Name_Localised']

                                # Buy the commodity
                                curr_cargo_qty = int(ap.status.get_cleaned_data()['Cargo'])
                                cargo_timestamp = ap.status.current_data['timestamp']

                                free_cargo = cargo_capacity - curr_cargo_qty
                                logger.info(f"Execute trade: Free cargo space: {free_cargo}")

                                if free_cargo == 0:
                                    logger.info(f"Execute trade: No space for additional cargo")
                                    break

                                qty_to_buy = buy_commodities[key]
                                logger.info(f"Execute trade: Shopping list requests {qty_to_buy} units of {key}")

                                # Attempt to buy the commodity
                                qty = self._buy_verified(ap, name, qty_to_buy, free_cargo)
                                logger.info(f"Execute trade: Bought {qty} units of {name}")

                                # If we bought any goods, wait for status file to update with
                                # new cargo count for next commodity
                                if qty > 0:
                                    ap.status.wait_for_file_change(cargo_timestamp, 5)

                    else:
                        # Buy the commodity
                        curr_cargo_qty = int(ap.status.get_cleaned_data()['Cargo'])
                        cargo_timestamp = ap.status.current_data['timestamp']

                        free_cargo = cargo_capacity - curr_cargo_qty
                        logger.info(f"Execute trade: Free cargo space: {free_cargo}")

                        if free_cargo == 0:
                            logger.info(f"Execute trade: No space for additional cargo")
                            break

                        qty_to_buy = buy_commodities[key]
                        logger.info(f"Execute trade: Shopping list requests {qty_to_buy} units of {key}")

                        # Attempt to buy the commodity
                        qty = self._buy_verified(ap, key, qty_to_buy, free_cargo)
                        logger.info(f"Execute trade: Bought {qty} units of {key}")

                        # If we bought any goods, wait for status file to update with
                        # new cargo count for next commodity
                        if qty > 0:
                            ap.status.wait_for_file_change(cargo_timestamp, 5)

                        # Update counts if necessary
                        if qty > 0 and self.waypoints[dest_key]['UpdateCommodityCount']:
                            buy_commodities[key] = qty_to_buy - qty

                # Go through global buy commodities list
                for i, key in enumerate(global_buy_commodities):
                    curr_cargo_qty = int(ap.status.get_cleaned_data()['Cargo'])
                    cargo_timestamp = ap.status.current_data['timestamp']

                    free_cargo = cargo_capacity - curr_cargo_qty
                    logger.info(f"Execute trade: Free cargo space: {free_cargo}")

                    if free_cargo == 0:
                        logger.info(f"Execute trade: No space for additional cargo")
                        break

                    qty_to_buy = global_buy_commodities[key]
                    logger.info(f"Execute trade: Global shopping list requests {qty_to_buy} units of {key}")

                    # Attempt to buy the commodity
                    qty = self._buy_verified(ap, key, qty_to_buy, free_cargo)
                    logger.info(f"Execute trade: Bought {qty} units of {key}")

                    # If we bought any goods, wait for status file to update with
                    # new cargo count for next commodity
                    if qty > 0:
                        ap.status.wait_for_file_change(cargo_timestamp, 5)

                    # Update counts if necessary
                    if qty > 0 and self.waypoints['GlobalShoppingList']['UpdateCommodityCount']:
                        global_buy_commodities[key] = qty_to_buy - qty

                # Save changes
                self.write_waypoints(data=None, filename='./waypoints/' + Path(self.filename).name)

            sleep(1.5)  # give time to popdown
            # Go to ship view
            ap.ship_control.goto_cockpit_view()

    def waypoint_assist(self, keys, scr_reg):
        """ Processes the waypoints, performing jumps and sc assist if going to a station
        also can then perform trades if specific in the waypoints file.
        """
        self.aborted = False
        self.abort_reason = ''
        if len(self.waypoints) == 0:
            self.ap_ckb('log+vce', "No Waypoint file loaded. Exiting Waypoint Assist.")
            return

        self.step = 0  # start at first waypoint
        self.ap._launched_early = False
        self.ap_ckb('log', "Waypoint file: " + str(Path(self.filename).name))
        self.reset_stats()

        # Already docked at one of the waypoint stations? Then continue from there (do its trade first)
        # instead of undocking and flying to the first open waypoint.
        self._start_at_docked_station()

        # Loop until complete, or error. The reason of an abort is kept for the fail-safe (EDRecovery).
        _abort = False
        self.aborted = False
        self.abort_reason = ''
        never_stop = bool(self.ap.config.get('WaypointNeverStop', True))
        station_fail_cnt = 0  # failed attempts in a row to reach the current station
        max_station_fails = max(1, int(self.ap.config.get('WaypointStationRetries', 3)))
        while not _abort:
            # Game still running? (connection error dialog, main menu) -> raises and stops
            if self.ap.config.get('GameConnectionCheck', True) and not self.ap.game_is_playable():
                self.ap.stop_game_not_running("main menu, game closed or not in the ship")

            # Current location
            cur_star_system = self.ap.jn.ship_state()['cur_star_system'].upper()
            cur_station = self.ap.jn.ship_state()['cur_station'].upper()
            cur_station_type = self.ap.jn.ship_state()['exp_station_type']

            # Current in game destination
            status = self.ap.status.get_cleaned_data()
            destination_system = status['Destination_System']  # The system ID
            destination_body = status['Destination_Body']  # The body number (0 for prim star)
            destination_name = status['Destination_Name']  # The system/body/station/settlement name

            # ====================================
            # Get next Waypoint
            # ====================================

            old_step = self.step
            # Loop through waypoints to find next waypoint
            while True:
                skip_waypoint = False
                # Get the waypoint details
                dest_key, next_waypoint = self.get_waypoint()

                # End loop if we are not skipping this waypoint, or we are at the end
                if (not skip_waypoint) or (dest_key is None):
                    break

            if dest_key is None:
                self.ap_ckb('log+vce', "Waypoint list has been completed.")
                break

            # Is this a new waypoint?
            if self.step != old_step:
                new_waypoint = True
            else:
                new_waypoint = False

            # Flag if we are using bookmarks
            gal_bookmark = next_waypoint.get('GalaxyBookmarkNumber', -1) > 0
            sys_bookmark = next_waypoint.get('SystemBookmarkNumber', -1) > 0
            gal_bookmark_type = next_waypoint.get('GalaxyBookmarkType', '')
            gal_bookmark_num = next_waypoint.get('GalaxyBookmarkNumber', 0)
            sys_bookmark_type = next_waypoint.get('SystemBookmarkType', '')
            sys_bookmark_num = next_waypoint.get('SystemBookmarkNumber', 0)

            next_wp_system = next_waypoint.get('SystemName', '').upper()
            next_wp_station = next_waypoint.get('StationName', '').upper()

            if new_waypoint:
                self.ap_ckb('log+vce', f"Next Waypoint: {next_wp_station} in {next_wp_system}")

            # ====================================
            # Target and travel to a System
            # ====================================

            # Check current system and go to next system if different and not blank
            if next_wp_system == "" or (cur_star_system == next_wp_system):
                if new_waypoint:
                    self.ap_ckb('log+vce', f"Already in target System.")
            else:
                # Check if the current nav route is to the target system
                last_nav_route_sys = self.ap.nav_route.get_last_system().upper()
                # Check we have a route and that we have a destination to a star (body 0).
                # We can have one without the other.
                if ((last_nav_route_sys == next_wp_system) and
                        (destination_body == 0 and destination_name != "") and not self._replot_after_trade):
                    # No need to target system
                    self.ap_ckb('log+vce', f"System already targeted.")
                else:
                    # Docked: start the launch first and plot the route while the docking computer flies out
                    # (the galaxy map can be used during the auto launch, saves ~25 s per station).
                    if self.ap.can_launch_early():
                        self.ap.start_launch()
                    self.ap_ckb('log+vce', f"Targeting system {next_wp_system}.")
                    # Select destination in galaxy map based on name
                    # After a trade the ship is heavier/lighter: plot the route again (an old route may contain
                    # jumps that are too long now -> 'FSD failed to charge').
                    res = self.ap.galaxy_map.set_gal_map_destination_text(self.ap, next_wp_system,
                                                                          self.ap.jn.ship_state,
                                                                          force=self._replot_after_trade)
                    self._replot_after_trade = False
                    if res:
                        self.ap_ckb('log', f"System has been targeted.")
                    else:
                        self.ap_ckb('log+vce', f"Unable to target {next_wp_system} in Galaxy Map.")
                        self.abort_reason = f"could not target {next_wp_system} in the Galaxy Map"
                        _abort = True
                        break

                # Enough fuel for the plotted route? (ships without fuel scoop)
                if not self._fuel_ok_for_route():
                    fuel_pct = float(self.ap.jn.ship_state().get('fuel_percent') or 0)
                    if never_stop and fuel_pct >= 90:
                        # Full tank and still not enough: the route needs a fuel stop on the way. Fly; below
                        # 'RefuelStopPercent' the jumps stop and the fail-safe flies to the nearest station.
                        self.ap_ckb('log+vce', "Tank is full, flying anyway. A fuel stop is made on the way if needed.")
                    else:
                        self.abort_reason = "low_fuel"
                        _abort = True
                        break

                # Select next target system
                # TODO should this be in before every jump?
                keys.send('TargetNextRouteSystem')

                # Jump to the destination system
                self.ap_ckb('log+vce', f"Jumping to {next_wp_system}.")
                res = self.ap.jump_to_system(scr_reg)
                if not res:
                    self.ap_ckb('log', f"Failed to jump to {next_wp_system}.")
                    self.abort_reason = "low_fuel" if getattr(self.ap, '_low_fuel_abort', False) \
                        else f"jump to {next_wp_system} failed"
                    _abort = True
                    break

                continue

            # ====================================
            # Target and travel to a local Station
            # ====================================

            # If we are in the right system, check if we are already docked.
            docked_at_stn = False
            is_docked = self.ap.status.get_flag(FlagsDocked)
            if is_docked:
                # Check if we are at the correct station. Note that for FCs, the station name
                # reported by the Journal is only the ship identifier (ABC-123) and not the carrier name.
                # So we need to check if the ID (ABC-123) is at the end of the target ('Fleety McFleet ABC-123').
                self.ap_ckb('log', f"Docked at {cur_station}.")
                self.ap_ckb('log', f"Checking station name against target station: {next_wp_station}.")
                if cur_station_type == StationType.FleetCarrier:
                    if next_wp_station.endswith(cur_station):
                        docked_at_stn = True
                    else:
                        self.ap_ckb('log', f"FleetCarrier name: {next_wp_station} does not end with: {cur_station}.")

                elif cur_station_type == StationType.SquadronCarrier:
                    if next_wp_station.endswith(cur_station):
                        docked_at_stn = True
                    else:
                        self.ap_ckb('log', f"SquadronCarrier name: {next_wp_station} does not end with: {cur_station}.")

                elif 'System Colonisation Ship'.upper() in next_wp_station:
                    if cur_station_type == StationType.ColonisationShip:
                        docked_at_stn = True
                    else:
                        self.ap_ckb('log', f"Current station is not a Colonisation Ship.")

                # elif next_wp_station.startswith('Orbital Construction Site'.upper()):
                #     if (cur_station_type == 'SurfaceStation'.upper() and
                #             'Orbital Construction Site'.upper() in cur_station.upper()):
                #         docked_at_stn = True
                elif cur_station == next_wp_station:
                    docked_at_stn = True

                if not docked_at_stn:
                    self.ap_ckb('log', f"We are not docked at the target station.")

            # Check current station and go to it if different
            if docked_at_stn:
                if new_waypoint:
                    self.ap_ckb('log+vce', f"Already at target Station: {next_wp_station}.")
            else:
                # Check if we need to travel to a station, else we are done.
                # This may be by 1) System bookmark, 2) Galaxy bookmark or 3) by Station Name text
                if sys_bookmark or gal_bookmark or next_wp_station != "":
                    # If waypoint file has a Station Name associated then attempt targeting it
                    self.ap_ckb('log+vce', f"Targeting Station: {next_wp_station}")

                    if gal_bookmark:
                        # Set destination via gal bookmark, not system bookmark
                        res = self.ap.galaxy_map.set_gal_map_dest_bookmark(self.ap, gal_bookmark_type, gal_bookmark_num)
                        if not res:
                            self.ap_ckb('log+vce', f"Unable to set Galaxy Map bookmark.")
                            self.abort_reason = "galaxy map bookmark failed"
                            _abort = True
                            break

                    elif sys_bookmark and sys_bookmark_type != 'Nav Panel OCR':
                        # Set destination via system bookmark
                        res = self.ap.system_map.set_sys_map_dest_bookmark(self.ap, sys_bookmark_type, sys_bookmark_num)
                        if not res:
                            self.ap_ckb('log+vce', f"Unable to set System Map bookmark.")
                            self.abort_reason = "system map bookmark failed"
                            _abort = True
                            break

                    elif next_wp_station != "":
                        # A system name is defined and 'Nav Panel OCR' is selected, or both gal bookmark and system
                        # bookmark are empty, so we will default to using OCR.
                        if sys_bookmark_type != 'Nav Panel OCR':
                            # Log fall back to OCR message.
                            self.ap.ap_ckb('log', f"No bookmark number configured for '{next_wp_station}'; defaulting "
                                                  f"to Nav Panel OCR to set station by name.")
                        # Locate the station by name in the in-game Nav Panel (left HUD) and lock onto it.
                        # With the in-game Supercruise Assist this is not needed: activating the SCA selects the
                        # station in the same Nav Panel list (it was searched twice, ~13 s each).
                        if self.ap.jn.ship_state()['has_supercruise_assist']:
                            logger.debug(f"Station '{next_wp_station}' is selected when the SC Assist is activated.")
                        else:
                            res = self.ap.nav_panel.lock_destination(next_wp_station)
                            if not res:
                                self.ap_ckb('log+vce', f"Unable to set Nav Panel OCR bookmark.")
                                self.abort_reason = f"{next_wp_station} not found in the Nav Panel"
                                _abort = True
                                break

                    else:
                        # No bookmark and no station name -- nothing to target.
                        self.ap_ckb('log+vce', "No bookmark or station name defined for this waypoint.")
                        self.abort_reason = "config: no station for this waypoint"
                        _abort = True
                        break

                    # Jump to the station by name
                    res = self.ap.supercruise_to_station(scr_reg, next_wp_station)
                    sleep(1)  # Allow status log to update
                    if res:
                        station_fail_cnt = 0
                    else:
                        # Before, a failure here started the next attempt at once, forever (log 2026-10-20:
                        # 697 attempts in 2 hours while the game showed a connection error).
                        station_fail_cnt += 1
                        if station_fail_cnt >= max_station_fails:
                            self.ap_ckb('log+vce', f"Could not reach {next_wp_station} after {station_fail_cnt} "
                                                   f"attempts.")
                            self.abort_reason = f"could not reach {next_wp_station}"
                            _abort = True
                            break
                        delay = float(self.ap.config.get('WaypointRestartDelay', 10))
                        self.ap_ckb('log+vce', f"Could not reach {next_wp_station}, attempt {station_fail_cnt} of "
                                               f"{max_station_fails}. Trying again in {delay:.0f} seconds.")
                        sleep(delay)
                    continue
                else:
                    self.ap_ckb('log+vce', f"Arrived at target System: {next_wp_system}")

            # ====================================
            # Dock and Trade at Station
            # ====================================

            # Are we at the correct station to trade?
            if docked_at_stn:  # and (next_wp_station != "" or sys_bookmark):
                # Docked - let do trade
                self.ap_ckb('log+vce', f"Execute trade at Station: {next_wp_station}")
                self.execute_trade(self.ap, dest_key)
                self._replot_after_trade = True  # cargo mass changed -> jump range changed
                if getattr(self, '_trade_failed', False):
                    # Do not fly the whole route with an empty hold
                    self.ap_ckb('log+vce', "Trade failed (purchase not confirmed)." +
                                ("" if never_stop else " Stopping Waypoint Assist here, still docked. "
                                                       "Please check the market."))
                    self.abort_reason = "trade failed"
                    _abort = True
                    break

            # Mark this waypoint as completed
            self.mark_waypoint_complete(dest_key)
            self.progress_cnt = getattr(self, 'progress_cnt', 0) + 1  # the fail-safe resets its stages on progress
            self.ap_ckb('log+vce', f"Current Waypoint complete.")

        # Done with waypoints
        if not _abort:
            self.ap_ckb('log+vce',
                           "Waypoint Route Complete, total distance jumped: " + str(self.ap.total_dist_jumped) + "LY")
            self.ap.update_ap_status("Idle")
        else:
            self.aborted = True
            if not self.abort_reason:
                self.abort_reason = "aborted"
            self.ap_ckb('log+vce', f"Waypoint Route was aborted ({self.abort_reason}).")
            self.ap.update_ap_status("Idle")

    def _fuel_ok_for_route(self) -> bool:
        """ Checks the fuel for the plotted route (NavRoute.json) with the fuel use learned from the recent jumps
        in the journal. Only for ships without fuel scoop (with a scoop EDAP refuels at the stars).
        Returns False if the fuel is not enough to reach the destination (-> stop, rather than to be stranded). """
        ap = self.ap
        if not ap.config.get('FuelRouteCheck', True):
            return True
        state = ap.jn.ship_state()
        if state.get('has_fuel_scoop'):
            return True
        cap = state.get('fuel_capacity')
        try:
            status = ap.status.get_cleaned_data()
            # Status.json is up to date after refuelling at a station (the journal 'RefuelAll' has no fuel level)
            fuel = status.get('FuelMain') or state.get('fuel_level')
            cargo = int(status.get('Cargo') or 0)
            if not fuel or not cap:
                return True
            est = estimate_route_fuel(os.path.dirname(ap.jn.current_log), ap.nav_route.get_nav_route_data(),
                                      cargo, state.get('cargo_capacity'), state.get('cur_star_system'))
        except Exception as e:
            logger.warning(f"Fuel check failed: {e}")
            return True
        if est is None:
            self.ap_ckb('log', "Fuel check: not enough jumps with this ship and cargo in the journal yet, skipped.")
            return True

        reserve = cap * ap.config['FuelThreasholdAbortAP'] / 100.0
        left = fuel - est['need']
        left_min = fuel - est['need_max']
        self.ap_ckb('log', f"Fuel check: {est['jumps']} jumps need about {est['need']:.1f} t "
                           f"(max. {est['need_max']:.1f} t), tank {fuel:.1f} of {cap:.0f} t, "
                           f"expected on arrival {left:.1f} t ({100 * left / cap:.0f}%).")
        if left < 1.0:
            self.ap_ckb('log+vce', f"Not enough fuel for this route: need about {est['need']:.1f} t, "
                                   f"tank has {fuel:.1f} t. Stopping Waypoint Assist. Refuel or choose a shorter "
                                   f"route (e.g. with a fuel stop as waypoint).")
            return False
        if left_min < reserve:
            self.ap_ckb('log+vce', f"Warning: fuel on arrival will be low (about {100 * left / cap:.0f}%, "
                                   f"worst case {100 * max(0.0, left_min) / cap:.0f}%).")
        return True

    def reset_stats(self):
        # Clear stats
        self.stats_log['Colonisation'] = 0
        self.stats_log['Construction'] = 0
        self.stats_log['Fleet Carrier'] = 0
        self.stats_log['Station'] = 0

    def sell_to_colonisation_ship(self, ap):
        self.ap.stn_svcs_in_ship.sell_to_colonisation_ship(self.ap)


def main():
    from ED_AP import EDAutopilot

    ed_ap = EDAutopilot(cb=None)
    wp = EDWayPoint(ed_ap, None, True)  # False = Horizons
    wp.step = 0  # start at first waypoint
    keys = EDKeys(cb=None)
    keys.activate_window = True
    wp.ap.stn_svcs_in_ship.commodities_market.select_sell(keys)
    wp.ap.stn_svcs_in_ship.commodities_market.sell_commodity(keys, "Aluminium", 1, wp.cargo_parser)
    wp.ap.stn_svcs_in_ship.commodities_market.sell_commodity(keys, "Beryllium", 1, wp.cargo_parser)
    wp.ap.stn_svcs_in_ship.commodities_market.sell_commodity(keys, "Cobalt", 1, wp.cargo_parser)
    # wp.ap.stn_svcs_in_ship.buy_commodity(keys, "Titanium", 5, 200)

    # dest = 'Enayex'
    # print(dest)

    # print("In waypoint_assist, at:"+str(dest))

    # already in doc config, test the trade
    # wp.execute_trade(keys, dest)

    # Set the Route for the waypoint^#
    # dest = wp.waypoint_next(ap=None)

    # while dest != "":

    #  print("Doing: "+str(dest))
    #  print(wp.waypoints[dest])

    # wp.set_station_target(None, dest)

    # Mark this waypoint as complated
    # wp.mark_waypoint_complete(dest)

    # set target to next waypoint and loop
    # dest = wp.waypoint_next(ap=None)


if __name__ == "__main__":
    main()
