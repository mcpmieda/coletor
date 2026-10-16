"""Desktop bridge for narrowly scoped non-secret local settings."""
from .local_settings import LocalSettings, ScheduleConflict, default_settings
from .service import PreviewApi
from .desktop_state import DesktopState
from .manual_session import ManualSession, SessionError
from .institutional_access import InstitutionalAccess, AccessDenied
from .device_provider import DeviceProvider
from .frequency_runtime import FrequencyRuntime
from .protected_storage import StorageError
from .resume_store import ResumeStore
from functools import wraps
import threading
import time

# Balloon beside the clock: the window may be hidden in the tray.
ALERTS = {
    'SOURCE_LOGIN_REQUIRED': ('Smecel desconectado', 'Abra o Coletor e entre no Smecel para continuar a coleta.'),
    'SOURCE_LOGIN_FAILED': ('Smecel recusou o acesso', 'Confira o e-mail e a senha do Smecel salvos no Coletor.'),
    'CLASS_RECONCILIATION_REQUIRED': ('Turma sem ligação no Centro', 'Há turma do Smecel que o Centro não reconheceu. Confira a Importação.'),
    'CENTER_CLASSES_REQUIRED': ('Turmas ainda não importadas', 'Importe a Relação e o Relatório no Centro de Administração.'),
    'NO_SELECTED_CLASSES': ('Nenhuma turma escolhida', 'Abra o Coletor, entre no Smecel e marque as turmas.'),
    'SOURCE_CLASS_UNAVAILABLE': ('Turma fora da lista do Smecel', 'Uma turma escolhida não apareceu na lista do Smecel.'),
    'lease-fenced': ('Coleta interrompida', 'Abra o Coletor para descartar o lote pendente e coletar de novo.'),
    'revision-conflict': ('Coleta interrompida', 'Abra o Coletor para descartar o lote pendente e coletar de novo.'),
    'not-authorized': ('Acesso do computador negado', 'Entre novamente no Ecossistema pelo Coletor.'),
    'PROTECTED_STORAGE_UNAVAILABLE': ('Proteção do Windows indisponível', 'O Coletor não conseguiu proteger os dados neste computador.'),
    'PROTECTED_STORAGE_LIMIT': ('Fila de envio cheia', 'Confira a conexão com a internet.'),
    'PENDING_BATCHES': ('Lotes pendentes de conferência', 'O acesso deste computador mudou. Confira os recibos antes de autorizar uma nova geração.'),
    'ACCESS_REQUIRED': ('Entre no Ecossistema', 'A coleta automática precisa do acesso deste computador.'),
    'CLOCK_OUT_OF_SYNC': ('Horário do Windows incorreto', 'Sincronize data e hora do Windows para retomar a coleta.'),
}


class DesktopApi(PreviewApi):
    def __init__(self, settings_directory=None, access=None):
        self._settings = LocalSettings(settings_directory)
        # The fox is part of the program's identity: always shown, animated unless the
        # system asks for reduced motion.
        self._desktop_state = DesktopState({"version": 1, "show": True, "animate": True})
        self._tray = None
        self._manual_session = ManualSession(settings_directory=settings_directory)
        self._provider = getattr(access, '_provider', None) if access else DeviceProvider(settings_directory)
        self._access = access or InstitutionalAccess(self._provider, on_locked=self._access_locked)
        self._pending_alert = None
        self._resume = ResumeStore(settings_directory)
        self._collector = FrequencyRuntime(self._access, self._provider, self._manual_session, settings_directory,
                                           on_started=self._desktop_state.begin_read,
                                           on_finished=self._desktop_state.end_read,
                                           on_alert=self._alert)

    def _alert(self, code):
        message = ALERTS.get(code)
        if message is None: return
        tray = self._tray
        if tray is None:
            self._pending_alert = message
            return
        tray.notify(*message)

    def _attach_tray(self, tray):
        """Python-only: the tray shows the collector state and pending balloons."""
        self._tray = tray
        tray.status_provider = self._collector.public_status
        message, self._pending_alert = self._pending_alert, None
        if message: tray.notify(*message)

    def _resume_collection(self, attempts=30, interval=60):
        """Python-only. Reopening the program (or Windows) keeps collecting when the
        operator left collection active; it stops only by an explicit pause or logout.
        A boot without network yet is retried for about half an hour."""
        if not self._resume.active(): return False
        for attempt in range(attempts):
            status = self._access.status()
            if status.get('authenticated') and status.get('authorized'):
                result = self._operational(self._collector.activate)
                if 'error' not in result: return True
            elif status.get('code') not in {'ACCESS_UNAVAILABLE', 'LOGIN_UNAVAILABLE'}:
                self._alert('ACCESS_REQUIRED')
                return False
            if attempt + 1 < attempts: time.sleep(interval)
        return False

    def _start_resume(self):
        threading.Thread(target=self._resume_collection, name='collector-resume', daemon=True).start()

    def _access_locked(self):
        # Connectivity loss cancels operational work, but is not a revocation
        # receipt. Retain only the consented encrypted reconciliation queue.
        # Only explicit logout can destroy the protected reconciliation queue.
        # Reauthentication, revocation and connectivity errors are not receipts.
        self._collector.cancel(purge=False)

    def _operational(self, work):
        try: return work()
        except (AccessDenied, StorageError) as error:
            return {'error': 'Não foi possível concluir. Confira o estado do coletor e a conexão.', 'code': error.code}
        except Exception:
            return {'error': 'Não foi possível concluir. Confira o estado do coletor e a conexão.', 'code': 'unavailable'}

    def get_collector_status(self):
        return self._operational(self._collector.refresh)

    def activate_collector(self):
        result = self._operational(self._collector.activate)
        if 'error' not in result: self._resume.set(True)
        return result

    def collect_now(self):
        return self._operational(self._collector.collect)

    def pause_collector(self, paused):
        result = self._operational(lambda: self._collector.local_pause(paused))
        if 'error' not in result: self._resume.set(not paused)
        return result

    def save_source_credential(self, email, password):
        # Write-only: the window never receives the saved password back.
        try: return self._collector.save_credential(email, password)
        except StorageError as error:
            if error.code == 'SOURCE_CREDENTIAL_INVALID':
                return {'error': 'Confira o e-mail e a senha do Smecel.', 'code': error.code}
            return {'error': 'O Windows não conseguiu proteger o acesso neste computador.', 'code': error.code}
        except Exception:
            return {'error': 'Não foi possível salvar o acesso do Smecel.', 'code': 'unavailable'}

    def forget_source_credential(self):
        return self._operational(self._collector.forget_credential)

    def get_collector_history(self):
        return {'entries': self._collector.recent_history(50)}

    def save_shared_schedule(self, revision, schedule):
        return self._operational(lambda: self._collector.save_settings(revision, schedule))

    def pause_school_collection(self, revision, paused):
        return self._operational(lambda: self._collector.school_pause(revision, paused))

    def discard_pending_collection(self):
        return self._operational(self._collector.discard_queue)

    def get_institutional_access_status(self):
        return self._access.status()

    def _pending_batch_blocker(self):
        """Never revoke or replace the identity of an unreconciled encrypted queue."""
        try:
            self._collector._bind_storage()
            if self._collector._storage.queue():
                return {"error": "Há lotes sem recibo. Confira os recibos ou descarte com confirmação antes de sair ou trocar o acesso.",
                        "code": "PENDING_BATCHES"}
        except StorageError as error:
            if error.code == "PENDING_BATCHES":
                return {"error": "Há lotes sem recibo vinculados ao acesso anterior. Confira-os antes de sair ou trocar o acesso.",
                        "code": "PENDING_BATCHES"}
            return {"error": "Há dados protegidos que precisam ser conferidos antes de alterar o acesso deste PC.",
                    "code": "PROTECTED_STORAGE_UNAVAILABLE"}
        return None

    def open_institutional_login(self):
        # A new pairing may revoke the original generation and bind storage
        # to a new device. No unreceipted queue may be destroyed implicitly.
        blocked = self._pending_batch_blocker()
        if blocked is not None: return blocked
        try:
            self._access.open_login()
            return {"ok": True}
        except AccessDenied as error:
            return {"error": str(error), "code": error.code}

    def logout_institutional_access(self):
        # Explicitly clicking "Sair" is not consent to discard academic batches.
        # Revocation must never happen before pending receipts are reconciled.
        blocked = self._pending_batch_blocker()
        if blocked is not None: return blocked
        try:
            self._access.logout()
            self._resume.set(False)
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
        if 'catalog' not in result and confirmed is True:
            # The list redirects to Smecel's login when the session expired: use the saved login.
            credential = self._collector.saved_credential()
            if credential:
                def signed():
                    self._manual_session.sign_in(credential)
                    return self._manual_session.discover(self._manual_session.status()['generation'], True)
                retry = self._manual(signed)
                if 'catalog' in retry: result = retry
        if 'catalog' in result: self._collector.source_ready()
        return result

    def save_manual_class_selection(self, generation, ids, revision):
        result = self._manual(lambda: self._manual_session.save_choices(generation, ids, revision))
        if 'error' not in result:
            self._collector.source_ready()
        return result

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
              "save_schedule", "save_theme", "get_collector_history"):
    setattr(DesktopApi, _name, _protected(getattr(DesktopApi, _name)))

for _name in ('get_collector_status', 'activate_collector', 'collect_now', 'pause_collector',
              'save_shared_schedule', 'pause_school_collection', 'discard_pending_collection',
              'save_source_credential', 'forget_source_credential'):
    setattr(DesktopApi, _name, _protected(getattr(DesktopApi, _name)))

