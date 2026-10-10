"""Desktop bridge for narrowly scoped non-secret local settings."""
from .local_settings import LocalSettings, default_settings
from .service import PreviewApi
from .desktop_state import DesktopState


class DesktopApi(PreviewApi):
    def __init__(self, settings_directory=None):
        self._settings = LocalSettings(settings_directory)
        self._desktop_state = DesktopState(self.get_local_settings()["settings"]["fox"])
        self._tray = None

    def _reading(self, work):
        self._desktop_state.begin_read()
        failed = True
        try:
            result = work()
            failed = "error" in result
            return result
        finally:
            self._desktop_state.end_read(failed)

    def load_demo(self):
        return self._reading(super().load_demo)

    def preview_html(self, html, class_id, year):
        return self._reading(lambda: super(DesktopApi, self).preview_html(html, class_id, year))

    def get_desktop_status(self):
        return {"tray_available": self._tray is not None and self._tray.available(),
                "automatic_collection": False}

    def hide_window(self):
        if self._tray is None:
            return {"error": "A bandeja não está disponível. A janela continua aberta."}
        return self._tray.hide()

    def set_tray_context(self, activity, reduced_motion):
        try:
            self._desktop_state.set_context(activity, reduced_motion)
            return {"ok": True}
        except (ValueError, TypeError):
            return {"error": "Estado local inválido."}

    def get_local_settings(self):
        try:
            return self._settings.read()
        except OSError:
            return {"settings": default_settings(),
                    "notice": "Não foi possível carregar as configurações. Você pode ajustar nesta sessão."}

    def _save(self, field, value):
        try:
            return {"settings": self._settings.update(field, value)}
        except (OSError, ValueError, TypeError, RecursionError):
            return {"error": "Não foi possível salvar neste computador. Suas alterações continuam na tela."}

    def save_schedule(self, schedule):
        return self._save("schedule", schedule)

    def save_theme(self, theme):
        return self._save("theme", theme)

    def save_fox(self, fox):
        result = self._save("fox", fox)
        if "settings" in result: self._desktop_state.set_fox(result["settings"]["fox"])
        return result

