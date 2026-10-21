"""An update over a running Coletor: the installer asks it to quit, never interrupts a collection."""
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from coletor import desktop  # noqa: E402
from coletor.instance_lock import QUIT_EVENT, SHOW_EVENT  # noqa: E402

SCRIPT = (ROOT / "installer/Coletor.iss").read_text(encoding="utf-8-sig")


def constant(name):
    return re.search(rf"^\s*{name} = (.+);", SCRIPT, re.M).group(1)


class InstallerQuitContractTests(unittest.TestCase):
    def test_installer_signals_the_event_the_app_listens_to(self):
        self.assertEqual(constant("QuitEvent"), "'" + QUIT_EVENT + "'")
        self.assertNotEqual(QUIT_EVENT, SHOW_EVENT)

    def test_installer_waits_longer_than_the_app_waits_for_a_collection(self):
        installer = eval(constant("QuitWaitSeconds"))  # "17 * 60"
        self.assertGreater(installer, desktop.EXIT_COLLECTION_WAIT + 60)

    def test_running_collector_is_closed_before_files_and_reopened_after(self):
        self.assertIn("function PrepareToInstall(", SCRIPT)
        self.assertIn("CloseCollector(ExpandConstant('{app}'), Page)", SCRIPT)
        post = SCRIPT.split("procedure CurStepChanged", 1)[1].split("end;\n\n", 1)[0]
        self.assertIn("if CollectorWasRunning then ReopenCollector();", post)
        self.assertIn("'--background'", SCRIPT.split("procedure ReopenCollector", 1)[1])
        uninstall = SCRIPT.split("procedure CurUninstallStepChanged", 1)[1]
        self.assertIn("CloseCollector(ExpandConstant('{app}'), nil)", uninstall)
        # Only processes started from this installation folder are ever stopped.
        self.assertIn("Pos(Folder, Path) = 1", SCRIPT)
        self.assertNotIn("taskkill", SCRIPT.lower())


class Window:
    def __init__(self, closes):
        self.events = Mock()
        self.events.shown = threading.Event(); self.events.shown.set()
        self.events.closed = threading.Event()
        if closes: self.events.closed.set()
        self.destroy = Mock()


class QuitForUpdateTests(unittest.TestCase):
    def api(self, tray):
        api = Mock()
        api._tray = tray
        return api

    def test_waits_for_the_collection_then_quits_like_the_tray_menu(self):
        order = []
        tray = Mock()
        tray._invoke.side_effect = lambda action: order.append("quit")
        api = self.api(tray)
        api._collector.finish_for_exit.side_effect = lambda wait: order.append(("drain", wait))
        window = Window(closes=True)
        desktop.quit_for_update(window, api)
        self.assertEqual(order, [("drain", desktop.EXIT_COLLECTION_WAIT), "quit"])
        tray._invoke.assert_called_once_with(tray._quit)
        window.destroy.assert_not_called()

    def test_without_tray_or_if_it_does_not_close_the_window_is_destroyed(self):
        window = Window(closes=False)
        desktop.quit_for_update(window, self.api(None), wait=0)
        window.destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
