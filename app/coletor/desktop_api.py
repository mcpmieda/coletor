"""Desktop bridge for narrowly scoped non-secret local settings."""
from .local_settings import LocalSettings, ScheduleConflict, default_settings
from .service import PreviewApi
from .desktop_state import DesktopState
from .manual_session import ManualSession, SessionError
from .institutional_access import InstitutionalAccess, AccessDenied
from .device_provider import DeviceProvider
from .frequency_runtime import FrequencyRuntime
from .protected_storage import StorageError
from functools import wraps


class DesktopApi(PreviewApi):
    def __init__(self, settings_directory=None, access=None):
        self._settings = LocalSettings(settings_directory)
        self._desktop_state = DesktopState(self._read_settings()["settings"]["fox"])
        self._tray = None
        self._manual_session = ManualSession(settings_directory=settings_directory)
        self._provider = getattr(access, '_provider', None) if access else DeviceProvider(settings_directory)
        self._access = access or InstitutionalAccess(self._provider, on_locked=self._access_locked)
        self._collector = FrequencyRuntime(self._access, self._provider, self._manual_session, settings_directory,
                                           on_started=self._desktop_state.begin_read,
                                           on_finished=self._desktop_state.end_read)

    def _access_locked(self):
        # Connectivity loss cancels operational work, but is not a revocation
        # receipt. Retain only the consented encrypted reconciliation queue.
        self._collector.cancel(purge=self._access._locked_code != 'ACCESS_UNAVAILABLE')

    def _operational(self, work):
        try: return work()
        except (AccessDenied, StorageError) as error:
            return {'error': 'Não foi possível concluir. Confira o estado do coletor e a conexão.', 'code': error.code}
        except Exception:
            return {'error': 'Não foi possível concluir. Confira o estado do coletor e a conexão.', 'code': 'unavailable'}

    def get_collector_status(self):
        return self._operational(self._collector.refresh)

    def activate_collector(self):
        return self._operational(self._collector.activate)

    def collect_now(self):
        return self._operational(self._collector.collect)

    def pause_collector(self, paused):
        return self._operational(lambda: self._collector.local_pause(paused))

    def save_shared_schedule(self, revision, schedule):
        return self._operational(lambda: self._collector.save_settings(revision, schedule))

    def pause_school_collection(self, revision, paused):
        return self._operational(lambda: self._collector.school_pause(revision, paused))

    def discard_pending_collection(self):
        return self._operational(self._collector.discard_queue)

    def get_institutional_access_status(self):
        return self._access.status()

    def open_institutional_login(self):
        try:
            self._access.open_login()
            return {"ok": True}
        except AccessDenied as error:
            return {"error": str(error), "code": error.code}

    def logout_institutional_access(self):
        try:
            self._access.logout()
            self._collector.cancel(purge=True)
            self._manual_session.close()
            return {"ok": True}
        except AccessDenied as error:
            return {"error": str(error), "code": error.code}
        except Exception:
            return {"error": "Não foi possível concluir a limpeza da sessão.", "code": "ACCESS_CLEANUP_PENDING"}

    def prepare_manual_login(self, year):
        if self._collector.public_status()['active']: self._collector.local_pause(True)
        return self._manual(lambda: self._manual_session.prepare_login(year))

    def get_manual_class_selection_preferences(self):
        saved = self._manual_session._selections.read()
        return {"last_year": saved["selection"]["scope"]["year"] if saved["selection"] else None,
                "revalidation_required": True, "notice": saved["notice"]}

    def discover_manual_classes(self, generation, confirmed):
        result = self._manual(lambda: self._manual_session.discover(generation, confirmed))
        if 'catalog' in result: self._collector.source_ready()
        return result

    def save_manual_class_selection(self, generation, ids, revision):
        return self._manual(lambda: self._manual_session.save_choices(generation, ids, revision))

    def clear_manual_class_selection(self, generation, revision):
        return self._manual(lambda: self._manual_session.save_choices(generation, [], revision, clear=True))

    def capture_selected_class(self, generation, class_id, confirmed):
        return self._reading(lambda: self._manual(lambda: self._manual_session.capture_selected(generation, class_id, confirmed)))

    def _manual(self, work):
        if self._collector._operation.locked():
            return {'error': 'Há uma coleta em andamento. Aguarde terminar ou pause neste computador antes de alterar a sessão.'}
        try:
            return work()
        except SessionError as error:
            return {"error": str(error)}
        except (OSError, ValueError, TypeError):
            return {"error": "Confira a etapa, a turma e o ano. Se a sessão não responder, feche-a e prepare novamente."}

    def open_manual_session(self, generation, confirmed):
        return self._manual(lambda: self._manual_session.open(generation, confirmed))

    def close_manual_session(self):
        if self._collector.public_status()['active']:
            # Pausing collection closes its source session. The desktop caller
            # expects ManualStatus, never a frequency CollectorStatus.
            result = self._operational(lambda: self._collector.local_pause(True))
            if 'error' in result:
                return result
            return self._manual_session.status()
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
                "automatic_collection": self._collector.public_status()['active']}

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
        return self._read_settings()

    def _read_settings(self):
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


def _protected(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return self._access.run(lambda: method(self, *args, **kwargs))
        except AccessDenied as error:
            return {"error": str(error), "code": error.code}
    return guarded


# Authentication is enforced by Python for every protected command, independently
# of visibility or state in the webview. Login/status/logout and safe cleanup remain public.
for _name in ("prepare_manual_login", "get_manual_class_selection_preferences", "discover_manual_classes",
              "save_manual_class_selection", "clear_manual_class_selection", "capture_selected_class",
              "open_manual_session", "get_manual_session_status", "load_demo", "preview_html",
              "get_desktop_status", "hide_window", "set_tray_context", "get_local_settings",
              "save_schedule", "save_theme", "save_fox"):
    setattr(DesktopApi, _name, _protected(getattr(DesktopApi, _name)))

for _name in ('get_collector_status', 'activate_collector', 'collect_now', 'pause_collector',
              'save_shared_schedule', 'pause_school_collection', 'discard_pending_collection'):
    setattr(DesktopApi, _name, _protected(getattr(DesktopApi, _name)))

