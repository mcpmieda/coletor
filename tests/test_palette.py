"""Brand palette contrast checks against authored CSS, without a browser."""
from pathlib import Path
import re
import unittest

CSS = (Path(__file__).resolve().parents[1] / 'ui/src/index.css').read_text()

def contrast(a, b):
    def luminance(value):
        rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        rgb = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
        return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722
    x, y = luminance(a), luminance(b)
    return (max(x, y) + .05) / (min(x, y) + .05)

class PaletteTests(unittest.TestCase):
    def check_palette(self, theme, accent):
        block = re.search(r"\[data-theme='" + theme + r"'\] \{([^}]+)", CSS)[1]
        tokens = dict(re.findall(r'--([a-z-]+): (#[0-9a-f]{6});', block))
        self.assertEqual(tokens['accent'], accent)
        for surface in ('background', 'surface', 'surface-secondary', 'app-sidebar'):
            self.assertGreaterEqual(contrast(tokens['foreground'], tokens[surface]), 4.5)
            self.assertGreaterEqual(contrast(tokens['muted'], tokens[surface]), 4.5)
            self.assertGreaterEqual(contrast(tokens['focus'], tokens[surface]), 3)
        self.assertGreaterEqual(contrast(tokens['accent-foreground'], tokens['accent']), 4.5)

    def test_light_palette(self):
        self.check_palette('light', '#a32743')

    def test_dark_palette(self):
        self.check_palette('dark', '#f28ba0')

    def test_presence_keeps_semantic_green(self):
        self.assertIn('.state-present { color: #217346; }', CSS)
        self.assertIn('.dark .state-present { color: #7ed7a5; }', CSS)

    def test_errors_have_non_color_shape(self):
        self.assertIn('border-left: 3px solid currentColor', CSS)
