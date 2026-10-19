"""
Unit tests for the in-game Supercruise Assist (SCA) support.
These tests do NOT need Elite Dangerous to be running, all game interaction is mocked.

Run: python -m unittest test_SCAssist.py
"""
import sys
import types
import unittest
from unittest import mock


def _stub_missing(name: str, **attrs):
    """ Insert a stub module if the real one is not importable (e.g. pywin32 on non-Windows CI). """
    try:
        __import__(name)
    except Exception:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod


# On Windows with the requirements installed nothing is stubbed. On other systems (e.g. CI) the Windows-only
# modules are replaced by empty stubs, which is fine as the tests never call into them.
for _name in ("win32con", "win32gui", "mss", "kthread", "pyttsx3"):
    _stub_missing(_name)
if sys.platform != "win32":
    _stub_missing_windows = types.ModuleType("WindowsKnownPaths")
    sys.modules.setdefault("WindowsKnownPaths", _stub_missing_windows)

navmod = None
try:
    import EDNavigationPanel as navmod
    from EDNavigationPanel import (EDNavigationPanel, destination_names_match, normalize_destination_name)
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - environment specific
    IMPORT_ERROR = e


def _no_sleep():
    """ Patch the module level sleep() of EDNavigationPanel. """
    return mock.patch.object(navmod, "sleep", lambda *_: None)


class FakeKeys:
    """ Records all key sends. """
    def __init__(self, bound=None):
        self.sent = []
        self.bound = set(bound or [])

    def send(self, key_binding, hold=None, repeat=1, repeat_delay=None, state=None):
        for _ in range(repeat):
            self.sent.append(key_binding if state is None else f"{key_binding}:{state}")

    def has_binding(self, key_binding):
        return key_binding in self.bound


@unittest.skipIf(IMPORT_ERROR is not None, f"EDNavigationPanel not importable: {IMPORT_ERROR}")
class DestinationNameTestCase(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_destination_name("Jaques Station"), "JAQUES STATION")
        self.assertEqual(normalize_destination_name(" PAX  GALACITICA H7G-G6G "), "PAX GALACITICA H7G G6G")
        self.assertEqual(normalize_destination_name(None), "")

    def test_exact_and_case(self):
        self.assertTrue(destination_names_match("Jaques Station", "JAQUES STATION"))

    def test_partial_name(self):
        self.assertTrue(destination_names_match("Jaques Station", "Jaques"))
        self.assertFalse(destination_names_match("Jaques Station", "Ja"))  # too short

    def test_ocr_like_difference(self):
        # Nav Panel OCR vs Status.json spelling
        self.assertTrue(destination_names_match("PAX GALACITICA H7G-G6G", "PAX GALACTICA H7G-G6G"))

    def test_different(self):
        self.assertFalse(destination_names_match("Jaques Station", "Colonia Orbital"))
        self.assertFalse(destination_names_match("", "Colonia Orbital"))


@unittest.skipIf(IMPORT_ERROR is not None, f"EDNavigationPanel not importable: {IMPORT_ERROR}")
class ActivateSupercruiseAssistTestCase(unittest.TestCase):
    def _panel(self, status_names):
        """ Build a nav panel without running __init__ (no screen/OCR needed). """
        pnl = EDNavigationPanel.__new__(EDNavigationPanel)
        pnl.keys = FakeKeys()
        names = iter(status_names)
        last = {"name": ""}

        def get_cleaned_data():
            try:
                last["name"] = next(names)
            except StopIteration:
                pass
            return {"Destination_Name": last["name"]}

        pnl.status_parser = mock.Mock()
        pnl.status_parser.get_cleaned_data.side_effect = get_cleaned_data
        pnl.show_navigation_tab = mock.Mock(return_value=True)
        pnl.find_destination_in_list = mock.Mock(return_value=True)
        pnl.hide_panel = mock.Mock()
        return pnl

    def test_key_sequence_and_verification(self):
        pnl = self._panel(["", "", "Jaques Station"])
        with _no_sleep():
            ok = pnl.activate_supercruise_assist("Jaques Station")
        self.assertTrue(ok)
        # Details view -> SUPERCRUISE ASSIST (2nd button) -> select
        self.assertEqual(pnl.keys.sent, ["UI_Select", "UI_Right", "UI_Select"])
        pnl.find_destination_in_list.assert_called_once_with("Jaques Station")
        pnl.hide_panel.assert_called()

    def test_not_in_list(self):
        pnl = self._panel([""])
        pnl.find_destination_in_list.return_value = False
        with _no_sleep():
            self.assertFalse(pnl.activate_supercruise_assist("Nowhere"))
        self.assertEqual(pnl.keys.sent, ["UI_Back"])  # back to the list and one retry, nothing selected
        self.assertEqual(pnl.find_destination_in_list.call_count, 2)
        pnl.hide_panel.assert_called()

    def test_destination_not_confirmed(self):
        pnl = self._panel(["Colonia Orbital"])
        with _no_sleep(), mock.patch.object(navmod.time, "time", side_effect=[0.0, 0.0, 10.0, 10.0, 10.0]):
            self.assertFalse(pnl.activate_supercruise_assist("Jaques Station"))
        pnl.hide_panel.assert_called()


@unittest.skipIf(IMPORT_ERROR is not None, f"EDNavigationPanel not importable: {IMPORT_ERROR}")
class ShowPanelTestCase(unittest.TestCase):
    def test_uses_focus_left_panel_when_bound(self):
        pnl = EDNavigationPanel.__new__(EDNavigationPanel)
        pnl.keys = FakeKeys(bound=["FocusLeftPanel"])  # UIFocus/HeadLookReset not bound
        pnl.ap = mock.Mock()
        pnl.screen = mock.Mock()
        pnl.is_panel_active = mock.Mock(side_effect=[(False, ""), (True, "NAVIGATION")])
        with _no_sleep(), mock.patch.object(navmod.cv2, "imwrite"):
            active, tab = pnl.show_panel()
        self.assertTrue(active)
        self.assertEqual(pnl.keys.sent, ["FocusLeftPanel"])

    def test_falls_back_to_uifocus(self):
        pnl = EDNavigationPanel.__new__(EDNavigationPanel)
        pnl.keys = FakeKeys(bound=["UIFocus", "HeadLookReset"])
        pnl.ap = mock.Mock()
        pnl.screen = mock.Mock()
        pnl.is_panel_active = mock.Mock(side_effect=[(False, ""), (True, "NAVIGATION")])
        with _no_sleep(), mock.patch.object(navmod.cv2, "imwrite"):
            pnl.show_panel()
        self.assertEqual(pnl.keys.sent, ["HeadLookReset", "UIFocus:1", "UI_Left", "UIFocus:0"])


if __name__ == '__main__':
    unittest.main()
