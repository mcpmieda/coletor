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
        self.assertEqual(len(shortcuts), 2)  # Start menu and desktop; sign-in uses the logon task.
        self.assertNotIn("{userstartup}\\Coletor de Frequência\";", icons)
        for line in shortcuts:
            self.assertIn(f'AppUserModelID: "{app_id}"', line)
            self.assertIn('fox-idle.ico', line)

    def test_the_app_is_called_coletor_and_the_old_shortcuts_go(self):
        # Owner request 05/11/2026: the name shown is just "Coletor"; the AppId and folder stay.
        script = (ROOT / "installer/Coletor.iss").read_text(encoding="utf-8-sig")
        self.assertIn('#define AppName "Coletor"', script)
        self.assertIn("AppId={{D2471FE4-968A-4E83-AC4C-5A85CC8E651B}", script)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\ColetorFrequenciaSmecel", script)
        removed = script.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
        for place in ("{autoprograms}", "{autodesktop}", "{userstartup}"):
            self.assertIn(f'Type: files; Name: "{place}\\Coletor de Frequência.lnk"', removed)
        icons = script.split("[Icons]", 1)[1].split("\n[", 1)[0]
        self.assertIn('Name: "{autoprograms}\\Coletor";', icons)


if __name__ == "__main__":
    unittest.main()
