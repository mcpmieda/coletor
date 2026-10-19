"""Tray menu drawn like the Atualizador de Planilhas' menu, in the fox's colours.

Header with the program name and a status dot, Segoe Fluent icons, a rounded
highlight on hover, separators inset from the edges and light/dark palettes.
Each item paints itself completely in its Paint event (no .NET subclassing,
which this embedded pythonnet cannot create).
"""
import winreg

PALETTES = {
    "light": {"bg": "#FFFFFF", "hover": "#F7E4E9", "text": "#302227", "muted": "#74646A", "accent": "#A32743",
              "line": "#EADDE1", "ok": "#2E7D4F", "danger": "#C42B1C"},
    "dark": {"bg": "#2A2024", "hover": "#43262F", "text": "#F4E8EC", "muted": "#C2ADB5", "accent": "#F28BA0",
             "line": "#503B44", "ok": "#5CC48A", "danger": "#FF6B5E"},
}
# Segoe Fluent Icons (Windows 11) / Segoe MDL2 Assets (Windows 10): same code points.
GLYPHS = {"open": "", "hide": "", "sync": "", "pause": "", "play": "", "power": ""}
ITEM_HEIGHT, HEADER_HEIGHT, SEPARATOR_HEIGHT, WIDTH = 36, 52, 9, 260


def windows_is_dark():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def palette(theme):
    dark = theme == "dark" or (theme == "system" and windows_is_dark())
    return PALETTES["dark" if dark else "light"]


class FoxMenu:
    """Styles a WinForms ContextMenuStrip; keep a reference while the menu lives."""

    def __init__(self, menu, theme="system"):
        from System.Drawing import Font, FontStyle
        from System.Windows.Forms import Padding, ToolStripRenderMode
        self.menu = menu
        self.set_theme(theme)
        self.fonts = {"text": Font("Segoe UI", 9.75), "title": Font("Segoe UI", 9.75, FontStyle.Bold),
                      "small": Font("Segoe UI", 8.25), "icon": Font("Segoe Fluent Icons", 11.0)}
        if self.fonts["icon"].Name != "Segoe Fluent Icons": self.fonts["icon"] = Font("Segoe MDL2 Assets", 11.0)
        # Professional base renderer: our Paint covers each item, and unlike
        # System it draws no blue selection line between items.
        menu.RenderMode = ToolStripRenderMode.Professional
        try: self.s = max(1.0, float(menu.DeviceDpi) / 96.0)
        except Exception: self.s = 1.0
        menu.ShowImageMargin = False
        menu.ShowCheckMargin = False
        menu.Padding = Padding(0, int(4 * self.s), 0, int(4 * self.s))
        menu.Paint += self._paint_border

    def add(self, item, kind, icon=""):
        """kind: header | item | danger | separator."""
        from System.Drawing import Size
        item.AutoSize = False
        height = {"header": HEADER_HEIGHT, "separator": SEPARATOR_HEIGHT}.get(kind, ITEM_HEIGHT)
        item.Size = Size(int(WIDTH * self.s), int(height * self.s))
        # Tag, not id(): pythonnet hands each event a fresh wrapper object.
        item.Tag = icon
        item.Paint += lambda sender, event, k=kind: self._paint_item(sender, event, k, str(sender.Tag or ""))
        self.menu.Items.Add(item)
        return item

    def set_theme(self, theme):
        from System.Drawing import ColorTranslator
        self.c = {k: ColorTranslator.FromHtml(v) for k, v in palette(theme).items()}
        self.menu.BackColor = self.c["bg"]

    def set_icon(self, item, icon):
        item.Tag = icon

    def dispose(self):
        """Release the fonts; call when the tray goes away."""
        for font in self.fonts.values():
            font.Dispose()
        self.fonts = {}

    @staticmethod
    def _release(*objects):
        for item in objects:
            if item is not None: item.Dispose()

    def _paint_border(self, sender, event):
        from System.Drawing import Pen, Rectangle
        pen = Pen(self.c["line"])
        try: event.Graphics.DrawRectangle(pen, Rectangle(0, 0, sender.Width - 1, sender.Height - 1))
        finally: pen.Dispose()

    def _paint_item(self, item, event, kind, icon):
        # Every GDI+ object is released at once (no reliance on finalizers):
        # the menu repaints on each hover.
        from System.Drawing import Rectangle, RectangleF, SolidBrush, StringAlignment, StringFormat
        from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode
        from System.Drawing.Text import TextRenderingHint
        g, w, h, s = event.Graphics, item.Width, item.Height, self.s
        g.SmoothingMode = SmoothingMode.AntiAlias
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit
        brushes, others = [], []
        def brush(colour):
            b = SolidBrush(colour); brushes.append(b); return b
        try:
            g.FillRectangle(brush(self.c["bg"]), Rectangle(0, 0, w, h))
            if kind == "separator":
                g.FillRectangle(brush(self.c["line"]), Rectangle(int(12 * s), h // 2, w - int(24 * s), max(1, int(s))))
                return
            if kind == "header":
                title, _, status = item.Text.partition("\n")
                ok = not status.startswith("!")
                g.DrawString(title, self.fonts["title"], brush(self.c["text"]), 14.0 * s, 8.0 * s)
                g.FillEllipse(brush(self.c["ok"] if ok else self.c["danger"]), Rectangle(int(16 * s), int(34 * s), int(7 * s), int(7 * s)))
                g.DrawString(status.lstrip("!"), self.fonts["small"], brush(self.c["muted"]), 27.0 * s, 29.0 * s)
                return
            if item.Selected and item.Enabled:
                path, r, d = GraphicsPath(), Rectangle(int(5 * s), 1, w - int(10 * s), h - 2), int(14 * s)
                others.append(path)
                path.AddArc(r.X, r.Y, d, d, 180, 90); path.AddArc(r.Right - d, r.Y, d, d, 270, 90)
                path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); path.AddArc(r.X, r.Bottom - d, d, d, 90, 90)
                path.CloseFigure()
                g.FillPath(brush(self.c["hover"]), path)
            danger = kind == "danger"
            centre = StringFormat(); centre.Alignment = StringAlignment.Center; centre.LineAlignment = StringAlignment.Center
            middle = StringFormat(); middle.LineAlignment = StringAlignment.Center
            others += [centre, middle]
            icon_colour = self.c["danger"] if danger else (self.c["accent"] if item.Enabled else self.c["muted"])
            text_colour = self.c["danger"] if danger else (self.c["text"] if item.Enabled else self.c["muted"])
            g.DrawString(GLYPHS.get(icon, ""), self.fonts["icon"], brush(icon_colour), RectangleF(10.0 * s, 0.0, 28.0 * s, float(h)), centre)
            g.DrawString(item.Text, self.fonts["text"], brush(text_colour), RectangleF(44.0 * s, 0.0, float(w) - 50.0 * s, float(h)), middle)
        finally:
            self._release(*brushes, *others)
