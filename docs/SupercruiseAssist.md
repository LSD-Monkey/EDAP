# Supercruise Assist

EDAP uses the game's own **Supercruise Assist (SCA)** module when it is fitted to the ship. EDAP only selects the
destination, aligns, activates the SCA and then monitors; the game does the flying and the drop.

## Flow
0. Destination: the station name from the waypoint, otherwise the **current in-game destination** from
   `Status.json` (`Destination.Name`). Select it in the Galaxy/System Map or Nav Panel before pressing *SC Assist*.
1. Leave the station/planet if docked or landed, enter supercruise and set **throttle 0**.
2. Activate the in-game SCA: Nav Panel > **NAVIGATION** > find the entry (OCR) > `UI_Select` opens the details view,
   which has the same buttons for all destination types (stations, carriers, bodies, signal sources):

   ```
   [ LOCK DESTINATION ] [ SUPERCRUISE ASSIST ]
                  BACK
   ```
   `UI_Right` > `UI_Select` activates **SUPERCRUISE ASSIST**. This also locks the destination, which is verified via
   `Status.json` (0.5-1 s delay).
3. Align to the destination with the compass while standing still (throttle 0). Can be disabled (`SCAssistAlign`).
4. Hands off. The in-game SCA flies to the destination and drops out of supercruise. The HUD shows
   **SUPERCRUISE ASSIST ACTIVE** (blue triangle above the canopy). EDAP sends no flight keys and does **not** press
   disengage itself. EDAP monitors:
   * `SupercruiseDestinationDrop` + normal space: arrived, continue with docking.
   * Interdiction: submit, escape, then steps 1-3 again.
   * Dropped elsewhere, destination changed by the player, or timeout: throttle 0 and stop.
   * Optional OCR check of the *SUPERCRUISE ASSIST ACTIVE* text. If it was seen and disappears while still in
     supercruise, the SCA is re-activated (max. 3 activations). If it is never seen (e.g. region not calibrated),
     the check is switched off and a hint is logged; EDAP never re-activates blindly.
5. Docking (as before): request docking via the Nav Panel CONTACTS tab, docking computer, refuel/repair.

If the ship has **no SCA module**, or the destination cannot be found in the Nav Panel, EDAP falls back to its own
(compass/target image based) SC Assist (`sc_assist_manual`).

## Required key bindings
* Nav Panel: `FocusLeftPanel` (default `1`) **or** `UIFocus` (+ `UI_Left`). `FocusLeftPanel` is preferred.
* `UI_Up`, `UI_Down`, `UI_Left`, `UI_Right`, `UI_Select`, `UI_Back`, `CycleNextPanel`.
* For the alignment and docking: `PitchUpButton`, `PitchDownButton`, `YawLeftButton`, `YawRightButton`,
  `RollLeftButton`, `RollRightButton`, `SetSpeedZero`, `SetSpeed50`, `SetSpeed100`.

## Settings (`configs/AP.json`)
| Key | Default | Description |
|---|---|---|
| `SCAssistTimeout` | `3600` | Max. seconds to reach the destination (0 = no limit). |
| `SCAssistAlign` | `true` | Align to the destination with the compass (throttle 0) after activating the SCA. |
| `SCAssistCheckActiveOCR` | `true` | Check the HUD for *SUPERCRUISE ASSIST ACTIVE* (English locale only, `SC_ASSIST_ACTIVE_MSG`). |

## Calibration
The screen region `Screen_Regions.full_panel.subregion.sca_active` (top center of the HUD) is added to
`configs/ocr_calibration.json` automatically and can be adjusted on the Calibration tab like the other regions.
