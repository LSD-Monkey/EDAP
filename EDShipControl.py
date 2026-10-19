from __future__ import annotations

from typing import TypedDict

from EDAP_data import *
from RPYLineEditor import convert_curve_to_float, convert_curve_to_str, closest_angle
from Screen import set_focus_elite_window
from StatusParser import StatusParser
from time import sleep
import time
from EDlogger import logger


def scale(inp: float, in_min: float, in_max: float, out_min: float, out_max: float, clamp: bool) -> float:
    """ Does scaling of the input based on input and output min/max.
    @param inp: The input, typically with the range in_min to in_max, but can extend outside.
    @param in_min: The min input value.
    @param in_max: The max input value.
    @param out_min: The min output value.
    @param out_max: The max output value.
    @param clamp: Clamp the output to out_min and out_max.
    @return: The calculated input interpolated or extrapolated by the given ranges.
    """
    x = (inp - in_min) / (in_max - in_min) * (out_max - out_min) + out_min
    if clamp:
        return max(min(x, out_max), out_min)
    else:
        return x


class CompassTargetOffset(TypedDict):
    """
    Dictionary containing navigation (compass) and/or Target information.
    """
    roll: float
    pit: float
    yaw: float
    tar_occ: bool
    tar_behind: bool
    used_nav: bool
    used_tar: bool


class ThrottleDemand(TypedDict):
    """
    Dictionary containing target information.
    """
    RollRate: dict[str, float]
    PitchRate: dict[str, float]
    YawRate: dict[str, float]


class EDShipControl:
    """ Handles ship control, FSD, SC, etc. """

    def __init__(self, ed_ap, screen, keys, cb):
        self.ap = ed_ap
        self.ocr = ed_ap.ocr
        self.screen = screen
        self.keys = keys
        self.ap_ckb = cb
        self.status_parser = StatusParser()

    # Max. time a single roll/pitch/yaw key is held. Ships need ~2-10 s for large angles, longer holds are
    # the result of wrong (too low) rate values and would block EDAP for minutes.
    MAX_HOLD_TIME = 15.0

    def _limit_hold_time(self, htime: float, axis: str) -> float:
        """ Limits the key hold time for one movement. """
        if htime > self.MAX_HOLD_TIME:
            self.ap_ckb('log', f"{axis}: calculated hold time {htime:.1f} s is too long, limited to "
                               f"{self.MAX_HOLD_TIME:.0f} s. Check the ship's {axis} rates (calibration).")
            return self.MAX_HOLD_TIME
        return htime

    # Plausible rotation rates in deg/s (all ships). Values outside are measuring errors (compass front/back
    # ambiguity at large angles, key press not reaching the game) or the result of extrapolating bad points.
    RATE_LIMITS = {'Roll': (1.0, 200.0), 'Pitch': (0.5, 90.0), 'Yaw': (0.3, 60.0)}

    def _rate_ok(self, rate: float, axis: str) -> bool:
        lo, hi = self.RATE_LIMITS[axis]
        return lo <= rate <= hi

    def _htime(self, abs_deg: float, rate: float, axis: str) -> float:
        """ Hold time for abs_deg with a rate from the curve. Implausible rates (e.g. 1440 deg/s from a corrupted
        auto-tune curve) are clamped, otherwise the key is only tapped for 0.1 s and the ship never turns. """
        lo, hi = self.RATE_LIMITS[axis]
        if not (lo <= rate <= hi):
            clamped = min(max(rate, lo), hi)
            self.ap_ckb('log', f"{axis}: implausible rate {rate:.2f} deg/s from the ship curve, using {clamped:.1f}.")
            rate = clamped
        return abs_deg / rate

    def _tune_plausible(self, act_ang: float, demand_ang: float, axis: str) -> bool:
        """ Auto-tune sanity check. If the ship moved less than 10 % of the demanded angle, the key press most
        likely did not reach the game (window focus, admin rights, wrong binding). Learning a rate from that would
        poison the ship config with tiny rates and very long hold times. """
        if demand_ang > 2.0 and act_ang < 0.1 * demand_ang:
            self.ap_ckb('log', f"Auto-tune: ship moved only {act_ang:.1f} of {demand_ang:.1f} deg ({axis}). "
                               f"Not learning this value. Are the key presses reaching Elite (focus/admin rights)?")
            return False
        return True

    AUTOSAVE_INTERVAL = 20.0  # seconds between automatic saves of learned (auto-tune) curves

    def _add_to_curve(self, axis: str, curve_key: str, angle: float, rate: float):
        """ Adds/updates a point of the current RPY curve (auto-tune).
        - Implausible points are ignored (compass front/back ambiguity at large angles, key not reaching the game).
        - An existing point is blended 50/50 with the new measurement instead of being overwritten, so one bad
          measurement can not ruin the curve and the values converge over several movements.
        - The ship config is saved automatically (at most every AUTOSAVE_INTERVAL s). """
        if angle > 100.0 or not self._rate_ok(rate, axis):
            logger.debug(f"Auto-tune: ignored {axis} point {angle:.1f} deg, {rate:.2f} deg/s (implausible).")
            return
        throttle = self.get_throttle_demand_dict()
        if not throttle:
            return
        c = convert_curve_to_float(throttle[curve_key])
        a = closest_angle(angle)
        old = c.get(a)
        new = rate if old is None else 0.5 * old + 0.5 * rate
        c[a] = round(new, 2)
        throttle[curve_key] = convert_curve_to_str(c)  # conversion sorts the points
        if old is None:
            self.ap_ckb('log', f'Added a point to the {self.ap.speed_demand} {axis} curve at {a} deg, '
                               f'{round(new, 2)} deg/s.')
        else:
            self.ap_ckb('log', f'Updated the {self.ap.speed_demand} {axis} curve at {a} deg: '
                               f'{round(old, 2)} -> {round(new, 2)} deg/s (measured {round(rate, 2)}).')
        self._autosave_curves()

    def _autosave_curves(self):
        """ Saves the learned curves to configs/ship_configs.json (throttled). Before, learned values were only
        kept in memory and lost on restart unless 'Save All Settings' was clicked. """
        now = time.time()
        if now - getattr(self, '_last_autosave', 0.0) < self.AUTOSAVE_INTERVAL:
            return
        self._last_autosave = now
        try:
            self.ap.update_ship_configs()
            logger.debug("Auto-tune: ship configuration saved.")
        except Exception as e:
            logger.warning(f"Auto-tune: could not save the ship configuration: {e}")

    def _settled_offset(self, axis_key: str, min_wait: float, auto_tune: bool):
        """ Reads the compass/target offset after a movement. With auto-tune the reading is repeated until the
        ship has stopped turning: heavy ships (Type-9, Cutter, ...) keep rotating for a while after the key is
        released. Measuring too early made the learned rate too low, every following correction too long and the
        ship oscillated around the target (e.g. yaw +6/-6 deg for a minute). """
        sleep(min_wait)
        off = self.ap.get_compass_target_offset()
        if not auto_tune or not off:
            return off
        t0 = time.time()
        while time.time() - t0 < 3.0:
            sleep(0.25)
            off2 = self.ap.get_compass_target_offset()
            if not off2:
                break
            if abs(off2[axis_key] - off[axis_key]) < 0.3:
                return off2
            off = off2
        return off

    def add_to_roll_curve(self, angle: float, rate: float):
        """ Add/update a point of the roll curve of the current ship (deg, deg/s). """
        self._add_to_curve('Roll', 'RollRate', angle, rate)

    def add_to_pitch_curve(self, angle: float, rate: float):
        """ Add/update a point of the pitch curve of the current ship (deg, deg/s). """
        self._add_to_curve('Pitch', 'PitchRate', angle, rate)

    def add_to_yaw_curve(self, angle: float, rate: float):
        """ Add/update a point of the yaw curve of the current ship (deg, deg/s). """
        self._add_to_curve('Yaw', 'YawRate', angle, rate)

    def get_throttle_demand_dict(self) -> ThrottleDemand | None:
        """
        Gets the current RPY tuning curve for the current ship. Or None if neither are valid.
        @return: The ThrottleDemand dict containing the RPY curves:
            {   'RollRate': dict[str, float],
                'PitchRate': dict[str, float],
                'YawRate': dict[str, float] }
        """
        # Check if a ship config loaded
        if self.ap.current_ship_cfg:
            # Check the throttle demand is in the ship config
            if self.ap.speed_demand in self.ap.current_ship_cfg:
                # Select the throttle demand
                throttle_demand = self.ap.current_ship_cfg[self.ap.speed_demand]
                return throttle_demand

        return None

    def goto_cockpit_view(self) -> bool:
        """ Goto cockpit view.
        @return: True once complete.
        """
        if self.status_parser.get_gui_focus() == GuiFocusNoFocus:
            return True

        # Go down to cockpit view
        while not self.status_parser.get_gui_focus() == GuiFocusNoFocus:
            self.keys.send("UI_Back")  # make sure back in cockpit view

        return True

    def roll_clockwise_anticlockwise(self, deg: float, auto_tune: bool = False, cur_deg: float = 0.0) -> (
            CompassTargetOffset | None):
        """ Roll in deg. (> 0.0 for roll right, < 0.0 for roll left)
        @param deg: The angle to turn in degrees
        @param auto_tune: Enable auto-tuning of ship
        @param cur_deg: Our current angle used for tuning
        @return: N/A.
        """
        close = 8.0
        abs_deg = abs(deg)
        htime = abs_deg / self.ap.rollrate

        if self.ap.speed_demand is None:
            self.ap.set_throttle_50()

        if self.ap.current_ship_cfg:
            # Roll rate from ship config
            if self.ap.speed_demand in self.ap.current_ship_cfg:
                speed_demand = self.ap.current_ship_cfg[self.ap.speed_demand]
                if 'RollRate' in speed_demand:
                    last_deg = 0.0
                    last_val = 0.0
                    last_deg1 = 0.0
                    last_val1 = 0.0
                    for key, value in speed_demand['RollRate'].items():
                        key_deg = float(key)
                        if last_val == 0.0:
                            # We want to clamp at the min recorded value because interpolating starting at 0.0 will
                            # produce a large rate which will cause oscillation.
                            last_val = value
                            last_val1 = value

                        if abs_deg <= key_deg:
                            # Interpolate based on the last value and this value
                            ratio_val = scale(abs_deg, last_deg, key_deg, last_val, value, False)
                            self.ap_ckb('log',
                                        f"Roll demand: {round(deg, 1)}. Interp value: {round(ratio_val, 2)} deg/s")

                            htime = self._htime(abs_deg, ratio_val, 'Roll')

                            last_deg1 = last_deg
                            last_val1 = last_val
                            last_deg = key_deg
                            last_val = value
                            break
                        else:
                            last_deg1 = last_deg
                            last_val1 = last_val
                            last_deg = key_deg
                            last_val = value

                    # Check if found one curve point and we are off the scale
                    if abs_deg > last_deg and last_val > 0.0:
                        # Extrapolate based on the last value and the value before this value
                        ratio_val = scale(abs_deg, last_deg1, last_deg, last_val1, last_val, False)
                        self.ap_ckb('log', f"Roll demand: {round(deg, 1)}. Extrap value: {round(ratio_val, 2)} deg/s")

                        htime = self._htime(abs_deg, ratio_val, 'Roll')

        # Check if we are rolling right or left and perform the movement.
        htime = self._limit_hold_time(htime, 'Roll')
        if deg > 0.0:
            self.keys.send('RollRightButton', hold=htime)
        else:
            self.keys.send('RollLeftButton', hold=htime)

        # Calculate error
        # Calc the position we want to achieve
        sp = cur_deg - deg
        # Wait for ship to stabilize. Calc the delay from the angle 0 - 45 deg = 0.1 - 0.75 Sec. 45 deg is where the
        # rate no longer increases.
        dly = scale(abs_deg, 0.0, 45.0, 0.5, 1.0, True)

        # Take current reading (with auto-tune: after the ship has stopped turning)
        off = self._settled_offset('roll', dly, auto_tune)
        if off:
            # Are we still too far away?
            err = sp - off['roll']
            if abs(err) > close:
                # Add angle and time to curve
                act_ang = abs(cur_deg - off['roll'])
                rate = act_ang / htime
                if auto_tune and not self._tune_plausible(act_ang, abs_deg, 'roll'):
                    pass  # Ship (almost) did not move, do not learn a wrong rate
                elif auto_tune:
                    # Add a new point for the detected rate
                    self.add_to_roll_curve(act_ang, rate)
                    # Update the existing point as well
                    self.add_to_roll_curve(abs_deg, rate)
                else:
                    c_ang = closest_angle(act_ang)
                    # self.ap_ckb('log', f"Roll Tuning suggestion - Add {c_ang} deg with {round(rate, 2)} deg/s rate")

        # Return compass/target data or None
        return off

    def pitch_up_down(self, deg: float, auto_tune: bool = False, cur_deg: float = 0.0) -> CompassTargetOffset | None:
        """ Pitch in deg. (> 0.0 for pitch up, < 0.0 for pitch down)
        @param deg: The angle to turn in degrees
        @param auto_tune: Enable auto-tuning of ship
        @param cur_deg: Our current angle used for tuning
        @return: N/A.
        """
        close = 0.5
        abs_deg = abs(deg)
        htime = abs_deg / self.ap.pitchrate

        if self.ap.speed_demand is None:
            self.ap.set_throttle_50()

        if self.ap.current_ship_cfg:
            # Pitch rate from ship config
            if self.ap.speed_demand in self.ap.current_ship_cfg:
                speed_demand = self.ap.current_ship_cfg[self.ap.speed_demand]
                if 'PitchRate' in speed_demand:
                    last_deg = 0.0
                    last_val = 0.0
                    last_deg1 = 0.0
                    last_val1 = 0.0
                    for key, value in speed_demand['PitchRate'].items():
                        key_deg = float(key)
                        if last_val == 0.0:
                            # We want to clamp at the min recorded value because interpolating starting at 0.0 will
                            # produce a large rate which will cause oscillation.
                            last_val = value
                            last_val1 = value

                        if abs_deg <= key_deg:
                            # Interpolate based on the last value and this value
                            ratio_val = scale(abs_deg, last_deg, key_deg, last_val, value, False)
                            self.ap_ckb('log',
                                        f"Pitch demand: {round(deg, 1)}. Interp value: {round(ratio_val, 2)} deg/s")

                            htime = self._htime(abs_deg, ratio_val, 'Pitch')

                            last_deg1 = last_deg
                            last_val1 = last_val
                            last_deg = key_deg
                            last_val = value
                            break
                        else:
                            last_deg1 = last_deg
                            last_val1 = last_val
                            last_deg = key_deg
                            last_val = value

                    # Check if found one curve point and we are off the scale
                    if abs_deg > last_deg and last_val > 0.0:
                        # Extrapolate based on the last value and the value before this value
                        ratio_val = scale(abs_deg, last_deg1, last_deg, last_val1, last_val, False)
                        self.ap_ckb('log', f"Pitch demand: {round(deg, 1)}. Extrap value: {round(ratio_val, 2)} deg/s")

                        htime = self._htime(abs_deg, ratio_val, 'Pitch')

        # Check if we are pitching up or down and perform the movement.
        htime = self._limit_hold_time(htime, 'Pitch')
        if deg > 0.0:
            self.keys.send('PitchUpButton', hold=htime)
        else:
            self.keys.send('PitchDownButton', hold=htime)

        # Calculate error
        # Calc the position we want to achieve
        sp = cur_deg - deg
        # Wait for ship to stabilize. Calc the delay from the angle 0 - 30 deg = 0.1 - 0.5 Sec. 30 deg is where the
        # rate no longer increases.
        dly = scale(abs_deg, 0.0, 30.0, 0.5, 0.75, True)

        # Take current reading (with auto-tune: after the ship has stopped turning)
        off = self._settled_offset('pit', dly, auto_tune)
        if off:
            # Are we still too far away?
            err = sp - off['pit']
            if abs(err) > close:
                # Add angle and time to curve
                act_ang = abs(cur_deg - off['pit'])
                rate = act_ang / htime
                if auto_tune and not self._tune_plausible(act_ang, abs_deg, 'pit'):
                    pass  # Ship (almost) did not move, do not learn a wrong rate
                elif auto_tune:
                    # Add a new point for the detected rate
                    self.add_to_pitch_curve(act_ang, rate)
                    # Update the existing point as well
                    self.add_to_pitch_curve(abs_deg, rate)
                else:
                    c_ang = closest_angle(act_ang)
                    # self.ap_ckb('log', f"Pitch Tuning suggestion - Add {c_ang} deg with {round(rate, 2)} deg/s rate")

        # Return compass/target data or None
        return off

    def yaw_right_left(self, deg: float, auto_tune: bool = False, cur_deg: float = 0.0) -> CompassTargetOffset | None:
        """ Yaw in deg. (> 0.0 for yaw right, < 0.0 for yaw left)
        @param deg: The angle to turn in degrees
        @param auto_tune: Enable auto-tuning of ship
        @param cur_deg: Our current angle used for tuning
        @return: N/A.
        """
        close = 0.5
        abs_deg = abs(deg)
        htime = abs_deg / self.ap.yawrate

        if self.ap.speed_demand is None:
            self.ap.set_throttle_50()

        if self.ap.current_ship_cfg:
            # Yaw rate from ship config
            if self.ap.speed_demand in self.ap.current_ship_cfg:
                speed_demand = self.ap.current_ship_cfg[self.ap.speed_demand]
                if 'YawRate' in speed_demand:
                    last_deg = 0.0
                    last_val = 0.0
                    last_deg1 = 0.0
                    last_val1 = 0.0
                    for key, value in speed_demand['YawRate'].items():
                        key_deg = float(key)
                        if last_val == 0.0:
                            # We want to clamp at the min recorded value because interpolating starting at 0.0 will
                            # produce a large rate which will cause oscillation.
                            last_val = value
                            last_val1 = value

                        if abs_deg <= key_deg:
                            # Interpolate based on the last value and this value
                            ratio_val = scale(abs_deg, last_deg, key_deg, last_val, value, False)
                            self.ap_ckb('log',
                                        f"Yaw demand: {round(deg, 1)}. Interp value: {round(ratio_val, 2)} deg/s")

                            htime = self._htime(abs_deg, ratio_val, 'Yaw')

                            last_deg1 = last_deg
                            last_val1 = last_val
                            last_deg = key_deg
                            last_val = value
                            break
                        else:
                            last_deg1 = last_deg
                            last_val1 = last_val
                            last_deg = key_deg
                            last_val = value

                    # Check if found one curve point and we are off the scale
                    if abs_deg > last_deg and last_val > 0.0:
                        # Extrapolate based on the last value and the value before this value
                        ratio_val = scale(abs_deg, last_deg1, last_deg, last_val1, last_val, False)
                        self.ap_ckb('log', f"Yaw demand: {round(deg, 1)}. Extrap value: {round(ratio_val, 2)} deg/s")

                        htime = self._htime(abs_deg, ratio_val, 'Yaw')

        # Check if we are yawing right or left and perform the movement.
        htime = self._limit_hold_time(htime, 'Yaw')
        if deg > 0.0:
            self.keys.send('YawRightButton', hold=htime)
        else:
            self.keys.send('YawLeftButton', hold=htime)

        # Calculate error
        # Auto-tune if necessary
        # Calc the position we want to achieve
        sp = cur_deg - deg
        # Wait for ship to stabilize. Calc the delay from the angle 0 - 30 deg = 0.1 - 0.4 Sec. 30 deg is where the
        # rate no longer increases.
        dly = scale(abs_deg, 0.0, 30.0, 0.5, 0.75, True)

        # Take current reading (with auto-tune: after the ship has stopped turning)
        off = self._settled_offset('yaw', dly, auto_tune)
        if off:
            # Are we still too far away?
            err = sp - off['yaw']
            if abs(err) > close:
                # Add angle and time to curve
                act_ang = abs(cur_deg - off['yaw'])
                rate = act_ang / htime
                if auto_tune and not self._tune_plausible(act_ang, abs_deg, 'yaw'):
                    pass  # Ship (almost) did not move, do not learn a wrong rate
                elif auto_tune:
                    # Add a new point for the detected rate
                    self.add_to_yaw_curve(act_ang, rate)
                    # Update the existing point as well
                    self.add_to_yaw_curve(abs_deg, rate)
                else:
                    c_ang = closest_angle(act_ang)
                    # self.ap_ckb('log', f"Yaw Tuning suggestion - Add {c_ang} deg with {round(rate, 2)} deg/s rate")

        # Return compass/target data or None
        return off

    def ship_calibrate_roll(self):
        """ Performs ship roll tuning by pitching 360 degrees.
        If the ship does not rotate enough, decrease the roll value.
        If the ship rotates too much, increase the roll value.
        """
        self.ap_ckb('log', "Starting Roll Tuning.")

        if not self.ap.speed_demand or self.ap.speed_demand == '':
            self.ap_ckb('log', "WARNING: Set speed before tuning.")
            return

        if not self.ap.current_ship_cfg:
            return

        if self.ap.speed_demand not in self.ap.current_ship_cfg:
            self.ap.current_ship_cfg[self.ap.speed_demand] = dict()

        # Clear existing data
        self.ap.current_ship_cfg[self.ap.speed_demand]['RollRate'] = dict()

        test_time = 0.05
        delta = 0.0
        for targ_ang in [2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0, 55.0, 89.0, 144.0]:
            while 1:
                set_focus_elite_window()
                off = self.ap.get_compass_target_offset()
                if not off:
                    break

                # Clear the overlays before moving
                if self.ap.debug_overlay:
                    self.ap.overlay.overlay_remove_rect('compass')
                    self.ap.overlay.overlay_remove_floating_text('compass')
                    self.ap.overlay.overlay_remove_floating_text('nav')
                    self.ap.overlay.overlay_remove_floating_text('nav_beh')
                    self.ap.overlay.overlay_remove_floating_text('compass_rpy')
                    self.ap.overlay.overlay_paint()

                if off['roll'] > 0:
                    self.keys.send('RollRightButton', hold=test_time)
                else:
                    self.keys.send('RollLeftButton', hold=test_time)

                sleep(1)

                off2 = self.ap.get_compass_target_offset()
                if not off2:
                    break

                delta_lst = delta
                delta = round(abs(off2['roll'] - off['roll']), 1)

                test_time = test_time * 1.04
                rate = round(delta / test_time, 2)
                if delta >= targ_ang and delta > delta_lst:
                    self.ap.current_ship_cfg[self.ap.speed_demand]['RollRate'][str(delta)] = rate

                    print(f"Roll Angle: {round(delta, 1)}: Time: {round(test_time, 2)} Rate: {rate}")
                    self.ap_ckb('log', f"Roll Angle: {round(delta, 1)}: Time: {round(test_time, 2)} Rate: {rate}")
                    break
                else:
                    print(f"Ignored Roll Angle: {round(delta, 1)}: Time: {round(test_time, 2)} Rate: {rate}")

        self.ap_ckb('log', "Completed Roll Tuning. Remember to Save.")

    def ship_calibrate_pitch(self):
        """ Performs a ship pitch tuning by pitching 360 degrees.
        If the ship does not rotate enough, decrease the pitch value.
        If the ship rotates too much, increase the pitch value.
        """
        self.ap_ckb('log', "Starting Pitch Tuning.")

        if not self.ap.speed_demand or self.ap.speed_demand == '':
            self.ap_ckb('log', "WARNING: Set speed before tuning.")
            return

        if not self.ap.current_ship_cfg:
            return

        if self.ap.speed_demand not in self.ap.current_ship_cfg:
            self.ap.current_ship_cfg[self.ap.speed_demand] = dict()

        # Clear existing data
        self.ap.current_ship_cfg[self.ap.speed_demand]['PitchRate'] = dict()

        test_time = 0.05
        delta = 0.0
        for targ_ang in [0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 16.0, 32.0, 60.0, 90.0, 120.0]:
            while 1:
                set_focus_elite_window()
                off = self.ap.get_compass_target_offset()
                if not off:
                    print(f"Target lost")
                    break

                # Clear the overlays before moving
                if self.ap.debug_overlay:
                    self.ap.overlay.overlay_remove_rect('target')
                    self.ap.overlay.overlay_remove_floating_text('target')
                    self.ap.overlay.overlay_remove_floating_text('target_occ')
                    self.ap.overlay.overlay_remove_floating_text('target_rpy')
                    self.ap.overlay.overlay_paint()

                if off['pit'] > 0:
                    self.keys.send('PitchUpButton', hold=test_time)
                else:
                    self.keys.send('PitchDownButton', hold=test_time)

                sleep(1)

                off2 = self.ap.get_compass_target_offset()
                if not off2:
                    print(f"Target lost")
                    break

                delta_lst = delta
                delta = round(abs(off2['pit'] - off['pit']), 1)

                test_time = test_time * 1.04
                rate = round(delta / test_time, 2)
                if delta >= targ_ang and delta > delta_lst:
                    self.ap.current_ship_cfg[self.ap.speed_demand]['PitchRate'][str(delta)] = rate

                    print(f"Pitch Angle: {delta}: Time: {round(test_time, 2)} Rate: {rate}")
                    self.ap_ckb('log', f"Pitch Angle: {delta}: Time: {round(test_time, 2)} Rate: {rate}")
                    break
                else:
                    print(f"Ignored Pitch Angle: {delta}: Time: {round(test_time, 2)} Rate: {rate}")

        self.ap_ckb('log', "Completed Pitch Tuning. Remember to Save.")

    def ship_calibrate_yaw(self):
        """ Performs a ship yaw tuning by pitching 360 degrees.
        If the ship does not rotate enough, decrease the yaw value.
        If the ship rotates too much, increase the yaw value.
        """
        self.ap_ckb('log', "Starting Yaw Tuning.")

        if not self.ap.speed_demand or self.ap.speed_demand == '':
            self.ap_ckb('log', "WARNING: Set speed before tuning.")
            return

        if not self.ap.current_ship_cfg:
            return

        if self.ap.speed_demand not in self.ap.current_ship_cfg:
            self.ap.current_ship_cfg[self.ap.speed_demand] = dict()

        # Clear existing data
        self.ap.current_ship_cfg[self.ap.speed_demand]['YawRate'] = dict()

        test_time = 0.07
        delta = 0.0
        for targ_ang in [0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 16.0, 32.0, 60.0, 90.0, 120.0]:
            while 1:
                set_focus_elite_window()
                off = self.ap.get_compass_target_offset()
                if not off:
                    break

                # Clear the overlays before moving
                if self.ap.debug_overlay:
                    self.ap.overlay.overlay_remove_rect('target')
                    self.ap.overlay.overlay_remove_floating_text('target')
                    self.ap.overlay.overlay_remove_floating_text('target_occ')
                    self.ap.overlay.overlay_remove_floating_text('target_rpy')
                    self.ap.overlay.overlay_paint()

                if off['yaw'] > 0:
                    self.keys.send('YawRightButton', hold=test_time)
                else:
                    self.keys.send('YawLeftButton', hold=test_time)

                sleep(1)

                off2 = self.ap.get_compass_target_offset()
                if not off2:
                    break

                delta_lst = delta
                delta = round(abs(off2['yaw'] - off['yaw']), 1)

                test_time = test_time * 1.05
                rate = round(delta / test_time, 2)
                if delta >= targ_ang and delta > delta_lst:
                    self.ap.current_ship_cfg[self.ap.speed_demand]['YawRate'][str(delta)] = rate

                    print(f"Yaw Angle: {delta}: Time: {round(test_time, 2)} Rate: {rate}")
                    self.ap_ckb('log', f"Yaw Angle: {delta}: Time: {round(test_time, 2)} Rate: {rate}")
                    break
                else:
                    print(f"Ignored Yaw Angle: {delta}: Time: {round(test_time, 2)} Rate: {rate}")

        self.ap_ckb('log', "Completed Yaw Tuning. Remember to Save.")

    def ship_tst_roll(self, angle: float):
        """ Performs a ship roll test by pitching 360 degrees.
        If the ship does not rotate enough, decrease the roll value.
        If the ship rotates too much, increase the roll value.
        @param angle: The angle to move in degrees.
        @return: N/A
        """
        # if not self.ap.status.get_flag(FlagsSupercruise):
        #     self.ap_ckb('log', "Enter Supercruise and try again.")
        #     return
        #
        # if self.ap.jn.ship_state()['target'] is None:
        #     self.ap_ckb('log', "Select a target system and try again.")
        #     return

        set_focus_elite_window()
        sleep(0.25)
        # self.ap.set_speed_50()
        self.roll_clockwise_anticlockwise(angle)

    def ship_tst_pitch(self, angle: float):
        """ Performs a ship pitch test by pitching 360 degrees.
        If the ship does not rotate enough, decrease the pitch value.
        If the ship rotates too much, increase the pitch value.
        @param angle: The angle to move in degrees.
        @return: N/A
        """
        # if not self.ap.status.get_flag(FlagsSupercruise):
        #     self.ap_ckb('log', "Enter Supercruise and try again.")
        #     return
        #
        # if self.ap.jn.ship_state()['target'] is None:
        #     self.ap_ckb('log', "Select a target system and try again.")
        #     return

        set_focus_elite_window()
        sleep(0.25)
        # self.ap.set_speed_50()
        self.pitch_up_down(angle)

    def ship_tst_yaw(self, angle: float):
        """ Performs a ship yaw test by pitching 360 degrees.
        If the ship does not rotate enough, decrease the yaw value.
        If the ship rotates too much, increase the yaw value.
        @param angle: The angle to move in degrees.
        @return: N/A
        """
        # if not self.ap.status.get_flag(FlagsSupercruise):
        #     self.ap_ckb('log', "Enter Supercruise and try again.")
        #     return
        #
        # if self.ap.jn.ship_state()['target'] is None:
        #     self.ap_ckb('log', "Select a target system and try again.")
        #     return

        set_focus_elite_window()
        sleep(0.25)
        # self.ap.set_speed_50()
        self.yaw_right_left(angle)


def main():
    pass


if __name__ == "__main__":
    main()
