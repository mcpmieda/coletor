"""Desktop bridge for narrowly scoped non-secret local settings."""
from .local_settings import LocalSettings, ScheduleConflict, default_settings
from .service import PreviewApi
from .desktop_state import DesktopState
from .manual_session import ManualSession, SessionError


class DesktopApi(PreviewApi):
    def __init__(self, settings_directory=None):
        self._settings = LocalSettings(settings_directory)
        self._desktop_state = DesktopState(self.get_local_settings()["settings"]["fox"])
        self._tray = None
        self._manual_session = ManualSession()

    def _manual(self, work):
        try:
            return work()
        except SessionError as error:
            return {"error": str(error)}
        except (OSError, ValueError, TypeError):
            return {"error": "Confira a etapa, a turma e o ano. Se a sessão não responder, feche-a e prepare novamente."}

    def prepare_manual_session(self, class_id, year):
        return self._manual(lambda: self._manual_session.prepare(class_id, year))

    def open_manual_session(self, generation, confirmed):
        return self._manual(lambda: self._manual_session.open(generation, confirmed))

    def capture_manual_preview(self, generation, confirmed):
        return self._reading(lambda: self._manual(lambda: self._manual_session.capture(generation, confirmed)))

    def close_manual_session(self):
        return self._manual(self._manual_session.close)

    def get_manual_session_status(self):
        return self._manual_session.status()

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
        except ScheduleConflict:
            return {"error": "Os horários foram alterados em outra janela. Recarregue os horários salvos e compare antes de salvar novamente.", "code": "SCHEDULE_REVISION_CONFLICT"}
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

