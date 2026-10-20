# import queue
# import sys
# import os
# import threading
# import kthread
# from datetime import datetime
# from time import sleep
# import cv2
# import json
# from pathlib import Path
import queue
import threading
import subprocess
from typing import TypedDict

import keyboard
import webbrowser
# import requests


# from PIL import Image, ImageGrab, ImageTk
import tkinter as tk
from tkinter import filedialog as fd
# from tkinter import messagebox
from tkinter import ttk
import sv_ttk
import pywinstyles
import sys  # Do not delete - prevents a 'super' error from tktoolip.
from tktooltip import ToolTip  # In requirements.txt as 'tkinter-tooltip'.

from EDAPCalibration import Calibration
from EDAPColonizeEditor import ColonizeEditorTab
# from OCR import RegionCalibration
# from Voice import *
# from MousePt import MousePoint

# from Image_Templates import *
# from Screen import *
# from Screen_Regions import *
# from EDKeys import *
# from EDJournal import *
from ED_AP import *
from EDAPWaypointEditor import WaypointEditorTab
from EDAPSettingsTab import SettingsTab
import json
import os
import time
from datetime import datetime

from EDlogger import logger
from Screen import set_focus_elite_window
from time import sleep
from RPYLineEditor import line_editor

"""
File:EDAPGui.py

Description:
User interface for controlling the ED Autopilot

Note:
Ideas taken from:  https://github.com/skai2/EDAutopilot

 HotKeys:
    Home - Start FSD Assist
    INS  - Start SC Assist
    PG UP - Start Robigo Assist
    End - Terminate any ongoing assist (FSD, SC, AFK)

Author: sumzer0@yahoo.com
"""

# ---------------------------------------------------------------------------
# must be updated with a new release so that the update check works properly!
# contains the names of the release.
EDAP_VERSION = "V1.9.3"
# depending on how release versions are best marked you could also change it to the release tag, see function check_update.
# ---------------------------------------------------------------------------

FORM_TYPE_CHECKBOX = 0
FORM_TYPE_SPINBOX = 1
FORM_TYPE_ENTRY = 2


def str_to_float(input_str: str) -> float:
    try:
        return float(input_str)
    except ValueError:
        return 0.0  # Assign a default value on error


class SubRegion(TypedDict):
    """ """
    rect: list[float]
    text: str


class Objects(TypedDict):
    """ """
    width: float
    height: float
    text: str


class MyRegion(TypedDict):
    """ """
    rect: list[float]
    text: str
    readonly: bool
    regions: dict[str, SubRegion]
    objects: dict[str, Objects]


class APGui:

    def __init__(self, root):
        self.statusbar = None
        self.root = root
        root.title("EDAutopilot " + EDAP_VERSION)
        # root.overrideredirect(True)
        # root.geometry("400x550")
        # root.configure(bg="blue")
        root.protocol("WM_DELETE_WINDOW", self.close_window)
        root.resizable(False, False)

        self.tooltips = {
            'FSD Route Assist': "Will execute your route. \nAt each jump the sequence will perform some fuel scooping.",
            'Supercruise Assist': "Will keep your ship pointed to target, \nyou target can only be a station for the autodocking to work.",
            'Waypoint Assist': "When selected, will prompt for the waypoint file. \nThe waypoint file contains System names that \nwill be entered into Galaxy Map and route plotted.",
            'Robigo Assist': "Robigo passenger mission loop (Robigo Mines / Sirius Atmospherics).",
            'DSS Assist': "When selected, will perform DSS scans while you are traveling between stars.",
            'Single Waypoint Assist': "Fly to the system and/or station entered above (test of a single waypoint).",
            'ELW Scanner': "Will perform FSS scans while FSD Assist is traveling between stars. \nIf the FSS shows a signal in the region of Earth, \nWater or Ammonia type worlds, it will announce that discovery.",
            'AFK Combat Assist': "Used with a AFK Combat ship in a Rez Zone.",
            'RollRate': "Roll rate your ship has in deg/sec. Higher the number the more maneuverable the ship.",
            'PitchRate': "Pitch (up/down) rate your ship has in deg/sec. Higher the number the more maneuverable the ship.",
            'YawRate': "Yaw rate (rudder) your ship has in deg/sec. Higher the number the more maneuverable the ship.",
            'SunPitchUp+Time': "This field are for ship that tend to overheat. \nProviding 1-2 more seconds of Pitch up when avoiding the Sun \nwill overcome this problem.",
            'Sun Bright Threshold': "The low level for brightness detection, \nrange 0-255, want to mask out darker items",
            'Nav Align Tries': "How many attempts the ap should make at alignment.",
            'Jump Tries': "How many attempts the ap should make to jump.",
            'Docking Retries': "How many attempts to make to dock.",
            'Wait For Autodock': "After docking granted, \nwait this amount of time for us to get docked with autodocking",
            'Start FSD': "Button to start FSD route assist.",
            'Start SC': "Button to start Supercruise assist.",
            'Start Robigo': "Button to start Robigo assist.",
            'Stop All': "Button to stop all assists.",
            'Refuel Threshold': "If fuel level get below this level, \nit will attempt refuel.",
            'Scoop Timeout': "Number of second to wait for full tank, \nmight mean we are not scooping well or got a small scooper",
            'Fuel Threshold Abort': "Level at which AP will terminate, \nbecause we are not scooping well.",
            'X Offset': "Offset left the screen to start place overlay text.",
            'Y Offset': "Offset down the screen to start place overlay text.",
            'Font Size': "Font size of the overlay.",
            'Calibrate': "Will iterate through a set of scaling values \ngetting the best match for your system. \nSee HOWTO-Calibrate.md",
            'Cap Mouse XY': "This will provide the StationCoord value of the Station in the SystemMap. \nSelecting this button and then clicking on the Station in the SystemMap \nwill return the x,y value that can be pasted in the waypoints file",
            'Debug Overlay': "Enables debug data to be displayed over the \nElite Dangerous screen while playing the game.",
            'Debug OCR': "Enables OCR debug output to be stored in the 'ocr_output' folder.",
            'Debug Images': "Enables debug images to be stored in the 'debug_output' folder.",
            'Modifier Key Delay': "Delay for key modifiers to ensure modifier is detected before/after the key.",
            'Default Hold Time': "Default hold time for a key press.",
            'Repeat Key Delay': "Delay between key press repeats.",
        }

        self.gui_loaded = False
        self.log_buffer = queue.Queue()
        # Callbacks from worker threads (engine, SCO monitor, key sender, ...) must not touch Tk widgets:
        # Tkinter is not thread safe, concurrent widget calls from several threads end the process without a
        # Python traceback. They are queued here and processed in the Tk main thread (see _process_cb_queue).
        self._cb_queue = queue.Queue()
        self._main_thread = threading.main_thread()
        self.root.after(100, self._process_cb_queue)
        self.callback('log', f'Starting ED Autopilot {EDAP_VERSION}.')

        self.ed_ap = EDAutopilot(cb=self.callback)
        self.ed_ap.robigo.set_single_loop(self.ed_ap.config['Robigo_Single_Loop'])
        # self.calibrator = RegionCalibration(root, self.ed_ap, cb=self.callback)
        self.calibration = None

        self.ocr_calibration_data = {}

        self.mouse = MousePoint()

        self.checkboxvar = {}
        self.radiobuttonvar = {}
        self.entries = {}
        self.lab_ck = {}
        self.single_waypoint_system = tk.StringVar()
        self.single_waypoint_station = tk.StringVar()
        self.throttle_var = tk.StringVar()
        self.throttle_combo = None
        self.throttle_keys = []
        self._global_shopping_list_tab = None
        self.waypoint_editor_tab = None
        self.colonize_tab = None
        self._nb = None
        self._active_mode = None  # name of the running assist (for the status panel)
        self._session_start = None  # time the running assist was started
        self._status_text = "Idle"
        self._jump_text = ""
        self._settings_dirty = False
        self.settings_tab = None
        self.btn_save = None
        self.autoscroll_var = None
        self.live = {}

        self.FSD_A_running = False
        self.SC_A_running = False
        self.WP_A_running = False
        self.RO_A_running = False
        self.DSS_A_running = False
        self.SWP_A_running = False
        self.AFK_A_running = False

        self.cv_view = False

        self.msgList = self.gui_gen(root)

        self.checkboxvar['Debug Overlay'].set(self.ed_ap.config['DebugOverlay'])
        self.checkboxvar['Debug OCR'].set(self.ed_ap.config['DebugOCR'])
        self.checkboxvar['Debug Images'].set(self.ed_ap.config['DebugImages'])

        self.entries['ship']['SunPitchUp+Time'].delete(0, tk.END)
        self.entries['ship']['SunPitchUp+Time'].insert(0, float(self.ed_ap.sunpitchuptime))

        if self.ed_ap.config['LogDEBUG']:
            self.radiobuttonvar['debug_mode'].set("Debug")
        elif self.ed_ap.config['LogINFO']:
            self.radiobuttonvar['debug_mode'].set("Info")
        else:
            self.radiobuttonvar['debug_mode'].set("Error")

        # Hotkeys
        self.setup_hotkeys()

        # check for updates
        self.check_updates()

        sleep(0.25)  # Added because the custom tkinter takes longer to load? Without, you occasionally get errors
        # that the main thread is not in main loop.
        self.ed_ap.gui_loaded = True
        self.gui_loaded = True
        # Send a log entry which will flush out the buffer.
        self.callback('log', 'ED Autopilot loaded successfully.')

        # Live status panel on the main tab
        self.root.after(1000, self._update_live_panel)

    def setup_hotkeys(self):
        """ Enable or disable hotkeys.
        Global trap for these keys, the 'end' key will stop any current AP action the 'home' key will start the
        FSD Assist. May want another to start SC Assist.
        """
        # Remove all the hotkeys. Adding a dummy hotkey will eliminate an error if none had been configured.
        keyboard.add_hotkey(' ', print)
        keyboard.remove_all_hotkeys()

        if self.ed_ap.config['HotkeysEnable']:
            # Add the desired hotkeys. An invalid key name must not break the other hotkeys.
            for cfg_key, msg in (('HotKey_StopAllAssists', 'stop_all_assists'), ('HotKey_StartFSD', 'fsd_start'),
                                 ('HotKey_StartSC', 'sc_start'), ('HotKey_StartRobigo', 'robigo_start')):
                hotkey = str(self.ed_ap.config.get(cfg_key, '')).strip()
                if not hotkey:
                    continue
                try:
                    keyboard.add_hotkey(hotkey, self.callback, args=(msg, None))
                except Exception as e:
                    self.log_msg(f"Hotkey '{hotkey}' ({cfg_key}) is not valid: {e}")

            # TODO - Enable these to allow pips to be controlled by EDAP when using the defined keys (tbd).
            # keyboard.add_hotkey('up', self.callback, args=('up', None))
            # keyboard.add_hotkey('down', self.callback, args=('down', None))
            # keyboard.add_hotkey('left', self.callback, args=('left', None))
            # keyboard.add_hotkey('right', self.callback, args=('right', None))

    # callback from the EDAP, to configure GUI items
    def callback(self, msg, body=None):
        """ Thread safe entry point for messages from the autopilot. """
        if threading.current_thread() is self._main_thread:
            self._callback_main(msg, body)
        elif msg in ('log', 'log+vce'):
            # Write the log file and speak right away in the calling thread (correct timestamps, nothing lost if
            # the GUI is busy), only the list box update is done in the Tk main thread.
            logger.info(body)
            if msg == 'log+vce':
                self.ed_ap.vce.say(body)
            self._cb_queue.put(('_gui_log', body))
        else:
            self._cb_queue.put((msg, body))

    def _process_cb_queue(self):
        """ Runs in the Tk main thread: handles all queued callbacks. """
        try:
            for _ in range(200):  # at most 200 per tick, keep the GUI responsive
                try:
                    msg, body = self._cb_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._callback_main(msg, body)
                except Exception as e:
                    logger.error(f"GUI callback '{msg}' failed: {e}")
        finally:
            self.root.after(100, self._process_cb_queue)

    def _callback_main(self, msg, body=None):
        if msg == '_gui_log':
            self.log_msg(body, write_log=False)
        elif msg == 'log':
            self.log_msg(body)
        elif msg == 'log+vce':
            self.log_msg(body)
            self.ed_ap.vce.say(body)
        elif msg == 'statusline':
            self.update_statusline(body)
        elif msg == 'fsd_stop':
            logger.debug("Detected 'fsd_stop' callback msg")
            self.checkboxvar['FSD Route Assist'].set(0)
            self.check_cb('FSD Route Assist')
        elif msg == 'fsd_start':
            self.checkboxvar['FSD Route Assist'].set(1)
            self.check_cb('FSD Route Assist')
        elif msg == 'sc_stop':
            logger.debug("Detected 'sc_stop' callback msg")
            self.checkboxvar['Supercruise Assist'].set(0)
            self.check_cb('Supercruise Assist')
        elif msg == 'sc_start':
            self.checkboxvar['Supercruise Assist'].set(1)
            self.check_cb('Supercruise Assist')
        elif msg == 'waypoint_stop':
            logger.debug("Detected 'waypoint_stop' callback msg")
            self.checkboxvar['Waypoint Assist'].set(0)
            self.check_cb('Waypoint Assist')
        elif msg == 'waypoint_start':
            self.checkboxvar['Waypoint Assist'].set(1)
            self.check_cb('Waypoint Assist')
        elif msg == 'robigo_stop':
            logger.debug("Detected 'robigo_stop' callback msg")
            self.checkboxvar['Robigo Assist'].set(0)
            self.check_cb('Robigo Assist')
        elif msg == 'robigo_start':
            self.checkboxvar['Robigo Assist'].set(1)
            self.check_cb('Robigo Assist')
        elif msg == 'afk_stop':
            logger.debug("Detected 'afk_stop' callback msg")
            self.checkboxvar['AFK Combat Assist'].set(0)
            self.check_cb('AFK Combat Assist')
        elif msg == 'dss_start':
            logger.debug("Detected 'dss_start' callback msg")
            self.checkboxvar['DSS Assist'].set(1)
            self.check_cb('DSS Assist')
        elif msg == 'dss_stop':
            logger.debug("Detected 'dss_stop' callback msg")
            self.checkboxvar['DSS Assist'].set(0)
            self.check_cb('DSS Assist')
        elif msg == 'single_waypoint_stop':
            logger.debug("Detected 'single_waypoint_stop' callback msg")
            self.checkboxvar['Single Waypoint Assist'].set(0)
            self.check_cb('Single Waypoint Assist')

        elif msg == 'stop_all_assists':
            logger.debug("Detected 'stop_all_assists' callback msg")

            self.checkboxvar['FSD Route Assist'].set(0)
            self.check_cb('FSD Route Assist')

            self.checkboxvar['Supercruise Assist'].set(0)
            self.check_cb('Supercruise Assist')

            self.checkboxvar['Waypoint Assist'].set(0)
            self.check_cb('Waypoint Assist')

            self.checkboxvar['Robigo Assist'].set(0)
            self.check_cb('Robigo Assist')

            self.checkboxvar['AFK Combat Assist'].set(0)
            self.check_cb('AFK Combat Assist')

            self.checkboxvar['DSS Assist'].set(0)
            self.check_cb('DSS Assist')

            self.checkboxvar['Single Waypoint Assist'].set(0)
            self.check_cb('Single Waypoint Assist')

        elif msg == 'jumpcount':
            self.update_jumpcount(body)
        elif msg == 'update_ship_cfg':
            self.root.after(0, self.update_ship_cfg)
        elif msg == 'load_waypoints':
            # TODO - Enable this at some point to auto load the previous waypoints on startup. Not called at the moment.
            self.waypoint_editor_tab.editor_load_waypoint_file(body)
        elif msg == 'up':
            # TODO - Enable these to allow pips to be controlled by EDAP when using the defined keys (tbd). Not called at the moment.
            print('up')
            if ((self.ed_ap.status.get_flag(FlagsInMainShip) or self.ed_ap.status.get_flag(FlagsInFighter))
                    and self.ed_ap.status.get_gui_focus() == GuiFocusNoFocus):
                self.ed_ap.keys.send('ResetPowerDistribution')
                self.ed_ap.keys.send('IncreaseEnginesPower', repeat=3)
        elif msg == 'down':
            print('down')
            if ((self.ed_ap.status.get_flag(FlagsInMainShip) or self.ed_ap.status.get_flag(FlagsInFighter))
                    and self.ed_ap.status.get_gui_focus() == GuiFocusNoFocus):
                self.ed_ap.keys.send('ResetPowerDistribution')
        elif msg == 'left':
            print('left')
            if ((self.ed_ap.status.get_flag(FlagsInMainShip) or self.ed_ap.status.get_flag(FlagsInFighter))
                    and self.ed_ap.status.get_gui_focus() == GuiFocusNoFocus):
                self.ed_ap.keys.send('ResetPowerDistribution')
                self.ed_ap.keys.send('IncreaseSystemsPower', repeat=3)
        elif msg == 'right':
            print('right')
            if ((self.ed_ap.status.get_flag(FlagsInMainShip) or self.ed_ap.status.get_flag(FlagsInFighter))
                    and self.ed_ap.status.get_gui_focus() == GuiFocusNoFocus):
                self.ed_ap.keys.send('ResetPowerDistribution')
                self.ed_ap.keys.send('IncreaseWeaponsPower', repeat=3)

    def update_ship_cfg(self):
        """
        Load up the display with what we read from ED_AP for the current ship.
        Triggered when the ship is changed.
        @return:
        """
        self.entries['ship']['SunPitchUp+Time'].delete(0, tk.END)
        self.entries['ship']['SunPitchUp+Time'].insert(0, self.ed_ap.sunpitchuptime)

        if self.ed_ap.current_ship_cfg:
            self.throttle_keys = [key for key, value in self.ed_ap.current_ship_cfg.items() if 'Speed' in key]
            self.throttle_combo['values'] = self.throttle_keys

    def calibrate_callback(self):
        self.ed_ap.calibrate_target()

    def quit(self):
        logger.debug("Entered: quit")
        self.close_window()

    def close_window(self):
        logger.debug("Entered: close_window")
        if self._settings_dirty:
            ans = messagebox.askyesnocancel("EDAP", "There are unsaved settings. Save them before closing?")
            if ans is None:
                return
            if ans:
                self.save_settings()
        self.stop_fsd()
        self.stop_sc()
        self.ed_ap.quit()
        sleep(0.1)
        self.root.destroy()

    # this routine is to stop any current autopilot activity
    def stop_all_assists(self):
        logger.debug("Entered: stop_all_assists")
        self.callback('stop_all_assists')

    def start_fsd(self):
        logger.debug("Entered: start_fsd")
        self.ed_ap.set_fsd_assist(True)
        self.FSD_A_running = True
        self.log_msg("FSD Route Assist start")
        self.ed_ap.vce.say("FSD Route Assist On")

    def stop_fsd(self):
        logger.debug("Entered: stop_fsd")
        self.ed_ap.set_fsd_assist(False)
        self.FSD_A_running = False
        self.log_msg("FSD Route Assist stop")
        self.ed_ap.vce.say("FSD Route Assist Off")
        self.update_statusline("Idle")

    def start_sc(self):
        logger.debug("Entered: start_sc")
        self.ed_ap.set_sc_assist(True)
        self.SC_A_running = True
        self.log_msg("SC Assist start")
        self.ed_ap.vce.say("Supercruise Assist On")

    def stop_sc(self):
        logger.debug("Entered: stop_sc")
        self.ed_ap.set_sc_assist(False)
        self.SC_A_running = False
        self.log_msg("SC Assist stop")
        self.ed_ap.vce.say("Supercruise Assist Off")
        self.update_statusline("Idle")

    def start_waypoint(self):
        logger.debug("Entered: start_waypoint")
        self.ed_ap.set_waypoint_assist(True)
        self.WP_A_running = True
        self.log_msg("Waypoint Assist start")
        self.ed_ap.vce.say("Waypoint Assist On")

    def stop_waypoint(self):
        logger.debug("Entered: stop_waypoint")
        self.ed_ap.set_waypoint_assist(False)
        self.WP_A_running = False
        self.log_msg("Waypoint Assist stop")
        self.ed_ap.vce.say("Waypoint Assist Off")
        self.update_statusline("Idle")

    def start_robigo(self):
        logger.debug("Entered: start_robigo")
        self.ed_ap.set_robigo_assist(True)
        self.RO_A_running = True
        self.log_msg("Robigo Assist start")
        self.ed_ap.vce.say("Robigo Assist On")

    def stop_robigo(self):
        logger.debug("Entered: stop_robigo")
        self.ed_ap.set_robigo_assist(False)
        self.RO_A_running = False
        self.log_msg("Robigo Assist stop")
        self.ed_ap.vce.say("Robigo Assist Off")
        self.update_statusline("Idle")

    def start_dss(self):
        logger.debug("Entered: start_dss")
        self.ed_ap.set_dss_assist(True)
        self.DSS_A_running = True
        self.log_msg("DSS Assist start")
        self.ed_ap.vce.say("DSS Assist On")

    def stop_dss(self):
        logger.debug("Entered: stop_dss")
        self.ed_ap.set_dss_assist(False)
        self.DSS_A_running = False
        self.log_msg("DSS Assist stop")
        self.ed_ap.vce.say("DSS Assist Off")
        self.update_statusline("Idle")

    def start_single_waypoint_assist(self):
        """ The debug command to go to a system or station or both."""
        logger.debug("Entered: start_single_waypoint_assist")
        system = self.single_waypoint_system.get()
        station = self.single_waypoint_station.get()

        if system != "" or station != "":
            self.ed_ap.set_single_waypoint_assist(system, station, True)
            self.SWP_A_running = True
            self.log_msg("Single Waypoint Assist start")
            self.ed_ap.vce.say("Single Waypoint Assist On")

    def stop_single_waypoint_assist(self):
        """ The debug command to go to a system or station or both."""
        logger.debug("Entered: stop_single_waypoint_assist")
        self.ed_ap.set_single_waypoint_assist("", "", False)
        self.SWP_A_running = False
        self.log_msg("Single Waypoint Assist stop")
        self.ed_ap.vce.say("Single Waypoint Assist Off")
        self.update_statusline("Idle")

    def about(self):
        webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui")

    def check_for_updates(self, repo_path):
        try:
            # Fetch the latest changes from the remote repository
            subprocess.run(["git", "fetch"], cwd=repo_path, check=True, capture_output=True)

            # Get the current commit hash of the local repository
            local_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True,
                                        check=True).stdout.strip()

            # Get the commit hash of the remote repository
            remote_hash = subprocess.run(["git", "rev-parse", "origin/HEAD"], cwd=repo_path, capture_output=True,
                                         text=True, check=True).stdout.strip()

            # Compare the commit hashes
            if local_hash != remote_hash:
                print("The repository has been updated. Please clone it again to get the latest version.")
                return True
            else:
                print("The repository is up to date.")
                return False

        except subprocess.CalledProcessError as e:
            print(f"Error checking for updates: {e}")
            return False
        except FileNotFoundError:
            print("Git command not found. Please ensure Git is installed and in your system's PATH.")
            return False

    def check_updates(self):
        # response = requests.get("https://api.github.com/repos/SumZer0-git/EDAPGui/releases/latest")
        # if EDAP_VERSION != response.json()["name"]:
        #     mb = messagebox.askokcancel("Update Check", "A new release version is available. Download now?")
        #     if mb == True:
        #         webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/releases/latest")

        # Example usage:
        # repo_path = "/path/to/your/local/repo"
        repo_path = "./"
        updates_available = self.check_for_updates(repo_path)

        if updates_available:
            # Optionally, provide further instructions or automate the cloning process
            self.log_msg("=====================================================")
            self.log_msg("========== An update to EDAP is available ===========")
            self.log_msg("==== Click 'Check for Updates' on the Debug tab, ====")
            self.log_msg("====== or go directly to the EDAP Github page =======")
            self.log_msg("=====================================================")

            # print("You can use the following command to clone the repository again:")
            # print("git clone <repository_url> <new_directory_name>")
        else:
            self.log_msg("You have the latest version of EDAP!")

    def on_throttle_select(self, event):
        # The actual logi cis done on the edit curve buttons.
        pass

    def open_changelog(self):
        webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/ChangeLog.md")

    def open_discord(self):
        webbrowser.open_new("https://discord.gg/HCgkfSc")

    def open_logfile(self):
        os.startfile('autopilot.log')

    def log_msg(self, msg, write_log: bool = True):
        message = datetime.now().strftime("%H:%M:%S: ") + msg
        if not write_log:
            # Already written to the log file by the calling thread
            try:
                if self.gui_loaded:
                    while not self.log_buffer.empty():
                        self.msgList.insert(tk.END, self.log_buffer.get())
                    self.msgList.insert(tk.END, message)
                    self._log_trim_and_scroll()
                else:
                    self.log_buffer.put(message)
            except Exception:
                self.log_buffer.put(message)
            return

        try:
            if not self.gui_loaded:
                # Store message in queue
                self.log_buffer.put(message)
                logger.info(msg)
            else:
                # Add queued messages to the list
                while not self.log_buffer.empty():
                    self.msgList.insert(tk.END, self.log_buffer.get())

                self.msgList.insert(tk.END, message)
                self._log_trim_and_scroll()
                logger.info(msg)
        except:
            # Store message in queue
            self.log_buffer.put(message)
            logger.info(msg)

    def _log_trim_and_scroll(self):
        """ Keeps the log list at max. 5000 lines (a long session made the GUI slow) and scrolls to the end. """
        size = self.msgList.size()
        if size > 5000:
            self.msgList.delete(0, size - 5000)
        if self.autoscroll_var is None or self.autoscroll_var.get():
            self.msgList.yview(tk.END)

    def set_statusbar(self, txt):
        self.statusbar.configure(text=txt)

    def update_jumpcount(self, txt):
        self._jump_text = txt
        self.jumpcount.configure(text=txt)

    def update_statusline(self, txt):
        self._status_text = txt
        self.status.configure(text="Status: " + txt)
        self.log_msg(f"Status update: {txt}")

    # ------------------------------------------------------------------
    # Live status panel (main tab)
    # ------------------------------------------------------------------
    def _read_status_json(self) -> dict:
        try:
            with open(self.ed_ap.status.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _update_live_panel(self):
        """ Updates the status panel once per second. Only reads data (no journal file access from this thread). """
        try:
            ship = getattr(self.ed_ap.jn, 'ship', {}) or {}
            st = self._read_status_json()

            mode = self._active_mode or "Idle"
            self.live['mode'].configure(text=mode, foreground="#57c26a" if self._active_mode else "#9a9a9a")
            self.live['status'].configure(text=self._status_text or "-")
            if self._session_start:
                self.live['runtime'].configure(text=self._fmt_duration(time.time() - self._session_start))
            else:
                self.live['runtime'].configure(text="-")

            system = ship.get('cur_star_system') or '-'
            station = ship.get('cur_station') or ''
            flags = st.get('Flags', 0) or 0
            docked = bool(flags & 1)
            self.live['location'].configure(text=f"{system}" + (f"  /  {station} (docked)" if docked and station else ""))

            ship_type = ship.get('type') or '-'
            self.live['ship'].configure(text=str(ship_type).replace('_', ' ').title())

            cap = ship.get('fuel_capacity')
            fuel = (st.get('Fuel') or {}).get('FuelMain', ship.get('fuel_level'))
            if fuel is not None and cap:
                pct = max(0.0, min(100.0, 100.0 * float(fuel) / float(cap)))
                self.live['fuel_bar'].configure(value=pct)
                self.live['fuel'].configure(text=f"{float(fuel):.1f} / {float(cap):.0f} t  ({pct:.0f}%)")
            else:
                self.live['fuel_bar'].configure(value=0)
                self.live['fuel'].configure(text="-")

            cargo = st.get('Cargo')
            cargo_cap = ship.get('cargo_capacity')
            if cargo is not None:
                self.live['cargo'].configure(text=f"{int(cargo)} / {cargo_cap if cargo_cap else '?'} t")
            else:
                self.live['cargo'].configure(text="-")

            wp = self.ed_ap.waypoint
            if wp.waypoints:
                name = os.path.basename(wp.filename) if wp.filename else "(not saved)"
                keys = [k for k in wp.waypoints if k != 'GlobalShoppingList']
                step_txt = ""
                if self._active_mode == 'Waypoint Assist' and 0 <= wp.step < len(list(wp.waypoints)):
                    key = list(wp.waypoints)[wp.step]
                    w = wp.waypoints.get(key, {})
                    step_txt = f"  -  next: {w.get('SystemName', '')} / {w.get('StationName', '')}"
                self.live['waypoints'].configure(text=f"{name} ({len(keys)} entries){step_txt}")
            else:
                self.live['waypoints'].configure(text="no file loaded")

            self.live['jumps'].configure(text=self._jump_text or "-")
        except Exception as e:
            logger.debug(f"live panel update failed: {e}")
        finally:
            self.root.after(1000, self._update_live_panel)

    def clear_log(self):
        self.msgList.delete(0, tk.END)

    def _assist_running(self) -> bool:
        ap = self.ed_ap
        return any([ap.fsd_assist_enabled, ap.sc_assist_enabled, ap.waypoint_assist_enabled,
                    ap.robigo_assist_enabled, ap.afk_combat_assist_enabled, ap.dss_assist_enabled])

    def _run_ship_action(self, name: str, func):
        """ Runs a ship action started by a GUI button (throttle, Align to Target, ...) in a background thread.
        Before, these ran in the Tk main thread: the key sender waits while Elite is not the active window, and
        after clicking the button the EDAP window IS the active window, so the GUI froze (white window) until
        Elite was clicked again. Elite is brought to the front first. Not allowed while an assist is running
        (two threads steering the ship at the same time). """
        if self._assist_running():
            self.log_msg(f"'{name}' is not possible while an assist is running. Stop the assist first.")
            return
        if getattr(self, '_ship_action_thread', None) is not None and self._ship_action_thread.is_alive():
            self.log_msg(f"'{name}': the previous ship action is still running.")
            return

        def worker():
            try:
                set_focus_elite_window()
                sleep(0.3)
                func()
            except Exception as e:
                logger.exception(f"Ship action '{name}' failed")
                self.callback('log', f"'{name}' failed: {e}")

        self._ship_action_thread = threading.Thread(target=worker, name=f"ShipAction-{name}", daemon=True)
        self._ship_action_thread.start()

    def ship_throttle_0(self):
        self._run_ship_action('0% Throttle', self.ed_ap.set_throttle_0)

    def ship_throttle_50(self):
        self._run_ship_action('50% Throttle', self.ed_ap.set_throttle_50)

    def ship_throttle_100(self):
        self._run_ship_action('100% Throttle', self.ed_ap.set_throttle_100)

    def edit_roll_curve(self):
        # Get current ship roll curve
        if self.ed_ap.current_ship_cfg:
            # Get the selected speed from the combobox
            selected_throttle = self.throttle_var.get()  # i.e. SCSpeed50 etc.
            if selected_throttle in self.ed_ap.current_ship_cfg:
                spd_dmd_dict = self.ed_ap.current_ship_cfg[selected_throttle]
                if 'RollRate' in spd_dmd_dict:
                    curve = spd_dmd_dict['RollRate']
                    # Edit the curve
                    new_curve = line_editor(curve, f"{selected_throttle} - Roll curve")
                    if new_curve is not None:
                        if messagebox.askyesno("RPY curve", "Keep the changes made to curve? If Yes, remember to save."):
                            spd_dmd_dict['RollRate'] = new_curve
            else:
                messagebox.showinfo("EDAP", "Select a Throttle setting in the dropdown above.")

    def edit_pit_curve(self):
        # Get current ship pitch curve
        if self.ed_ap.current_ship_cfg:
            # Get the selected speed from the combobox
            selected_throttle = self.throttle_var.get()  # i.e. SCSpeed50 etc.
            if selected_throttle in self.ed_ap.current_ship_cfg:
                spd_dmd_dict = self.ed_ap.current_ship_cfg[selected_throttle]
                if 'PitchRate' in spd_dmd_dict:
                    curve = spd_dmd_dict['PitchRate']
                    # Edit the curve
                    new_curve = line_editor(curve, f"{selected_throttle} - Pitch curve")
                    if new_curve is not None:
                        if messagebox.askyesno("RPY curve", "Keep the changes made to curve? If Yes, remember to save."):
                            spd_dmd_dict['PitchRate'] = new_curve
            else:
                messagebox.showinfo("EDAP", "Select a Throttle setting in the dropdown above.")

    def edit_yaw_curve(self):
        # Get current ship yaw curve
        if self.ed_ap.current_ship_cfg:
            # Get the selected speed from the combobox
            selected_throttle = self.throttle_var.get()  # i.e. SCSpeed50 etc.
            if selected_throttle in self.ed_ap.current_ship_cfg:
                spd_dmd_dict = self.ed_ap.current_ship_cfg[selected_throttle]
                if 'YawRate' in spd_dmd_dict:
                    curve = spd_dmd_dict['YawRate']
                    # Edit the curve
                    new_curve = line_editor(curve, f"{selected_throttle} - Pitch curve")
                    if new_curve is not None:
                        if messagebox.askyesno("RPY curve", "Keep the changes made to curve? If Yes, remember to save."):
                            spd_dmd_dict['YawRate'] = new_curve
            else:
                messagebox.showinfo("EDAP", "Select a Throttle setting in the dropdown above.")

    def tuning_align_target(self):
        """
        Aligns to the target for tuning.
        @return: N/A
        """
        self._run_ship_action('Align to Target', lambda: self.ed_ap.compass_align(self.ed_ap.scrReg))

    def save_settings(self):
        self.entry_update(None)
        self.ed_ap.update_config()
        self.ed_ap.update_ship_configs()
        self.calibration.save_ocr_calibration_data()
        if self.settings_tab is not None:
            self.settings_tab.mark_saved()
        self.log_msg("Saved all settings.")

    def load_settings(self):
        """ Reloads AP.json and the ship configs from disk (discards unsaved changes). """
        if self._settings_dirty and not messagebox.askyesno(
                "Load settings", "Discard the unsaved changes and load the settings from disk?"):
            return
        self.ed_ap.load_config()
        self.ed_ap.process_config_settings()
        self.ed_ap.load_ship_configs()
        if self.settings_tab is not None:
            self.settings_tab.config = self.ed_ap.config  # load_config() created a new dict
            self.settings_tab.reload()
            self.settings_tab.mark_saved()
        self.setup_hotkeys()
        self.log_msg("Loaded all settings from disk.")

    def open_help(self):
        # Determine the active Tab
        tab_text = self._nb.tab(self._nb.select(), "text")

        if tab_text == "Ship":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/RollPitchYaw.md")
        elif tab_text == "Main":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/Main.md")
        elif tab_text == "Settings":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/Settings.md")
        elif tab_text == "Debug/Test":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/DebugTest.md")
        elif tab_text == "Calibration":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/Calibration.md")
        elif tab_text == "Waypoints":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/WaypointEditor.md")
        elif tab_text == "Colonization":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/ColonizationEditor.md")
        elif tab_text == "TCE":
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/TCE.md")
        else:
            messagebox.showwarning("Warning", f"No match for tab text '{tab_text}'. Please report to developers.")
            webbrowser.open_new("https://github.com/SumZer0-git/EDAPGui/blob/main/docs/Main.md")


    def entry_update(self, event):
        """ Reads the remaining entry fields (ship tab). All other settings are applied by the settings tab at once.
        @param event: A dummy argument required the calling function.
        """
        try:
            self.ed_ap.sunpitchuptime = float(self.entries['ship']['SunPitchUp+Time'].get())
        except ValueError:
            messagebox.showinfo("EDAP", "SunPitchUp Time: please enter a number.")
            return
        self.ed_ap.config['AutoTuneRPYRates'] = self.checkboxvar['Enable Auto-tune RPY'].get()
        self.ed_ap.process_config_settings()

    def on_setting_change(self, key, value):
        """ Called by the settings tab after a value was changed: apply it at once. """
        ap = self.ed_ap
        if key == 'EnableRandomness':
            ap.set_randomness(value)
        elif key == 'ActivateEliteEachKey':
            ap.set_activate_elite_eachkey(value)
            ap.keys.activate_window = value
        elif key == 'AutomaticLogout':
            ap.set_automatic_logout(value)
        elif key == 'OverlayTextEnable':
            ap.set_overlay(value)
        elif key == 'VoiceEnable':
            ap.set_voice(value)
        elif key == 'ElwScannerEnable':
            ap.set_fss_scan(value)
        elif key == 'HotkeysEnable' or key.startswith('HotKey_'):
            self.setup_hotkeys()
        elif key in ('Language', 'OCRLanguage', 'OCRMobile'):
            self.log_msg(f"'{key}' changed to '{value}'. Save the settings and restart EDAP to use it.")
        ap.process_config_settings()

    def on_settings_dirty(self, dirty: bool):
        self._settings_dirty = dirty
        if self.btn_save is not None:
            self.btn_save.configure(text='Save All Settings *' if dirty else 'Save All Settings')

    # Assist modes: checkbox name -> (start function, stop function, running flag attribute)
    MODE_FIELDS = ('FSD Route Assist', 'Supercruise Assist', 'Waypoint Assist', 'Robigo Assist',
                   'AFK Combat Assist', 'DSS Assist')

    def _mode_funcs(self, field):
        return {
            'FSD Route Assist': (self.start_fsd, self.stop_fsd, 'FSD_A_running'),
            'Supercruise Assist': (self.start_sc, self.stop_sc, 'SC_A_running'),
            'Waypoint Assist': (self.start_waypoint, self.stop_waypoint, 'WP_A_running'),
            'Robigo Assist': (self.start_robigo, self.stop_robigo, 'RO_A_running'),
            'AFK Combat Assist': (self.start_afk, self.stop_afk, 'AFK_A_running'),
            'DSS Assist': (self.start_dss, self.stop_dss, 'DSS_A_running'),
        }[field]

    def _set_other_modes_state(self, field, state: str):
        """ Only one assist can run: the other mode checkboxes are disabled while one runs. """
        for other in self.MODE_FIELDS:
            if other != field and other in self.lab_ck:
                self.lab_ck[other].config(state=state)

    def check_cb(self, field):
        """ Check checkbox
            ckbox.state:(ACTIVE | DISABLED)
        """
        if field in self.MODE_FIELDS:
            start, stop, flag = self._mode_funcs(field)
            checked = self.checkboxvar[field].get() == 1
            running = getattr(self, flag, False)
            if checked and not running:
                if field == 'Waypoint Assist' and not self._ensure_waypoint_file():
                    self.checkboxvar[field].set(0)
                    return
                self._set_other_modes_state(field, 'disabled')
                start()
                self._mode_started(field)
            elif not checked and running:
                stop()
                self._set_other_modes_state(field, 'normal')
                self._mode_stopped(field)
            return

        if field == 'Enable CV View':
            if self.checkboxvar['Enable CV View'].get() == 1:
                self.cv_view = True
                x = self.root.winfo_x() + self.root.winfo_width() + 4
                y = self.root.winfo_y()
                self.ed_ap.set_cv_view(True, x, y)
            else:
                self.cv_view = False
                self.ed_ap.set_cv_view(False)

        if field == 'debug_mode':
            if self.radiobuttonvar['debug_mode'].get() == "Error":
                self.ed_ap.set_log_error(True)
            elif self.radiobuttonvar['debug_mode'].get() == "Debug":
                self.ed_ap.set_log_debug(True)
            elif self.radiobuttonvar['debug_mode'].get() == "Info":
                self.ed_ap.set_log_info(True)

        if field == 'Single Waypoint Assist':
            if self.checkboxvar['Single Waypoint Assist'].get() == 1 and self.SWP_A_running == False:
                self.start_single_waypoint_assist()
                if self.SWP_A_running:
                    self._mode_started('Single Waypoint Assist')
                else:
                    self.checkboxvar['Single Waypoint Assist'].set(0)
            elif self.checkboxvar['Single Waypoint Assist'].get() == 0 and self.SWP_A_running == True:
                self.stop_single_waypoint_assist()
                self._mode_stopped('Single Waypoint Assist')

        if field == 'Debug Overlay':
            self.ed_ap.debug_overlay = bool(self.checkboxvar['Debug Overlay'].get())
            self.ed_ap.config['DebugOverlay'] = self.ed_ap.debug_overlay

        if field == 'Debug OCR':
            self.ed_ap.debug_ocr = self.checkboxvar['Debug OCR'].get()
            self.ed_ap.config['DebugOCR'] = bool(self.ed_ap.debug_ocr)

        if field == 'Debug Images':
            self.ed_ap.debug_images = self.checkboxvar['Debug Images'].get()
            self.ed_ap.config['DebugImages'] = bool(self.ed_ap.debug_images)

        if field == 'Enable Auto-tune RPY':
            self.ed_ap.config['AutoTuneRPYRates'] = self.checkboxvar['Enable Auto-tune RPY'].get()
            self.ed_ap.process_config_settings()

    def _mode_started(self, field):
        self._active_mode = field
        self._session_start = time.time()
        self._jump_text = ""

    def _mode_stopped(self, field):
        if self._active_mode == field:
            if self._session_start:
                self.log_msg(f"{field} ran for {self._fmt_duration(time.time() - self._session_start)}.")
            self._active_mode = None
            self._session_start = None

    def _ensure_waypoint_file(self) -> bool:
        """ Waypoint Assist needs a waypoint file. If none is loaded, ask for one. """
        wp = self.ed_ap.waypoint
        if wp.waypoints and len(wp.waypoints) > 0:
            return True
        initial = os.path.abspath('./waypoints')
        filepath = fd.askopenfilename(title="Waypoint Assist: select a waypoint file", initialdir=initial,
                                      filetypes=[("Waypoint files", "*.json"), ("All files", "*.*")])
        if not filepath:
            self.log_msg("Waypoint Assist not started: no waypoint file selected.")
            return False
        try:
            if self.waypoint_editor_tab is not None:
                self.waypoint_editor_tab.editor_load_waypoint_file(filepath)
            else:
                wp.load_waypoint_file(filepath)
        except Exception as e:
            self.log_msg(f"Could not load the waypoint file: {e}")
            return False
        if not wp.waypoints:
            self.log_msg("The waypoint file is empty or invalid.")
            return False
        return True

    def start_afk(self):
        self.ed_ap.set_afk_combat_assist(True)
        self.AFK_A_running = True
        self.log_msg("AFK Combat Assist start")

    def stop_afk(self):
        self.ed_ap.set_afk_combat_assist(False)
        self.AFK_A_running = False
        self.log_msg("AFK Combat Assist stop")
        self.update_statusline("Idle")

    @staticmethod
    def _fmt_duration(secs: float) -> str:
        secs = int(max(0, secs))
        return f"{secs // 3600:d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"

    def makeform(self, win: ttk.LabelFrame, f_type: int, fields, r: int = 0, inc: float = 1, r_from: float = 0,
                 rto: float = 1000):
        entries = {}
        win.columnconfigure(1, weight=1)

        for fld in fields:
            if f_type == FORM_TYPE_CHECKBOX:
                self.checkboxvar[fld] = tk.IntVar()
                lab = ttk.Checkbutton(win, text=fld, variable=self.checkboxvar[fld],
                                      command=(lambda field=fld: self.check_cb(field)))
                self.lab_ck[fld] = lab
                lab.grid(row=r, column=0, columnspan=2, padx=2, pady=2, sticky=tk.W)
            else:
                lab = ttk.Label(win, text=fld + ": ")
                if f_type == FORM_TYPE_SPINBOX:
                    ent = ttk.Spinbox(win, width=10, from_=r_from, to=rto, increment=inc, justify=tk.RIGHT)
                else:
                    ent = ttk.Entry(win, width=10, justify=tk.RIGHT)
                ent.bind('<FocusOut>', self.entry_update)
                ent.insert(0, "0")
                lab.grid(row=r, column=0, padx=2, pady=2, sticky=tk.W)
                ent.grid(row=r, column=1, padx=2, pady=2, sticky=tk.E)
                entries[fld] = ent

            lab = ToolTip(lab, msg=self.tooltips[fld], delay=1.0, bg="#808080", fg="#FFFFFF")
            r += 1
        return entries

    def _tip(self, widget, text):
        if text:
            ToolTip(widget, msg=text, delay=0.6, bg="#808080", fg="#FFFFFF")

    def gui_gen(self, win):

        modes_check_fields = self.MODE_FIELDS

        # ---- top bar ---------------------------------------------------------------------------------------------
        blk_top_buttons = ttk.Frame(win)
        blk_top_buttons.grid(row=0, column=0, padx=10, pady=5, sticky="EW")
        blk_top_buttons.columnconfigure(2, weight=1)

        btn_load = ttk.Button(blk_top_buttons, text='Load All Settings', command=self.load_settings)
        btn_load.grid(row=0, column=0, padx=5, pady=5, sticky="W")
        self._tip(btn_load, "Reload AP.json and the ship configs from disk (discards unsaved changes).")
        self.btn_save = ttk.Button(blk_top_buttons, text='Save All Settings', command=self.save_settings,
                                   style="Accent.TButton")
        self.btn_save.grid(row=0, column=1, padx=2, pady=5, sticky="W")
        self._tip(self.btn_save, "Write all settings, ship configs and calibration to disk.\n"
                                 "'*' = there are unsaved changes.")
        ttk.Button(blk_top_buttons, text="Online HELP", command=self.open_help).grid(row=0, column=3, padx=5,
                                                                                     pady=10, sticky=tk.E)

        self._nb = ttk.Notebook(win)
        self._nb.grid(row=1, padx=10, pady=5, sticky="NSEW")

        page0 = ttk.Frame(self._nb)
        page0.grid_columnconfigure(0, weight=1)
        page0.grid_rowconfigure(1, weight=1)  # Log row
        self._nb.add(page0, text="Main")

        page_ship = ttk.Frame(self._nb)
        page_ship.grid_columnconfigure([0, 1], weight=1, uniform="ship")
        self._nb.add(page_ship, text="Ship")

        page1 = ttk.Frame(self._nb)
        self._nb.add(page1, text="Settings")

        page2 = ttk.Frame(self._nb)
        page2.grid_columnconfigure([0, 1], weight=1)
        self._nb.add(page2, text="Debug/Test")

        # === Calibration Tab ===
        page_calibration = ttk.Frame(self._nb)
        page_calibration.grid_columnconfigure(0, weight=1)
        self._nb.add(page_calibration, text="Calibration")
        self.calibration = Calibration(self.ed_ap, self.callback)
        self.calibration.create_calibration_tab(page_calibration)

        # === Waypoint Editor Tab ===
        page_waypoint_editor = ttk.Frame(self._nb)
        page_waypoint_editor.grid_columnconfigure(0, weight=1)
        self._nb.add(page_waypoint_editor, text="Waypoints")
        self.waypoint_editor_tab = WaypointEditorTab(page_waypoint_editor, self.ed_ap.waypoint)
        self.waypoint_editor_tab.frame.pack(fill="both", expand=True)

        # === Colonization Editor Tab ===
        tab_colonize_editor = ttk.Frame(self._nb)
        tab_colonize_editor.grid_columnconfigure(0, weight=1)
        self._nb.add(tab_colonize_editor, text="Colonization")
        self.colonize_tab = ColonizeEditorTab(self.ed_ap, self.callback)
        self.colonize_tab.create_waypoints_tab(tab_colonize_editor)
        self.colonize_tab.frame.pack(fill="both", expand=True)

        # === TCE Integration ===
        page_tce_integration = ttk.Frame(self._nb)
        page_tce_integration.grid_columnconfigure(0, weight=1)
        self._nb.add(page_tce_integration, text="TCE")
        self.ed_ap.tce_integration.create_gui_tab(self, page_tce_integration)

        # ==============================================================================================================
        # MAIN TAB: modes | live status, log
        # ==============================================================================================================
        blk_main = ttk.Frame(page0)
        blk_main.grid(row=0, column=0, padx=10, pady=5, sticky="NSEW")
        blk_main.columnconfigure(0, weight=2, uniform="main")
        blk_main.columnconfigure(1, weight=3, uniform="main")

        # --- modes
        blk_modes = ttk.LabelFrame(blk_main, text="MODE  (tick to start, untick to stop)", padding=(10, 5))
        blk_modes.grid(row=0, column=0, padx=2, pady=2, sticky="NSEW")
        self.makeform(blk_modes, FORM_TYPE_CHECKBOX, modes_check_fields)
        btn_stop = ttk.Button(blk_modes, text="STOP ALL", command=self.stop_all_assists, style="Accent.TButton")
        btn_stop.grid(row=len(modes_check_fields), column=0, columnspan=2, padx=2, pady=(10, 4), sticky="EW")
        hk = self.ed_ap.config.get('HotKey_StopAllAssists', 'end')
        self._tip(btn_stop, f"Stops every running assist at once.\nHotkey: '{hk}' (if hotkeys are enabled in "
                            f"Settings > Hotkeys).")

        # --- live status
        blk_live = ttk.LabelFrame(blk_main, text="STATUS", padding=(10, 5))
        blk_live.grid(row=0, column=1, padx=2, pady=2, sticky="NSEW")
        blk_live.columnconfigure(1, weight=1)
        rows = (('mode', 'Assist'), ('status', 'Activity'), ('runtime', 'Running for'), ('location', 'Location'),
                ('ship', 'Ship'), ('fuel', 'Fuel'), ('cargo', 'Cargo'), ('waypoints', 'Waypoints'),
                ('jumps', 'Jumps'))
        r = 0
        for key, label in rows:
            ttk.Label(blk_live, text=label + ":", foreground="#9a9a9a").grid(row=r, column=0, sticky="NW", padx=2,
                                                                             pady=1)
            if key == 'fuel':
                frm = ttk.Frame(blk_live)
                frm.grid(row=r, column=1, sticky="EW", padx=2, pady=1)
                frm.columnconfigure(0, weight=1)
                self.live['fuel_bar'] = ttk.Progressbar(frm, maximum=100, value=0, length=120)
                self.live['fuel_bar'].grid(row=0, column=0, sticky="EW", padx=(0, 6))
                self.live['fuel'] = ttk.Label(frm, text="-")
                self.live['fuel'].grid(row=0, column=1, sticky="W")
            else:
                self.live[key] = ttk.Label(blk_live, text="-", wraplength=330, justify=tk.LEFT)
                self.live[key].grid(row=r, column=1, sticky="W", padx=2, pady=1)
            r += 1
        self.live['mode'].configure(font=("Segoe UI", 10, "bold"))

        # --- log
        log = ttk.LabelFrame(page0, text="LOG", padding=(10, 5))
        log.grid(row=1, column=0, padx=10, pady=5, sticky="NSEW")
        log.grid_columnconfigure(0, weight=1)
        log.grid_rowconfigure(1, weight=1)
        log_bar = ttk.Frame(log)
        log_bar.grid(row=0, column=0, columnspan=2, sticky="EW", pady=(0, 4))
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_bar, text="Auto-scroll", variable=self.autoscroll_var).pack(side="left")
        ttk.Button(log_bar, text="Open log file", command=self.open_logfile).pack(side="right", padx=2)
        ttk.Button(log_bar, text="Clear", command=self.clear_log).pack(side="right", padx=2)
        y_scrollbar = ttk.Scrollbar(log)
        y_scrollbar.grid(row=1, column=1, sticky="NSE")
        x_scrollbar = ttk.Scrollbar(log, orient="horizontal")
        x_scrollbar.grid(row=2, column=0, sticky="EW")
        mylist = tk.Listbox(log, width=100, height=14, yscrollcommand=y_scrollbar.set,
                            xscrollcommand=x_scrollbar.set)
        mylist.grid(row=1, column=0, sticky="NSEW")
        y_scrollbar.config(command=mylist.yview)
        x_scrollbar.config(command=mylist.xview)

        # ==============================================================================================================
        # SHIP TAB: tuning of the ship rotation rates
        # ==============================================================================================================
        blk_ship = ttk.LabelFrame(page_ship, text="SHIP SETTINGS", padding=(10, 5))
        blk_ship.grid(row=0, column=0, padx=10, pady=5, sticky="NSEW")
        blk_ship.columnconfigure(1, weight=1)

        lbl_sun_pitch_up = ttk.Label(blk_ship, text='SunPitchUp +/- Time (s):')
        lbl_sun_pitch_up.grid(row=0, column=0, pady=3, sticky=tk.W)
        spn_sun_pitch_up = ttk.Spinbox(blk_ship, width=10, from_=-100, to=100, increment=0.5, justify=tk.RIGHT)
        spn_sun_pitch_up.grid(row=0, column=1, padx=2, pady=2, sticky=tk.E)
        spn_sun_pitch_up.bind('<FocusOut>', self.entry_update)
        spn_sun_pitch_up.bind('<Return>', self.entry_update)
        self.entries['ship'] = {}
        self.entries['ship']['SunPitchUp+Time'] = spn_sun_pitch_up
        self._tip(lbl_sun_pitch_up, self.tooltips['SunPitchUp+Time'])

        self.checkboxvar['Enable Auto-tune RPY'] = tk.BooleanVar()
        self.checkboxvar['Enable Auto-tune RPY'].set(bool(self.ed_ap.config['AutoTuneRPYRates']))
        cb_auto_tune_rpy = ttk.Checkbutton(blk_ship, text='Auto-tune roll/pitch/yaw rates while flying',
                                           variable=self.checkboxvar['Enable Auto-tune RPY'],
                                           command=(lambda field='Enable Auto-tune RPY': self.check_cb(field)))
        cb_auto_tune_rpy.grid(row=1, column=0, columnspan=2, padx=2, pady=6, sticky=tk.W)
        self._tip(cb_auto_tune_rpy, "Measures how far the ship really turns for each key press and corrects the "
                                    "rate curves (saved automatically every 20 s).\nSwitch it off when the "
                                    "steering is good.")

        lbl_steps = ttk.Label(blk_ship, justify=tk.LEFT, foreground="#9a9a9a",
                              text="How to tune:\n"
                                   "1. Enable auto-tune and fly (or use 'Align to Target').\n"
                                   "2. Repeat until the ship turns precisely onto the target.\n"
                                   "3. Optional: check/edit a curve on the right, then Save.\n"
                                   "4. Disable auto-tune.")
        lbl_steps.grid(row=2, column=0, columnspan=2, pady=5, sticky=tk.W)

        blk_test = ttk.LabelFrame(page_ship, text="TEST (Elite is brought to the front)", padding=(10, 5))
        blk_test.grid(row=1, column=0, padx=10, pady=5, sticky="NSEW")
        blk_test.columnconfigure([0, 1, 2], weight=1, uniform="thr")
        ttk.Button(blk_test, text='0% Throttle', command=self.ship_throttle_0).grid(row=0, column=0, padx=2, pady=4,
                                                                                    sticky="EW")
        ttk.Button(blk_test, text='50% Throttle', command=self.ship_throttle_50).grid(row=0, column=1, padx=2,
                                                                                      pady=4, sticky="EW")
        ttk.Button(blk_test, text='100% Throttle', command=self.ship_throttle_100).grid(row=0, column=2, padx=2,
                                                                                        pady=4, sticky="EW")
        btn_align_target = ttk.Button(blk_test, text='Align to Target', command=self.tuning_align_target)
        btn_align_target.grid(row=1, column=0, columnspan=3, padx=2, pady=4, sticky="EW")
        self._tip(btn_align_target, "Turns the ship to the selected target with the compass (uses and tunes the "
                                    "current rate curves). Not possible while an assist is running.")

        blk_curves = ttk.LabelFrame(page_ship, text="RATE CURVES", padding=(10, 5))
        blk_curves.grid(row=0, column=1, rowspan=2, padx=10, pady=5, sticky="NSEW")
        blk_curves.columnconfigure(1, weight=1)
        ttk.Label(blk_curves, text="Throttle:").grid(row=0, column=0, padx=2, pady=5, sticky=tk.W)
        self.throttle_var = tk.StringVar()
        self.throttle_combo = ttk.Combobox(blk_curves, textvariable=self.throttle_var, values=self.throttle_keys,
                                           state="readonly")
        self.throttle_combo.grid(row=0, column=1, padx=2, pady=5, sticky="EW")
        self.throttle_combo.bind("<<ComboboxSelected>>", self.on_throttle_select)
        self._tip(self.throttle_combo, "Speed setting the curves belong to (e.g. SCSpeed50 = 50 % in supercruise).")
        ttk.Button(blk_curves, text='Edit Roll Curve', command=self.edit_roll_curve).grid(
            row=1, column=0, columnspan=2, padx=2, pady=3, sticky="EW")
        ttk.Button(blk_curves, text='Edit Pitch Curve', command=self.edit_pit_curve).grid(
            row=2, column=0, columnspan=2, padx=2, pady=3, sticky="EW")
        ttk.Button(blk_curves, text='Edit Yaw Curve', command=self.edit_yaw_curve).grid(
            row=3, column=0, columnspan=2, padx=2, pady=3, sticky="EW")
        ttk.Label(blk_curves, foreground="#9a9a9a", justify=tk.LEFT, wraplength=300,
                  text="A curve maps the wanted turn angle to the key hold time. Changed curves are kept after "
                       "'Save All Settings'.").grid(row=4, column=0, columnspan=2, pady=8, sticky=tk.W)

        # ==============================================================================================================
        # SETTINGS TAB
        # ==============================================================================================================
        self.settings_tab = SettingsTab(page1, self.ed_ap.config, self.ed_ap.default_config(),
                                        on_change=self.on_setting_change, on_dirty=self.on_settings_dirty)

        # ==============================================================================================================
        # DEBUG/TEST TAB
        # ==============================================================================================================
        # File Actions
        blk_file_actions = ttk.LabelFrame(page2, text="File Actions", padding=(10, 5))
        blk_file_actions.grid(row=0, column=0, padx=10, pady=5, sticky="NSEW")
        self.checkboxvar['Enable CV View'] = tk.IntVar()
        self.checkboxvar['Enable CV View'].set(int(self.ed_ap.config['Enable_CV_View']))
        cb_enable_cv_view = ttk.Checkbutton(blk_file_actions, text='Enable CV View', variable=self.checkboxvar['Enable CV View'], command=(lambda field='Enable CV View': self.check_cb(field)))
        cb_enable_cv_view.grid(row=2, column=0, padx=2, pady=2, sticky=tk.W)
        btn_restart = ttk.Button(blk_file_actions, text="Restart", command=self.restart_program)
        btn_restart.grid(row=3, column=0, padx=2, pady=2, sticky=tk.W)
        btn_exit = ttk.Button(blk_file_actions, text="Exit", command=self.close_window)
        btn_exit.grid(row=4, column=0, padx=2, pady=2, sticky=tk.W)

        # Help Actions
        blk_help_actions = ttk.LabelFrame(page2, text="Help Actions", padding=(10, 5))
        blk_help_actions.grid(row=0, column=1, padx=10, pady=5, sticky="NSEW")
        btn_check_updates = ttk.Button(blk_help_actions, text="Check for Updates", command=self.check_updates)
        btn_check_updates.grid(row=0, column=0, padx=2, pady=2, sticky=tk.W)
        btn_view_changelog = ttk.Button(blk_help_actions, text="View Changelog", command=self.open_changelog)
        btn_view_changelog.grid(row=1, column=0, padx=2, pady=2, sticky=tk.W)
        btn_join_discord = ttk.Button(blk_help_actions, text="Join Discord", command=self.open_discord)
        btn_join_discord.grid(row=2, column=0, padx=2, pady=2, sticky=tk.W)
        btn_about = ttk.Button(blk_help_actions, text="About", command=self.about)
        btn_about.grid(row=3, column=0, padx=2, pady=2, sticky=tk.W)

        # Debug Settings frame
        blk_debug_settings = ttk.LabelFrame(page2, text="Log Level", padding=(10, 5))
        blk_debug_settings.grid(row=1, column=0, padx=10, pady=5, sticky="NSEW")
        self.radiobuttonvar['debug_mode'] = tk.StringVar()
        rb_debug_debug = ttk.Radiobutton(blk_debug_settings, text="Debug + Info + Errors", variable=self.radiobuttonvar['debug_mode'], value="Debug", command=(lambda field='debug_mode': self.check_cb(field)))
        rb_debug_debug.grid(row=0, column=1, columnspan=2, sticky=tk.W)
        rb_debug_info = ttk.Radiobutton(blk_debug_settings, text="Info + Errors", variable=self.radiobuttonvar['debug_mode'], value="Info", command=(lambda field='debug_mode': self.check_cb(field)))
        rb_debug_info.grid(row=1, column=1, columnspan=2, sticky=tk.W)
        rb_debug_error = ttk.Radiobutton(blk_debug_settings, text="Errors only", variable=self.radiobuttonvar['debug_mode'], value="Error", command=(lambda field='debug_mode': self.check_cb(field)))
        rb_debug_error.grid(row=2, column=1, columnspan=2, sticky=tk.W)
        btn_open_logfile = ttk.Button(blk_debug_settings, text='Open Log File', command=self.open_logfile)
        btn_open_logfile.grid(row=3, column=0, padx=2, pady=2, columnspan=2, sticky="NSEW")

        # Single Waypoint Assist frame
        blk_single_waypoint_asst = ttk.LabelFrame(page2, text="Single Waypoint Assist", padding=(10, 5))
        blk_single_waypoint_asst.grid(row=1, column=1, padx=10, pady=5, sticky="NSEW")
        blk_single_waypoint_asst.columnconfigure(0, weight=1, minsize=10)
        blk_single_waypoint_asst.columnconfigure(1, weight=3, minsize=10)

        lbl_system = ttk.Label(blk_single_waypoint_asst, text='System:')
        lbl_system.grid(row=0, column=0, padx=2, pady=2, columnspan=1, sticky="NSEW")
        txt_system = ttk.Entry(blk_single_waypoint_asst, textvariable=self.single_waypoint_system)
        txt_system.grid(row=0, column=1, padx=2, pady=2, columnspan=1, sticky="NSEW")
        lbl_station = ttk.Label(blk_single_waypoint_asst, text='Station:')
        lbl_station.grid(row=1, column=0, padx=2, pady=2, columnspan=1, sticky="NSEW")
        txt_station = ttk.Entry(blk_single_waypoint_asst, textvariable=self.single_waypoint_station)
        txt_station.grid(row=1, column=1, padx=2, pady=2, columnspan=1, sticky="NSEW")
        self.checkboxvar['Single Waypoint Assist'] = tk.BooleanVar()
        cb_single_waypoint = ttk.Checkbutton(blk_single_waypoint_asst, text='Single Waypoint Assist', variable=self.checkboxvar['Single Waypoint Assist'], command=(lambda field='Single Waypoint Assist': self.check_cb(field)))
        cb_single_waypoint.grid(row=2, column=0, padx=2, pady=2, columnspan=2, sticky="NSEW")
        self._tip(cb_single_waypoint, self.tooltips['Single Waypoint Assist'])

        blk_debug_buttons = ttk.LabelFrame(page2, text="Debug Output", padding=(10, 5))
        blk_debug_buttons.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="NSEW")
        blk_debug_buttons.columnconfigure([0, 1], weight=1, minsize=100)

        self.checkboxvar['Debug Overlay'] = tk.BooleanVar()
        cb_debug_overlay = ttk.Checkbutton(blk_debug_buttons, text='Debug Overlay', variable=self.checkboxvar['Debug Overlay'], command=(lambda field='Debug Overlay': self.check_cb(field)))
        cb_debug_overlay.grid(row=6, column=0, padx=2, pady=2, columnspan=2, sticky="NSEW")
        self._tip(cb_debug_overlay, self.tooltips['Debug Overlay'])

        self.checkboxvar['Debug OCR'] = tk.BooleanVar()
        cb_debug_ocr = ttk.Checkbutton(blk_debug_buttons, text="Debug OCR - Writes OCR output to 'ocr-output' folder", variable=self.checkboxvar['Debug OCR'], command=(lambda field='Debug OCR': self.check_cb(field)))
        cb_debug_ocr.grid(row=7, column=0, padx=2, pady=2, columnspan=2, sticky="NSEW")
        self._tip(cb_debug_ocr, self.tooltips['Debug OCR'])

        self.checkboxvar['Debug Images'] = tk.BooleanVar()
        cb_debug_images = ttk.Checkbutton(blk_debug_buttons, text="Debug Images - Writes debug images to 'debug-output' folder", variable=self.checkboxvar['Debug Images'], command=(lambda field='Debug Images': self.check_cb(field)))
        cb_debug_images.grid(row=8, column=0, padx=2, pady=2, columnspan=2, sticky="NSEW")
        self._tip(cb_debug_images, self.tooltips['Debug Images'])

        # === Status Bar ===
        statusbar = ttk.Frame(win)
        statusbar.grid(row=4, column=0, sticky="EW", padx=10, pady=(0, 6))
        self.status = ttk.Label(statusbar, text="Status: Idle", relief=tk.SUNKEN, anchor=tk.W, justify=tk.LEFT,
                                width=29)
        self.jumpcount = ttk.Label(statusbar, text="<info> ", relief=tk.SUNKEN, anchor=tk.W, justify=tk.LEFT,
                                   width=40)
        self.status.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.jumpcount.pack(side=tk.RIGHT, fill=tk.Y, expand=False)

        return mylist

    def restart_program(self):
        logger.debug("Entered: restart_program")
        print("restart now")

        self.stop_fsd()
        self.stop_sc()
        self.ed_ap.quit()
        sleep(0.1)

        import sys
        print("argv was", sys.argv)
        print("sys.executable was", sys.executable)
        print("restart now")

        import os
        os.execv(sys.executable, ['python'] + sys.argv)


def apply_theme_to_titlebar(root):
    version = sys.getwindowsversion()

    if version.major == 10 and version.build >= 22000:
        # Set the title bar color to the background color on Windows 11 for better appearance
        pywinstyles.change_header_color(root, "#1c1c1c" if sv_ttk.get_theme() == "dark" else "#fafafa")
    elif version.major == 10:
        pywinstyles.apply_style(root, "dark" if sv_ttk.get_theme() == "dark" else "normal")

        # A hacky way to update the title bar's color on Windows 10 (it doesn't update instantly like on Windows 11)
        root.wm_attributes("-alpha", 0.99)
        root.wm_attributes("-alpha", 1)


def _enable_crash_logging():
    """ Hard crashes (e.g. inside OCR/native libraries) end the process without a Python traceback in
    autopilot.log. faulthandler writes the stack of all threads to crash.log in that case, and uncaught
    Tk callback errors are logged instead of only printed to the console. """
    import faulthandler
    import traceback
    from datetime import datetime
    try:
        f = open('crash.log', 'a', encoding='utf-8')
        f.write(f"\n===== EDAP started {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        globals()['_crash_log_file'] = f  # keep the file open
    except Exception as e:
        logger.warning(f"Could not enable crash logging: {e}")

    def _tk_error(exc, val, tb):
        logger.error("GUI callback error: " + "".join(traceback.format_exception(exc, val, tb)))
    tk.Tk.report_callback_exception = lambda self, exc, val, tb: _tk_error(exc, val, tb)

    def _excepthook(exc, val, tb):
        logger.error("Uncaught exception: " + "".join(traceback.format_exception(exc, val, tb)))
        sys.__excepthook__(exc, val, tb)
    sys.excepthook = _excepthook


def main():
    _enable_crash_logging()
    #   handle = win32gui.FindWindow(0, "Elite - Dangerous (CLIENT)")
    #   if handle != None:
    #       win32gui.SetForegroundWindow(handle)  # put the window in foreground

    root = tk.Tk()
    app = APGui(root)

    sv_ttk.set_theme("dark")

    # Remove focus outline from tabs by setting focuscolor to the background color
    style = ttk.Style()
    bg_color = "#1c1c1c" if sv_ttk.get_theme() == "dark" else "#fafafa"
    style.configure("TNotebook.Tab", focuscolor=bg_color)

    # if sys.platform == "win32":
    #     apply_theme_to_titlebar(root)

    root.mainloop()


if __name__ == "__main__":
    main()
