"""The taskbar shows the fox only when shortcuts carry the process's AppUserModelID."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


class InstallerShortcutTests(unittest.TestCase):
    def test_every_app_shortcut_carries_the_window_app_user_model_id(self):
        # Windows 11 groups taskbar buttons by AUMID and draws the icon of the
        # shortcut with that ID; without it the pythonw.exe icon is shown.
        source = (ROOT / "app/coletor/desktop.py").read_text(encoding="utf-8")
        app_id = re.search(r'^APP_USER_MODEL_ID = "([^"]+)"', source, re.M).group(1)
        script = (ROOT / "installer/Coletor.iss").read_text(encoding="utf-8-sig")
        icons = script.split("[Icons]", 1)[1].split("\n[", 1)[0]
        shortcuts = [line for line in icons.splitlines() if 'ColetorFrequencia.exe' in line]
        self.assertEqual(len(shortcuts), 3)
        for line in shortcuts:
            self.assertIn(f'AppUserModelID: "{app_id}"', line)
            self.assertIn('fox-idle.ico', line)


if __name__ == "__main__":
    unittest.main()
