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
import os
import ctypes
from datetime import datetime

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


def starts_with_windows():
    """The installer's Startup shortcut opens the Coletor beside the clock at logon."""
    base = os.environ.get('APPDATA')
    if not base: return False
    from pathlib import Path
    return (Path(base) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup' / 'Coletor de Frequência.lnk').is_file()


def native_local_recovery_confirmation(summary):
    """A webview click is never authorization to erase academic batches."""
    if os.name!='nt': return False
    def when(value):
        return datetime.fromtimestamp(value).strftime('%d/%m/%Y %H:%M') if type(value) in {int,float} else 'desconhecida'
    amount=summary['count']
    quantity='quantidade desconhecida' if amount is None else f'{amount} lote(s)'
    warning=('O conteudo cifrado nao pode ser aberto com esta autorizacao. '
             'Quantidade e datas desconhecidas.\\n\\n' if summary['unreadable'] else '')
    message=(f'ATENCAO: {quantity} aguardando recibo.\\n'
             f'Primeiro: {when(summary["oldest"])}\\nUltimo: {when(summary["newest"])}\\n\\n'
             +warning+
             'O dispositivo nao pode consultar recibos neste momento. O descarte LOCAL '
             'pode perder marcacoes ainda nao recebidas pelo Ecossistema. '
             'Apenas a fila deste computador sera excluida.\\n\\n'
             'Confirma DESCARTAR definitivamente esses lotes locais?')
    # Default button is No; only an explicit native Windows Yes can erase.
    return ctypes.windll.user32.MessageBoxW(None,message,
        'CONFIRMAR descarte local de frequencia — Coletor',0x4 | 0x30 | 0x100)==6


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
        self._confirm_local_discard = native_local_recovery_confirmation
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
        tray.collect_action = self.collect_now
        tray.pause_action = self.pause_collector
        tray.theme_provider = self._tray_theme
        message, self._pending_alert = self._pending_alert, None
        if message: tray.notify(*message)

    def _tray_theme(self):
        try: return self._settings.read().get("theme", "system")
        except (OSError, ValueError, TypeError): return "system"

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
        result = self._operational(self._collector.refresh)
        if 'error' not in result: self._remember_status(result)
        return result

    # ---- Instant opening: a non-secret summary of the last verified status.
    _SNAPSHOT_FIELDS = ('state', 'code', 'active', 'localPaused', 'persistent', 'credential', 'selectedClasses',
                        'classesMode', 'settings', 'lastReceipt')

    def _snapshot_path(self):
        return self._settings._directory / 'ui-snapshot.json'

    def _remember_status(self, status):
        """Masked account, counts, schedule and last receipt only; never the
        password, tokens, students or diary content."""
        import json, tempfile
        try:
            clean = {k: status.get(k) for k in self._SNAPSHOT_FIELDS}
            payload = json.dumps({'version': 1, 'savedAt': time.time(), 'status': clean}, ensure_ascii=False)
            if len(payload) > 64_000: return
            directory = self._snapshot_path().parent
            directory.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix='.ui-snapshot-', suffix='.tmp', dir=directory)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as file: file.write(payload)
                os.replace(temporary, self._snapshot_path())
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
        except (OSError, TypeError, ValueError):
            pass

    def _forget_status(self):
        try: self._snapshot_path().unlink(missing_ok=True)
        except OSError: pass

    def get_startup_snapshot(self):
        """Read locally, without the network, so the window opens ready. The
        live status replaces it moments later; nothing here authorizes work."""
        import json
        paired = False
        try:
            device = json.loads((self._settings._directory / 'device.json').read_text(encoding='utf-8'))
            paired = isinstance(device, dict) and device.get('state') == 'active'
        except (OSError, ValueError):
            pass
        status = None
        if paired:
            try:
                cached = json.loads(self._snapshot_path().read_text(encoding='utf-8'))
                if isinstance(cached, dict) and cached.get('version') == 1 and isinstance(cached.get('status'), dict):
                    status = {k: cached['status'].get(k) for k in self._SNAPSHOT_FIELDS}
            except (OSError, ValueError):
                pass
        try: history = self._collector.recent_history(200) if paired else []
        except Exception: history = []
        return {'paired': paired, 'status': status, 'history': history, 'settings': self._read_settings()['settings']}

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
        try:
            result = self._collector.save_credential(email, password)
            self._remember_status(result)
            return result
        except StorageError as error:
            if error.code == 'SOURCE_CREDENTIAL_INVALID':
                return {'error': 'Confira o e-mail e a senha do Smecel.', 'code': error.code}
            return {'error': 'O Windows não conseguiu proteger o acesso neste computador.', 'code': error.code}
        except Exception:
            return {'error': 'Não foi possível salvar o acesso do Smecel.', 'code': 'unavailable'}

    def forget_source_credential(self):
        result = self._operational(self._collector.forget_credential)
        if 'error' not in result: self._remember_status(result)
        return result

    def get_collector_history(self):
        return {'entries': self._collector.recent_history(200)}

    def save_shared_schedule(self, revision, schedule):
        return self._operational(lambda: self._collector.save_settings(revision, schedule))

    def pause_school_collection(self, revision, paused):
        return self._operational(lambda: self._collector.school_pause(revision, paused))

    def discard_pending_collection(self):
        return self._operational(self._collector.discard_queue)

    def get_local_recovery_status(self):
        # Public metadata only: no student, requestId, cookie or login secret.
        try: return self._collector._storage.recovery_status()
        except StorageError: return {'pending': False, 'count': None,
                                      'oldest': None, 'newest': None, 'unreadable': True}

    def discard_local_pending_collection(self):
        # Deliberately outside _protected: a revoked device has no proof with
        # which to query receipt. An OS-native confirmation remains mandatory.
        # Never allow a temporary network outage to masquerade as revocation.
        if not self._collector._operation.acquire(blocking=False):
            return {'error':'Há coleta em andamento. Interrompa antes de descartar.',
                    'code':'CANCELLED'}
        try:
            status=self._access.status()
            if status.get('code') in {'ACCESS_UNAVAILABLE','LOGIN_UNAVAILABLE'}:
                return {'error':'Sem conexão. Aguarde para conferir os recibos; não descarte por falha temporária.',
                        'code':'ACCESS_UNAVAILABLE'}
            if status.get('authenticated') and status.get('authorized'):
                try:
                    self._collector._bind_storage()
                    current=self._collector._storage.recovery_status()
                except StorageError as error:
                    current=self._collector._storage.recovery_status()
                    if error.code!='PENDING_BATCHES' and not (current['pending'] and current['unreadable']):
                        return {'error':'Não foi possível conferir a fila cifrada.','code':error.code}
                else:
                    # A still-readable queue must use server receipts; an
                    # unreadable prior-generation DPAPI blob cannot do so.
                    if not (current['pending'] and current['unreadable']):
                        return {'error':'O computador está autorizado. Consulte primeiro os recibos pelo descarte normal.',
                                'code':'ACCESS_REQUIRED'}
            summary=self._collector._storage.recovery_status()
            if not summary['pending']:
                return {'ok':True,'discarded':False}
            if not self._confirm_local_discard(summary):
                return {'error':'Descarte cancelado; todos os lotes foram preservados.',
                        'code':'CANCELLED'}
            self._collector.cancel(purge=False,pause=True)
            self._collector._storage.discard_confirmed_local_queue()
            self._resume.set(False)
            return {'ok':True,'discarded':True}
        except StorageError as error:
            return {'error':'O Windows não conseguiu verificar ou alterar a fila local.',
                    'code':error.code}
        finally: self._collector._operation.release()

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

    def _identity_change_busy(self):
        return {"error": "Há coleta ou outra operação em andamento. Aguarde para alterar o acesso deste PC.",
                "code": "CANCELLED"}

    def open_institutional_login(self):
        # The same operation mutex protects all enqueue/send operations. Hold
        # it across both the queue inspection AND the identity mutation so a
        # concurrent collector cannot insert a batch in the TOCTOU interval.
        if not self._collector._operation.acquire(blocking=False):
            return self._identity_change_busy()
        try:
            blocked = self._pending_batch_blocker()
            if blocked is not None: return blocked
            try:
                self._access.open_login()
                return {"ok": True}
            except AccessDenied as error:
                return {"error": str(error), "code": error.code}
        finally:
            self._collector._operation.release()

    def logout_institutional_access(self):
        # Logout is not permission to lose a batch; serialize check+revoke+
        # purge atomically against live collection, even on network failure.
        if not self._collector._operation.acquire(blocking=False):
            return self._identity_change_busy()
        try:
            blocked = self._pending_batch_blocker()
            if blocked is not None: return blocked
            try:
                self._access.logout()
                self._forget_status()
                self._resume.set(False)
                self._collector.cancel(purge=True)
                self._manual_session.close()
                return {"ok": True}
            except AccessDenied as error:
                return {"error": str(error), "code": error.code}
            except Exception:
                return {"error": "Não foi possível concluir a limpeza da sessão.", "code": "ACCESS_CLEANUP_PENDING"}
        finally:
            self._collector._operation.release()

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
        # With a saved Smecel access the Coletor signs in itself, so the window
        # can stay hidden (Ajustes); otherwise the person signs in in Edge.
        can_sign_in = bool(self._collector.saved_credential())
        return self._manual(lambda: self._manual_session.open(generation, confirmed, can_sign_in))

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
                "automatic_collection": self._collector.public_status()['active'],
                "autostart": starts_with_windows()}

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

    def save_browser_preference(self, visible):
        if type(visible) is not bool: return {"error": "Preferência inválida."}
        return self._save("browser", {"visible": visible})

    def save_classes_mode(self, mode):
        result = self._save("classes", {"mode": mode})
        if "error" not in result:
            # The count shown in Tarefas follows the new mode at once.
            status = self._operational(self._collector.public_status)
            if "error" not in status: self._remember_status(status)
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
              "save_schedule", "save_theme", "get_collector_history", "save_browser_preference", "save_classes_mode"):
    setattr(DesktopApi, _name, _protected(getattr(DesktopApi, _name)))

for _name in ('get_collector_status', 'activate_collector', 'collect_now', 'pause_collector',
              'save_shared_schedule', 'pause_school_collection', 'discard_pending_collection',
              'save_source_credential', 'forget_source_credential'):
    setattr(DesktopApi, _name, _protected(getattr(DesktopApi, _name)))

