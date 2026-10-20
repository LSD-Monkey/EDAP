# Settings

The **Settings** tab shows all autopilot settings in sections. 

* **Changes are active at once.** *Save All Settings* (top) writes them to `configs/AP.json`; the button shows `*` while there are unsaved changes. Closing EDAP with unsaved changes asks to save them.
* **Search** filters the settings by name and description (e.g. `fuel`, `dock`, `timeout`).
* **●** marks a value that differs from the default, the tooltip of each setting shows its default.
* **Reset section** sets the values of one section back to the defaults.
* Settings marked *(restart)* are used after a restart of EDAP.
* *Load All Settings* reloads `AP.json` and the ship configs from disk.

The ship related settings (SunPitchUp time, roll/pitch/yaw auto-tune, rate curves, throttle and align test buttons) are on the **Ship** tab.

## General

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Voice output | `VoiceEnable` | `False` | EDAP speaks its status messages (Windows text to speech). |
| Pause keys while Elite is not active | `PauseWhenUnfocused` | `True` | No key is sent while another window (e.g. EDAP, Discord) is in front. EDAP continues when you click into Elite again. Strongly recommended. |
| Stop on connection loss / main menu | `GameConnectionCheck` | `True` | Stops every assist when 'CONNECTION ERROR' is on screen, the game is in the main menu or was closed. Without it EDAP keeps pressing keys for hours after a disconnect. |
| Log out when the route is complete | `AutomaticLogout` | `False` | FSD Route Assist: log out of the game after reaching the destination. |
| Language (HUD texts) *(restart)* | `Language` | `en` | Language of the game. Used to recognise HUD texts by OCR. Needs a restart. |

## Hotkeys

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Enable global hotkeys | `HotkeysEnable` | `False` | Hotkeys also work while Elite is in front. Use keys that are not bound in Elite. |
| Stop all assists | `HotKey_StopAllAssists` | `end` | Key name as used by the python 'keyboard' package, e.g. end, home, ins, pgup, f9, ctrl+shift+s. |
| Start FSD Route Assist | `HotKey_StartFSD` | `home` | Key name, e.g. home. |
| Start Supercruise Assist | `HotKey_StartSC` | `ins` | Key name, e.g. ins. |
| Start Robigo Assist | `HotKey_StartRobigo` | `pgup` | Key name, e.g. pgup. |

The hotkey must be in the format 'ctrl+shift+a, s'. This would trigger when the user holds ctrl, shift and "a" at once, releases, and then presses "s". To represent literal commas, pluses, and spaces, use their names ('comma', 'plus', 'space'). Be sure not to use any keys you have mapped in ED. For a detailed list, refer to the [Keyboard](https://github.com/boppreh/keyboard/tree/master) module's [winkeyboard.py](https://github.com/boppreh/keyboard/blob/master/keyboard/_winkeyboard.py) file.

## Waypoint Assist

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Auto-restarts after an error | `WaypointAutoRestarts` | `3` | Waypoint Assist restarts itself this often in a row after an error (e.g. alignment failed). The counter is reset after 20 minutes without error. 0 = never restart. Range 0 - 20. |
| Wait before restart / retry (s) | `WaypointRestartDelay` | `10` | Seconds to wait before an auto-restart or a new attempt to reach a station. Range 0 - 300. |
| Attempts to reach a station | `WaypointStationRetries` | `3` | Waypoint Assist stops after this many failed attempts in a row to reach a station. Range 1 - 20. |
| Check fuel for the route | `FuelRouteCheck` | `True` | Ships without fuel scoop: before jumping, the fuel for the plotted route is estimated from your last jumps (same ship, similar cargo). Stops if it is not enough, warns if it will be tight. |

## Supercruise Assist

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Align to the target after activating | `SCAssistAlign` | `True` | Points the ship to the destination with the compass before the in-game SCA flies. Afterwards the throttle is set to 50 %. |
| Check 'SUPERCRUISE ASSIST ACTIVE' | `SCAssistCheckActiveOCR` | `True` | Reads the HUD text to see if the SCA is still active and re-activates it if not. |
| Fallback: EDAP steers itself | `SCAssistFallbackManual` | `False` | If the in-game SCA cannot be activated, EDAP steers to the target itself (old method, needs a good RPY tuning). |
| No progress after (s) | `SCAssistStallTime` | `60` | If the distance to the target does not change for this long: 1st align + 50 % throttle, 2nd re-activate the SCA, 3rd give up. 0 = off. Range 0 - 600. |
| Line of sight escape (s) | `SCAssistNoLOSEscapeTime` | `20` | Target behind a planet ('MOVE TO OBTAIN LINE OF SIGHT'): pitch up 90° and fly this long, then re-activate the SCA. Range 5 - 120. |
| Max. (re-)activations | `SCAssistMaxActivations` | `5` | How often the SCA is (re-)activated for one destination before giving up. Range 1 - 20. |
| Timeout (s) | `SCAssistTimeout` | `3600` | Max. time to reach the destination. 0 = no limit. Range 0 - 14400. |

## Docking & Departure

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Approach before docking request (s) | `DockApproachTime` | `20` | After the drop: seconds at 100 % throttle towards the station before docking is requested (then 50 %). Range 0 - 120. |
| Docking request attempts | `DockingRetries` | `30` | How often docking is requested (at least 8 are used). Range 1 - 60. |
| Wait for auto-dock (s) | `WaitForAutoDockTimer` | `240` | After docking was granted: max. time for the docking computer to land. Range 30 - 900. |
| Fleet carrier departure (s) | `FCDepartureTime` | `5.0` | Extra time to fly away from a fleet carrier before entering supercruise. Range 0 - 60. |
| Fleet carrier pitch up (°) | `FCDepartureAngle` | `90.0` | Pitch up when leaving a fleet carrier. Range 0 - 90. |
| Construction site pitch up (°) | `OCDepartureAngle` | `90.0` | Pitch up when leaving an orbital construction site. Range 0 - 90. |

## Navigation & Jumping

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Align attempts | `NavAlignTries` | `3` | How many attempts to align to the next system before the jump. Range 1 - 20. |
| Jump attempts | `JumpTries` | `3` | How many attempts to jump. Range 1 - 20. |
| Sun brightness threshold | `SunBrightThreshold` | `125` | Brightness (0-255) above which the screen centre is seen as a star (sun avoidance). Higher = less sensitive. Range 0 - 255. |
| Galaxy map select delay (s) | `GalMap_SystemSelectDelay` | `0.5` | Wait in the galaxy map before the system is selected. Increase on slow PCs. Range 0 - 5. |

## Fuel

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Scoop below (%) | `RefuelThreshold` | `65` | With fuel scoop: refuel at a scoopable star when the tank is below this level. Range 0 - 100. |
| Scoop timeout (s) | `FuelScoopTimeOut` | `35` | Max. time to wait for a full tank while scooping. Range 5 - 300. |
| Abort route below (%) | `FuelThreasholdAbortAP` | `10` | Stops the route when the tank is below this level after a jump (only while jumps are left). Range 0 - 100. |

## Keys & Input

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Randomise timing | `EnableRandomness` | `False` | Varies key hold times, delays and adds short random pauses (so actions do not have a fixed rhythm). |
| Random pause factor | `RandomnessScale` | `1.0` | Scales the random pauses: 0.5 = half as long, 2 = twice as long. Range 0 - 5. |
| Activate Elite before each key | `ActivateEliteEachKey` | `False` | Brings the Elite window to the front before every key. Only needed if keys get lost. |
| Key hold time (s) | `Key_DefHoldTime` | `0.2` | Default time a key is held down. Range 0.01 - 1. |
| Delay between repeats (s) | `Key_RepeatDelay` | `0.1` | Pause between repeated key presses. Range 0.01 - 1. |
| Modifier key delay (s) | `Key_ModDelay` | `0.01` | Delay so a modifier (Shift, Ctrl, ...) is detected before/after the key. Range 0 - 0.5. |

## Overlay

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| Show overlay text in game | `OverlayTextEnable` | `False` | Shows the EDAP status as text over the game (experimental). |
| X offset (px) | `OverlayTextXOffset` | `50` | Distance from the left screen border. Range 0 - 8000. |
| Y offset (px) | `OverlayTextYOffset` | `400` | Distance from the top screen border. Range 0 - 8000. |
| Font size | `OverlayTextFontSize` | `14` | Font size of the overlay text. Range 6 - 72. |

## Scanner & Combat

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| ELW scanner | `ElwScannerEnable` | `False` | FSD Route Assist: FSS scan in every system, announces Earth-like, water and ammonia worlds. |
| Discovery scanner button | `DSSButton` | `Primary` | Fire button the discovery scanner (honk) is assigned to. |
| AFK combat: fighter attacks at will | `AFKCombat_AttackAtWill` | `False` | Orders the ship launched fighter to attack at will. |

## OCR

| Setting | AP.json key | Default | Description |
|---|---|---|---|
| OCR language *(restart)* | `OCRLanguage` | `en` | Language model of the text recognition. Needs a restart. |
| Fast OCR model (less accurate) *(restart)* | `OCRMobile` | `False` | Smaller and faster text recognition model, for slow PCs. Needs a restart. |
