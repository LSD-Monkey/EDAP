from __future__ import annotations

import json
from os import environ, listdir
import os
from os.path import getmtime, isfile, join
from time import sleep, monotonic
import random
from typing import Any, final
from xml.etree.ElementTree import parse

import win32gui
import xmltodict

from Screen import set_focus_elite_window
from directinput import *
from EDlogger import logger

"""
Description:  Pulls the keybindings for specific controls from the ED Key Bindings file, this class also
  has method for sending a key to the display that has focus (so must have ED with focus)

Constraints:  This file will use the latest modified *.binds file
"""


@final
class EDKeys:

    def __init__(self, cb):
        self.ap_ckb = cb
        self.key_mod_delay = 0.01  # Delay for key modifiers to ensure modifier is detected before/after the key
        self.key_def_hold_time = 0.2  # Default hold time for a key press
        self.key_repeat_delay = 0.1  # Delay between key press repeats
        self.activate_window = False
        self.pause_when_unfocused = True  # Pause (not stop) key input while Elite is not the foreground window
        self.randomness = False  # Vary default hold times and delays between keys (EnableRandomness)

        self.keys_to_obtain = [
            'YawLeftButton',
            'YawRightButton',
            'RollLeftButton',
            'RollRightButton',
            'PitchUpButton',
            'PitchDownButton',
            'SetSpeedZero',
            'SetSpeed50',
            'SetSpeed100',
            'HyperSuperCombination',
            'SelectTarget',
            'DeployHeatSink',
            'UIFocus',
            'UI_Up',
            'UI_Down',
            'UI_Left',
            'UI_Right',
            'UI_Select',
            'UI_Back',
            'CycleNextPanel',
            'HeadLookReset',
            'PrimaryFire',
            'SecondaryFire',
            'ExplorationFSSEnter',
            'ExplorationFSSQuit',
            'MouseReset',
            'DeployHardpointToggle',
            'IncreaseEnginesPower',
            'IncreaseWeaponsPower',
            'IncreaseSystemsPower',
            'ResetPowerDistribution',
            'GalaxyMapOpen',
            'CamZoomIn',  # Gal map zoom in
            'SystemMapOpen',
            'UseBoostJuice',
            'Supercruise',
            'UpThrustButton',
            'LandingGearToggle',
            'TargetNextRouteSystem',  # Target next system in route
            'CamTranslateForward',
            'CamTranslateRight',
            'OrderAggressiveBehaviour',
            'FocusLeftPanel',  # Opens the left (Nav) panel directly (alternative to UIFocus + UI_Left)
        ]
        self.keys = self.get_bindings()
        self.bindings = self.get_bindings_dict()

        self.missing_keys = []
        # We want to log the keyboard name instead of just the key number so we build a reverse dictionary
        # so we can look up the name also
        self.reversed_dict = {value: key for key, value in SCANCODE.items()}

        # dump config to log
        for key in self.keys_to_obtain:
            try:
                # lookup the keyname in the SCANCODE reverse dictionary and output that key name
                keyname = self.reversed_dict.get(self.keys[key]['key'], "Key not found")
                keymod = " "
                # if key modifier, then look up that modifier name also
                if len(self.keys[key]['mods']) != 0:
                    keymod = self.reversed_dict.get(self.keys[key]['mods'][0], " ")

                logger.info('\tget_bindings_<{}>={} Key: <{}> Mod: <{}>'.format(key, self.keys[key], keyname, keymod))
                if key not in self.keys:
                    self.ap_ckb('log',
                                f"WARNING: \tget_bindings_<{key}>= does not have a valid keyboard keybind {keyname}.")
                    logger.warning(
                        "\tget_bindings_<{}>= does not have a valid keyboard keybind {}".format(key, keyname).upper())
                    self.missing_keys.append(key)
            except Exception as e:
                self.ap_ckb('log', f"WARNING: \tget_bindings_<{key}>= does not have a valid keyboard keybind.")
                logger.warning("\tget_bindings_<{}>= does not have a valid keyboard keybind.".format(key).upper())
                self.missing_keys.append(key)

        # Check if the hotkeys are used in ED
        binding_name = self.check_hotkey_in_bindings('Key_End')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_End' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

        binding_name = self.check_hotkey_in_bindings('Key_Insert')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_Insert' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

        binding_name = self.check_hotkey_in_bindings('Key_PageUp')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_PageUp' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

        binding_name = self.check_hotkey_in_bindings('Key_Home')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_Home' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

    def get_bindings(self) -> dict[str, Any]:
        """Returns a dict struct with the direct input equivalent of the necessary elite keybindings"""
        direct_input_keys = {}
        latest_bindings = self.get_latest_keybinds()
        if not latest_bindings:
            return {}
        bindings_tree = parse(latest_bindings)
        bindings_root = bindings_tree.getroot()

        for item in bindings_root:
            if item.tag in self.keys_to_obtain:
                key = None
                mods = []
                hold = None
                # Check primary
                if item[0].attrib['Device'].strip() == "Keyboard":
                    key = item[0].attrib['Key']
                    for modifier in item[0]:
                        if modifier.tag == "Modifier":
                            mods.append(modifier.attrib['Key'])
                        elif modifier.tag == "Hold":
                            hold = True
                # Check secondary (and prefer secondary)
                if item[1].attrib['Device'].strip() == "Keyboard":
                    key = item[1].attrib['Key']
                    mods = []
                    hold = None
                    for modifier in item[1]:
                        if modifier.tag == "Modifier":
                            mods.append(modifier.attrib['Key'])
                        elif modifier.tag == "Hold":
                            hold = True
                # Prepare final binding
                binding: None | dict[str, Any] = None
                try:
                    if key is not None:
                        binding = {}
                        binding['key'] = SCANCODE[key]
                        binding['mods'] = []
                        for mod in mods:
                            binding['mods'].append(SCANCODE[mod])
                        if hold is not None:
                            binding['hold'] = True
                except KeyError as e:
                    # Unknown key name (e.g. a layout specific key). Do not store a half-filled binding, it would
                    # look like a valid binding and fail later with KeyError 'key'.
                    logger.warning(f"Unrecognised key {e} for bind '{item.tag}' - binding ignored.")
                    self.ap_ckb('log', f"WARNING: Key {e} used for '{item.tag}' is not supported by EDAP. "
                                       f"Please bind '{item.tag}' to another key.")
                    binding = None
                if binding is not None:
                    direct_input_keys[item.tag] = binding

        if len(list(direct_input_keys.keys())) < 1:
            return {}
        else:
            return direct_input_keys

    def get_primary_scancode(self, key_binding: str):
        """ Scancode of the PRIMARY keyboard key of a bind (EDAP normally uses the secondary one).
        Example: UI_Down primary = S, secondary = Down Arrow. Returns None if there is none. """
        try:
            latest_bindings = self.get_latest_keybinds()
            if not latest_bindings:
                return None
            for item in parse(latest_bindings).getroot():
                if item.tag == key_binding and item[0].attrib.get('Device', '').strip() == "Keyboard":
                    return SCANCODE.get(item[0].attrib.get('Key'))
        except Exception as e:
            logger.warning(f"get_primary_scancode({key_binding}): {e}")
        return None

    def tap_scancode(self, scancode: int, hold: float = 0.15):
        """ Press and release a raw scancode (waits for the Elite window focus like send()). """
        if not self.activate_window:
            self.wait_for_focus()
        PressKey(scancode)
        try:
            sleep(hold)
        finally:
            ReleaseKey(scancode)
        sleep(self.key_repeat_delay)

    def get_bindings_dict(self) -> dict[str, Any]:
        """Returns a dict of all the elite keybindings.
        @return: A dictionary of the keybinds file.
        Example:
        {
        'Root': {
            'YawLeftButton': {
                'Primary': {
                    '@Device': 'Keyboard',
                    '@Key': 'Key_A'
                },
                'Secondary': {
                    '@Device': '{NoDevice}',
                    '@Key': ''
                }
            }
        }
        }
        """
        latest_bindings = self.get_latest_keybinds()
        if not latest_bindings:
            return {}

        try:
            with open(latest_bindings, 'r') as file:
                my_xml = file.read()
                my_dict = xmltodict.parse(my_xml)
                return my_dict

        except OSError as e:
            logger.error(f"OS Error reading Elite Dangerous bindings file: {latest_bindings}.")
            raise Exception(f"OS Error reading Elite Dangerous bindings file: {latest_bindings}.")

    def check_hotkey_in_bindings(self, key_name: str) -> str:
        """ Check for the action keys. """
        ret = []
        for key, value in self.bindings['Root'].items():
            if type(value) is dict:
                primary = value.get('Primary', None)
                if primary is not None:
                    if primary['@Key'] == key_name:
                        ret.append(f"{key} (Primary)")
                secondary = value.get('Secondary', None)
                if secondary is not None:
                    if secondary['@Key'] == key_name:
                        ret.append(f"{key} (Secondary)")
        return " and ".join(ret)

    # Note:  this routine will grab the *.binds file which is the latest modified
    def get_latest_keybinds(self):
        path_bindings = environ['LOCALAPPDATA'] + "\Frontier Developments\Elite Dangerous\Options\Bindings"
        try:
            list_of_bindings = [join(path_bindings, f) for f in listdir(path_bindings) if
                                isfile(join(path_bindings, f)) and f.endswith('.binds')]
        except FileNotFoundError as e:
            return None

        if not list_of_bindings:
            return None
        latest_bindings = max(list_of_bindings, key=getmtime)
        logger.info(f'Latest keybindings file:{latest_bindings}')
        return latest_bindings

    ELITE_WINDOW_TITLE = "Elite - Dangerous (CLIENT)"

    def elite_has_focus(self) -> bool:
        """ True if the Elite Dangerous window is the foreground window (True if it cannot be determined). """
        try:
            return win32gui.GetWindowText(win32gui.GetForegroundWindow()) == self.ELITE_WINDOW_TITLE
        except Exception:
            return True

    def _pause_active(self) -> bool:
        """ Pausing is only used if enabled and EDAP does not bring Elite to the front by itself. """
        return self.pause_when_unfocused and not self.activate_window

    def wait_for_focus(self) -> float:
        """ Pauses (does not stop) while Elite is not the foreground window, e.g. because the user clicked into
        another window. Key presses would otherwise go to the wrong window. Returns the paused time in seconds.
        Stays interruptible, so the stop button still works while paused. """
        if not self._pause_active() or self.elite_has_focus():
            return 0.0
        start = monotonic()
        logger.info("Elite Dangerous is not the active window - key input paused.")
        self.ap_ckb('log', "Elite is not the active window - EDAP paused. Click into Elite to continue.")
        while not self.elite_has_focus():
            sleep(0.25)
        paused = monotonic() - start
        logger.info(f"Elite Dangerous active again - key input resumed after {paused:.1f} s.")
        self.ap_ckb('log', f"Elite active again - EDAP continues (paused {paused:.0f} s).")
        sleep(0.3)  # Give the game a moment after regaining focus
        return paused

    def _sleep_responsive(self, duration: float, key=None):
        """ Sleeps in small steps. A stop request is raised asynchronously into the AP thread and is only
        delivered between Python statements, so one long sleep() would delay the stop by the whole hold time.
        If 'key' (a held key) is given and Elite loses focus, the key is released, the hold time is paused until
        Elite has focus again, then the key is pressed again for the remaining time. """
        remaining = duration
        last = monotonic()
        while remaining > 0:
            sleep(min(0.05, remaining))
            now = monotonic()
            remaining -= now - last
            last = now
            if key is not None and remaining > 0 and self._pause_active() and not self.elite_has_focus():
                ReleaseKey(key['key'])
                for mod in key['mods']:
                    ReleaseKey(mod)
                self.wait_for_focus()
                for mod in key['mods']:
                    PressKey(mod)
                    sleep(self.key_mod_delay)
                PressKey(key['key'])
                last = monotonic()

    def has_binding(self, key_binding: str) -> bool:
        """ Returns True if the given ED binding has a usable keyboard key. """
        return self.keys.get(key_binding) is not None

    def send_key(self, type, key):
        # Focus Elite window if configured
        if self.activate_window:
            set_focus_elite_window()
            sleep(0.05)

        if type == 'Up':
            ReleaseKey(key)
        else:
            PressKey(key)

    def send(self, key_binding, hold=None, repeat=1, repeat_delay=None, state=None):
        """ Send a key based on the defined keybind
        @param key_binding: The key bind name (i.e. UseBoostJuice).
        @param hold: The time to hold the key down in seconds.
        @param repeat: Number of times to repeat the key.
        @param repeat_delay: Time delay in seconds between repeats. If None, uses the default repeat delay.
        @param state: Key state:
            None - press and release (default).
            1 - press (but don't release).
            0 - release (a previous press state).
        """
        key = self.keys.get(key_binding)
        if key is None:
            logger.warning('SEND=NONE !!!!!!!!')
            self.ap_ckb('log', f"WARNING: Unable to retrieve keybinding for {key_binding}.")
            raise Exception(
                f"Unable to retrieve keybinding for {key_binding}. Advise user to check game settings for keyboard bindings.")

        key_name = self.reversed_dict.get(key['key'], "Key not found")
        logger.debug('\tsend=' + key_binding + ',key:' + str(key) + ',key_name:' + key_name + ',hold:' + str(
            hold) + ',repeat:' + str(
            repeat) + ',repeat_delay:' + str(repeat_delay) + ',state:' + str(state))

        for i in range(repeat):
            # Focus Elite window if configured.
            if self.activate_window:
                set_focus_elite_window()
                sleep(0.05)
            elif state is None or state == 1:
                # Pause while Elite is not the active window (never pause a pure release).
                self.wait_for_focus()

            if state is None or state == 1:
                for mod in key['mods']:
                    PressKey(mod)
                    sleep(self.key_mod_delay)

                PressKey(key['key'])

            try:
                if state is None:
                    if hold:
                        if hold > 0.0:
                            self._sleep_responsive(hold, key)
                    else:
                        if self.key_def_hold_time > 0.0:
                            if self.randomness:
                                sleep(self.key_def_hold_time * random.uniform(0.75, 1.5))
                            else:
                                sleep(self.key_def_hold_time)

                if 'hold' in key:
                    sleep(0.1)
            finally:
                # Always release, also when a stop request (EDAP_Interrupt) arrives while the key is held.
                # Otherwise the key would stay pressed in the game.
                if state is None or state == 0:
                    ReleaseKey(key['key'])

                    for mod in key['mods']:
                        sleep(self.key_mod_delay)
                        ReleaseKey(mod)

            if repeat_delay:
                sleep(repeat_delay)
            else:
                sleep(self.key_repeat_delay)
            if self.randomness:
                # Small, uneven gap between key presses (calibrated rotation holds are not changed)
                sleep(random.uniform(0.0, 0.08))

    def release_all_keys(self):
        """Release all modifier keys and any currently tracked key presses to prevent stuck keys.
        Called on stop/interrupt to ensure no keys remain held down."""
        modifier_scancodes = [
            SCANCODE.get("Key_LeftShift"),
            SCANCODE.get("Key_RightShift"),
            SCANCODE.get("Key_LeftControl"),
            SCANCODE.get("Key_RightControl"),
            SCANCODE.get("Key_LeftAlt"),
            SCANCODE.get("Key_RightAlt"),
        ]
        for sc in modifier_scancodes:
            if sc is not None:
                ReleaseKey(sc)

        for binding in self.keys.values():
            ReleaseKey(binding['key'])
            for mod in binding['mods']:
                ReleaseKey(mod)

    def get_collisions(self, key_name: str) -> list[str]:
        """ Get key name collisions (keys used for more than one binding).
        @param key_name: The key name (i.e. UI_Up, UI_Down).
        """
        key = self.keys.get(key_name)
        collisions = []
        for k, v in self.keys.items():
            if key == v:
                collisions.append(k)
        return collisions
