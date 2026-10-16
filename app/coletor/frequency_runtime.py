"""Operational V2 collector: server authority, sparse observations and receipts.

Only the private source worker supplies snapshots. The public webview has no
method that accepts collection payloads, identities, HTML or proof material.
"""
from datetime import datetime, timezone, timedelta
import copy
import re
import threading
import time
import uuid
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .device_provider import FrequencyError
from .device_provider import canonical_frequency
import hashlib
import ctypes
import os
from .history import CollectorHistory
from .institutional_access import AccessDenied
from .manual_session import SessionError
from .protected_storage import ProtectedStorage, StorageError

SAFE_CODES = {'invalid-request', 'not-authorized', 'unavailable', 'revision-conflict', 'lease-busy',
              'lease-fenced', 'paused', 'source-invalid', 'identity-review', 'SOURCE_LOGIN_REQUIRED',
              'SOURCE_CLASS_UNAVAILABLE', 'SOURCE_CLASS_AMBIGUOUS', 'NO_SELECTED_CLASSES',
              'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT', 'QUEUE_REQUEST_CONFLICT',
              'ACCESS_REQUIRED', 'ACCESS_UNAVAILABLE', 'CANCELLED', 'SOURCE_LOGIN_FAILED',
              'CLASS_RECONCILIATION_REQUIRED', 'CENTER_CLASSES_REQUIRED'}
# Problems an operator must see even with the window hidden in the tray.
ALERT_CODES = {'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED', 'CLASS_RECONCILIATION_REQUIRED',
               'CENTER_CLASSES_REQUIRED', 'NO_SELECTED_CLASSES', 'SOURCE_CLASS_UNAVAILABLE', 'lease-fenced',
               'revision-conflict', 'not-authorized', 'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT'}
# Routine waits are not failures: a reserve computer or a school pause.
QUIET_CODES = {'lease-busy', 'paused', 'CANCELLED'}


def discard_confirmation():
    if os.name != 'nt': return False
    return ctypes.windll.user32.MessageBoxW(None,
        'O servidor não registrou recibo para o lote pendente. Descartar este lote local e coletar novamente?\n\n'
        'As marcações já recebidas no Ecossistema serão preservadas.',
        'Recapturar frequência — Coletor', 0x4 | 0x20 | 0x100) == 6


def label(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def class_key(value):
    """Same rule as the Centro (frequencyClassKeyV2): accents, case, spacing and
    punctuation never distinguish classes, e.g. "8D 2026 -VESPERTINO"."""
    text = unicodedata.normalize('NFD', value if isinstance(value, str) else '')
    text = ''.join(c for c in text if not '\u0300' <= c <= '\u036f').upper()
    return re.sub(r'[^A-Z0-9]', '', text)


def stamp(value):
    if not isinstance(value, str): raise FrequencyError('unavailable')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result.timestamp()
    except (ValueError, OverflowError): raise FrequencyError('unavailable') from None


def validate_schedule(schedule):
    if not isinstance(schedule, dict) or set(schedule) != {'timezone', 'rules'}: raise FrequencyError('invalid-request')
    try: ZoneInfo(schedule['timezone'])
    except (ZoneInfoNotFoundError, ValueError, TypeError): raise FrequencyError('invalid-request') from None
    rules = schedule['rules']
    if not isinstance(rules, list) or len(rules) != 14: raise FrequencyError('invalid-request')
    keys = set()
    for rule in rules:
        if (not isinstance(rule, dict) or set(rule) != {'weekday', 'shift', 'enabled', 'times', 'recheck'}
                or type(rule['weekday']) is not int or not 0 <= rule['weekday'] <= 6
                or rule['shift'] not in {'matutino', 'vespertino'} or type(rule['enabled']) is not bool
                or not isinstance(rule['times'], list) or len(rule['times']) > 16): raise FrequencyError('invalid-request')
        key = (rule['weekday'], rule['shift'])
        if key in keys: raise FrequencyError('invalid-request')
        keys.add(key)
        times = rule['times']
        if any(not isinstance(t, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in times):
            raise FrequencyError('invalid-request')
        if len(set(times)) != len(times): raise FrequencyError('invalid-request')
        recheck = rule['recheck']
        if recheck is not None and (not isinstance(recheck, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', recheck)
                                    or any(t >= recheck for t in times)): raise FrequencyError('invalid-request')
        if len(times) + (1 if recheck is not None else 0) > 16: raise FrequencyError('invalid-request')
    return copy.deepcopy(schedule)


def collection_payload(preview, source_class, server_class, fencing, request_id, timezone_name='America/Bahia'):
    """Input is a Python worker result, never a bridged/user imported preview."""
    snapshot, capture = preview['snapshot'], preview['capture']
    if (preview.get('mode') != 'manual' or snapshot.get('source_format') != 'smecel-annual-v1'
            or capture.get('destination') != 'local_memory' or snapshot.get('year') != 2026
            or snapshot.get('class_id') != source_class['class_id']): raise FrequencyError('source-invalid')
    expected = class_key(source_class['name'])
    if not expected or class_key(server_class['sourceClassLabel']) != expected: raise FrequencyError('source-invalid')
    students = snapshot['students']
    if not 1 <= len(students) <= 64: raise FrequencyError('source-invalid')
    if any(class_key(s.get('original_class')) != expected for s in students): raise FrequencyError('source-invalid')
    if len({s['source_student_ref'] for s in students}) != len(students): raise FrequencyError('source-invalid')
    keys, duplicates = {}, {}
    for student in students:
        normalized_name = unicodedata.normalize('NFC', label(student['display_name'])).casefold()
        normalized_class = unicodedata.normalize('NFC', label(student['original_class'])).casefold()
        signature = (normalized_name, normalized_class)
        duplicates[signature] = duplicates.get(signature, 0) + 1
        # An opaque source reference is not identity authority. The backend
        # resolves originalName+originalClass centrally on every observation.
        reference = {'academicYear': 2026, 'sourceClassId': source_class['class_id'],
                     'originalName': normalized_name, 'originalClass': normalized_class,
                     'duplicateOrdinal': duplicates[signature]}
        keys[student['source_student_ref']] = 'source:' + hashlib.sha256(canonical_frequency(reference)).hexdigest()
    records = [{'recordKey': keys[s['source_student_ref']], 'originalName': s['display_name'],
                'originalClass': s['original_class']} for s in students]
    marks, coverage = [], {}
    cutoff = datetime.fromtimestamp(stamp(capture['captured_at']), ZoneInfo(timezone_name)).date().isoformat()
    for record in snapshot['records']:
        if record['state'] not in {'absent', 'excused_absent'} or record['date'] > cutoff: continue
        if record['source_student_ref'] not in keys or not 1 <= record['lesson'] <= 6: raise FrequencyError('source-invalid')
        key = keys[record['source_student_ref']]
        marks.append({'recordKey': key, 'date': record['date'], 'slot': record['lesson'],
                      'mark': 'X' if record['state'] == 'absent' else 'J'})
        coverage.setdefault((key, record['date']), set()).add(record['lesson'])
    # Points, missing roster evidence and empty cells cannot certify coverage.
    version = hashlib.sha256(canonical_frequency({'academicYear': 2026, 'sourceClassId': source_class['class_id'],
        'observedAt': capture['captured_at'], 'htmlSha256': capture['html_sha256'], 'parserVersion': 'smecel-annual-v1'})).hexdigest()
    return {'operation': 'collect', 'academicYear': 2026, 'requestId': request_id, 'fencingToken': fencing,
            'classId': server_class['classId'], 'expectedRevision': server_class['revision'],
            'sourceVersion': 'sha256:' + version, 'sourceClassId': source_class['class_id'],
            'sourceClassLabel': source_class['name'], 'observedAt': capture['captured_at'], 'rosterComplete': False,
            'records': records, 'marks': marks,
            'coverage': [{'recordKey': k, 'date': d, 'slots': sorted(slots), 'complete': False}
                         for (k, d), slots in coverage.items()]}


class FrequencyRuntime:
    def __init__(self, access, provider, source, directory=None, *, storage=None, clock=time.time,
                 on_started=lambda: None, on_finished=lambda failed: None, confirm_discard=discard_confirmation,
                 history=None, on_alert=lambda code: None):
        self._access, self._provider, self._source, self._clock = access, provider, source, clock
        self._storage = storage or ProtectedStorage(directory, clock=clock)
        self._history = history or CollectorHistory(self._storage.directory.parent, clock=clock)
        self._on_alert = on_alert
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._epoch = 0
        self._active, self._paused, self._closed = False, False, False
        self._school_paused = False
        self._confirm_discard = confirm_discard
        self._state, self._code = 'connect', None
        self._status, self._lease, self._class, self._last_receipt = None, None, None, None
        self._progress = {'completed': 0, 'total': 0, 'classLabel': None}
        self._minute = None
        self._fired = set()
        self._source_blocked = False
        self._last_tick = 0
        self._thread = None
        self._stop = threading.Event()
        self._on_started, self._on_finished = on_started, on_finished

    def _request(self, payload):
        return self._access.run(lambda: self._provider.frequency_request(payload))

    def _mutation(self, operation, **fields):
        payload = {'operation': operation, 'academicYear': 2026, 'requestId': str(uuid.uuid4()), **fields}
        reply = self._committed(self._request(payload), payload)
        if operation in {'save-settings', 'set-paused'} and reply.get('settingsRevision') != fields['expectedRevision'] + 1:
            raise FrequencyError('unavailable')
        return reply

    def _fresh(self):
        # A server timestamp is generated after the local request begins. Using
        # this earlier local bound never overstates an existing lease deadline.
        requested_at = self._clock()
        value = self._request({'operation': 'status', 'academicYear': 2026})
        try:
            if (value['contractVersion'] != 2 or value['state'] != 'ready' or value['academicYear'] != 2026
                    or not isinstance(value['classes'], list) or not isinstance(value['settings'], dict)):
                raise ValueError()
            stamp(value['serverTime'])
            settings = value['settings']
            if type(settings['revision']) is not int or settings['revision'] < 0 or type(settings['paused']) is not bool: raise ValueError()
            if settings['schedule'] is not None: validate_schedule(settings['schedule'])
            for c in value['classes']:
                if (type(c['classId']) is not int or c['classId'] < 1 or type(c['revision']) is not int
                        or c['revision'] < 0 or not label(c['sourceClassLabel'])): raise ValueError()
        except (KeyError, ValueError, TypeError): raise FrequencyError('unavailable') from None
        # Internal-only metadata; never exposed through the desktop bridge.
        value['_request_started_at'] = requested_at
        with self._lock:
            self._status = value
            self._school_paused = value['settings']['paused']
        return value

    def _committed(self, reply, payload):
        if (not isinstance(reply, dict) or reply.get('contractVersion') != 2 or reply.get('state') != 'committed'
                or reply.get('operation') != payload['operation'] or reply.get('requestId') != payload['requestId']):
            raise FrequencyError('unavailable')
        return reply

    def _check(self, epoch, lease=True):
        with self._lock:
            if self._closed or epoch != self._epoch or self._paused or not self._active: raise FrequencyError('CANCELLED')
            if self._school_paused: raise FrequencyError('paused')
            if lease and (self._lease is None or self._lease['deadline'] <= self._clock()): raise FrequencyError('lease-fenced')

    def activate(self):
        status = self._fresh()
        self._storage.bind(*self._provider.storage_binding())
        remembered = self._storage.enable()
        with self._lock:
            self._access.run(lambda: self._source.remember_if_ready(self._storage))
        with self._lock:
            if self._closed: raise FrequencyError('CANCELLED')
            self._active, self._paused = True, False
            self._state, self._code = ('paused' if status['settings']['paused'] else 'reserve'), None
            self._history.record('activated')
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name='collector-scheduler', daemon=True)
                self._thread.start()
        return {**self.public_status(), 'rememberSession': remembered}

    def _loop(self):
        while not self._stop.wait(1):
            now = self._clock()
            elapsed = now - self._last_tick
            # Clock corrections must not suspend collection checks until the
            # old wall-clock time is reached again. _fired still blocks repeats.
            if 0 <= elapsed < 30: continue
            self._last_tick = now
            try: self.tick()
            except Exception as error: self._error(error)

    @staticmethod
    def _state_for(code):
        if code == 'lease-busy': return 'reserve'
        if code in {'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED'}: return 'login-required'
        if code in {'paused', 'CANCELLED'}: return 'paused'
        return 'error'

    def _error(self, error, label=None):
        code = getattr(error, 'code', 'unavailable')
        if isinstance(error, SessionError):
            code = 'SOURCE_LOGIN_FAILED' if str(error) == 'SOURCE_LOGIN_FAILED' else 'SOURCE_LOGIN_REQUIRED'
        if code not in SAFE_CODES: code = 'unavailable'
        # With a saved Smecel login an expired session is retried at the next
        # scheduled time. A refused password or no saved login waits for a person.
        blocks_source = code == 'SOURCE_LOGIN_FAILED' or (
            code == 'SOURCE_LOGIN_REQUIRED' and self._storage.load_credential() is None)
        with self._lock:
            changed = self._code != code
            self._code = code
            if blocks_source: self._source_blocked = True
            self._state = self._state_for(code)
            if code in {'lease-fenced', 'not-authorized', 'paused'}: self._lease = None
        if code not in QUIET_CODES and changed: self._history.record('failure', code=code, label=label)
        if code in ALERT_CODES and changed:
            try: self._on_alert(code)
            except Exception: pass

    def public_status(self):
        with self._lock:
            return {'state': self._state, 'code': self._code, 'active': self._active, 'localPaused': self._paused,
                    'persistent': self._storage.persistent, 'progress': dict(self._progress),
                    'credential': self._storage.credential_status(),
                    'lastReceipt': self._last_receipt,
                    # Status shown locally contains operational settings only.
                    'settings': copy.deepcopy(self._status['settings']) if self._status else None}

    def refresh(self):
        self._fresh()
        self._bind_storage()
        return self.public_status()

    def _bind_storage(self):
        try: self._storage.bind(*self._provider.storage_binding())
        except Exception: pass  # Unbound storage simply reports no saved login.

    def save_credential(self, email, password):
        self._storage.bind(*self._provider.storage_binding())
        self._storage.save_credential(email, password)
        with self._lock:
            self._source_blocked = False
            if self._state == 'login-required': self._state, self._code = 'reserve', None
        return self.public_status()

    def forget_credential(self):
        self._storage.bind(*self._provider.storage_binding())
        self._storage.clear_credential()
        return self.public_status()

    def saved_credential(self):
        """Python-only: the login reaches the isolated Edge worker, never the window."""
        self._bind_storage()
        return self._storage.load_credential()

    def _acquire(self, status, force=False):
        if status['settings']['paused']: raise FrequencyError('paused')
        if not force and self._lease and self._lease['deadline'] > self._clock(): return
        existing = status.get('lease')
        if not force and existing is not None:
            device_id, _ = self._provider.storage_binding()
            remaining = stamp(existing['expiresAt']) - stamp(status['serverTime'])
            deadline = status['_request_started_at'] + remaining - 2
            if existing.get('deviceId') == device_id and type(existing.get('fencingToken')) is int and deadline > self._clock():
                with self._lock:
                    self._lease = {**existing, 'deadline': deadline}
                return
        request = {'operation': 'lease', 'academicYear': 2026, 'requestId': str(uuid.uuid4()), 'durationSeconds': 120}
        requested_at = self._clock()
        reply = self._committed(self._request(request), request)
        if type(reply.get('fencingToken')) is not int or reply['fencingToken'] < 1: raise FrequencyError('unavailable')
        # The database issues exactly the requested 120-second lease *after*
        # this request begins. A deadline based on the request start is a safe
        # lower bound even when the preceding status or network is slow. Do not
        # infer 120 seconds of freshness from the time the reply arrived.
        if stamp(reply['expiresAt']) <= stamp(status['serverTime']): raise FrequencyError('lease-fenced')
        deadline = requested_at + 120 - 2
        if deadline <= self._clock(): raise FrequencyError('lease-fenced')
        with self._lock:
            self._lease = {**reply, 'deadline': deadline}
            if self._source_blocked: self._state, self._code = 'login-required', 'SOURCE_LOGIN_REQUIRED'
            elif self._code not in {None, 'lease-busy', 'unavailable', 'CANCELLED', 'paused'}: self._state = 'error'
            else: self._state, self._code = 'ready', None

    def _heartbeat(self, epoch):
        self._check(epoch)
        status = self._fresh()
        if status['settings']['paused']: raise FrequencyError('paused')
        with self._lock:
            fencing = self._lease['fencingToken']
            state = 'collecting' if self._state == 'collecting' else 'login-required' if self._source_blocked else 'error' if self._state == 'error' else 'ready'
            class_id = self._class
            code = self._code.replace('-', '_').upper() if self._code and state in {'error', 'login-required'} else None
        request = {'operation': 'heartbeat', 'academicYear': 2026, 'requestId': str(uuid.uuid4()),
                   'fencingToken': fencing, 'status': state, 'classId': class_id, 'code': code}
        reply = self._committed(self._request(request), request)
        if reply.get('fencingToken') != fencing or reply.get('expiresAt') is None: raise FrequencyError('lease-fenced')
        remaining = stamp(reply['expiresAt']) - stamp(status['serverTime'])
        if not 0 < remaining <= 305: raise FrequencyError('lease-fenced')
        # Heartbeats report status; the server explicitly does not renew the
        # grant. A delayed heartbeat must never extend our original deadline.
        deadline = status['_request_started_at'] + remaining - 2
        if deadline <= self._clock(): raise FrequencyError('lease-fenced')
        with self._lock:
            if epoch != self._epoch or self._lease is None: raise FrequencyError('CANCELLED')
            if self._lease['fencingToken'] != fencing: return status
            self._lease['deadline'] = min(self._lease['deadline'], deadline)
        return status

    def tick(self):
        with self._lock:
            if self._closed or not self._active or self._paused: return
            epoch = self._epoch
        if self._operation.locked(): return
        status = self._fresh()
        if status['settings']['paused']:
            self.cancel(purge=False, school_pause=True)
            return
        schedule = status['settings']['schedule']
        # A device with no executable agenda or a known source blocker must
        # not monopolise the school lease. Eligible leaders still heartbeat
        # every 30 s so that the admin sees connected/standby computers.
        if schedule is None or not any(
            r['enabled'] and (r['times'] or r['recheck']) for r in schedule['rules']
        ): return
        blockers = {'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED', 'NO_SELECTED_CLASSES',
                    'CENTER_CLASSES_REQUIRED', 'SOURCE_CLASS_UNAVAILABLE',
                    'SOURCE_CLASS_AMBIGUOUS', 'CLASS_RECONCILIATION_REQUIRED',
                    'source-invalid', 'identity-review', 'revision-conflict',
                    'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT'}
        if self._source_blocked or self._code in blockers: return
        self._acquire(status)
        status = self._heartbeat(epoch)
        now = datetime.fromtimestamp(self._clock(), ZoneInfo(schedule['timezone']))
        minute = now.strftime('%Y-%m-%dT%H:%M%z')
        if minute == self._minute: return
        self._minute = minute  # No replay after sleep/offline, including DST.
        civil_day, wall_time = now.date().isoformat(), now.strftime('%H:%M')
        oldest = (now.date() - timedelta(days=7)).isoformat()
        self._fired = {key for key in self._fired if key[0] >= oldest}
        shifts = {r['shift'] for r in schedule['rules'] if r['enabled'] and r['weekday'] == (now.weekday() + 1) % 7
                  and wall_time in [*r['times'], r['recheck']] and (civil_day, r['shift'], wall_time) not in self._fired}
        if shifts:
            if self._source_blocked or self._code in {'lease-fenced', 'revision-conflict', 'source-invalid',
                   'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT', 'SOURCE_CLASS_UNAVAILABLE',
                   'SOURCE_CLASS_AMBIGUOUS', 'identity-review'}: return
            keys = {(civil_day, shift, wall_time) for shift in shifts}
            if not self._operation.acquire(blocking=False):
                self._minute = None  # A concurrent command may finish within this minute.
                return
            try:
                self._fired.update(keys)
                # The scheduler owns this lock until the worker finishes. This
                # also releases it for injected test workers and early errors.
                def run_scheduled():
                    try: self.collect(shifts, _claimed=True)
                    finally: self._operation.release()
                threading.Thread(target=run_scheduled, daemon=True, name='collector-capture').start()
            except Exception:
                self._fired.difference_update(keys)
                self._minute = None
                self._operation.release()
                raise

    def collect(self, shifts=None, *, _claimed=False):
        # A scheduled invocation already owns the operation lock so its minute
        # cannot be marked fired before a capture is accepted.
        if not _claimed and not self._operation.acquire(blocking=False): return self.public_status()
        self._on_started()
        heartbeat_stop = threading.Event()
        heartbeat = None
        try:
            with self._lock:
                epoch = self._epoch
                if not self._active or self._paused: raise FrequencyError('CANCELLED')
            status = self._fresh()
            self._reconcile_receipts(epoch)
            # Ineligible devices do not take the school-wide lease from a
            # healthy standby collector just to discover a known blocker.
            if not status['classes']: raise FrequencyError('CENTER_CLASSES_REQUIRED')
            if self._source_blocked: raise SessionError('SOURCE_LOGIN_REQUIRED')
            self._acquire(status)
            self._check(epoch)
            self._drain(epoch)
            catalog = self._access.run(lambda: self._source.operational_catalog(self._storage))
            self._check(epoch)
            selected = set(catalog['selected_class_ids'])
            sources = [c for c in catalog['catalog']['classes'] if c['class_id'] in selected]
            if catalog['unavailable_class_ids']: raise FrequencyError('SOURCE_CLASS_UNAVAILABLE')
            if not sources: raise FrequencyError('NO_SELECTED_CLASSES')
            pairs, unmatched = self._pair_classes(sources, status['classes'], shifts)
            with self._lock:
                self._state, self._code = 'collecting', None
                self._progress = {'completed': 0, 'total': len(pairs), 'classLabel': None}
            self._history.record('collection-started', sent=len(pairs))
            def renew():
                while not heartbeat_stop.wait(30):
                    with self._lock:
                        lease = self._lease
                        if lease is None or lease['deadline'] <= self._clock(): continue
                        fencing = lease['fencingToken']
                    try: self._heartbeat(epoch)
                    except Exception as error:
                        # A grant that lapsed during a slow capture, or that the
                        # capture loop already replaced, is renewed before the next
                        # send. Only a fence on the current grant cancels the work.
                        with self._lock:
                            lapsed = (self._lease is None or self._lease['fencingToken'] != fencing
                                      or self._lease['deadline'] <= self._clock())
                        if getattr(error, 'code', None) == 'lease-fenced' and lapsed: continue
                        # Heartbeat only reports device state and does not extend
                        # a lease. A transient outage cannot cancel the source
                        # capture; every transmission still rechecks authority.
                        if getattr(error, 'code', None) in {'unavailable', 'ACCESS_UNAVAILABLE'}:
                            continue
                        self._error(error)
                        self.cancel(purge=False, school_pause=getattr(error, 'code', None) == 'paused')
                        return
            heartbeat = threading.Thread(target=renew, name='collector-heartbeat', daemon=True)
            heartbeat.start()
            for source, central in pairs:
                self._check(epoch, lease=False)
                fresh = self._fresh()
                if fresh['settings']['paused']: raise FrequencyError('paused')
                # Every class starts with a new database concession, fencing and
                # requestId. Heartbeat only reports status; it does not renew.
                self._acquire(fresh, force=True)
                self._check(epoch)
                current = next((c for c in fresh['classes'] if c['classId'] == central['classId']
                                and class_key(c['sourceClassLabel']) == class_key(source['name'])), None)
                if current is None: raise FrequencyError('source-invalid')
                with self._lock:
                    self._class = current['classId']
                    self._progress['classLabel'] = source['name']
                preview = self._access.run(lambda: self._source.operational_capture(source['class_id']))
                self._check(epoch, lease=False)
                after_capture = self._fresh()
                if after_capture['settings']['paused']: raise FrequencyError('paused')
                if self._lease is None or self._lease['deadline'] <= self._clock():
                    self._acquire(after_capture, force=True)
                    self._check(epoch)
                school_zone = (after_capture['settings']['schedule'] or {'timezone': 'America/Bahia'})['timezone']
                payload = collection_payload(preview, source, current, self._lease['fencingToken'], str(uuid.uuid4()), school_zone)
                del preview
                with self._lock:
                    self._check(epoch)
                    self._storage.enqueue(payload)
                self._send(payload, epoch)
                with self._lock:
                    self._progress['completed'] += 1
                    receipt = dict(self._last_receipt or {})
                self._history.record('class-sent', label=source['name'], sent=receipt.get('resolvedRecords'),
                                     unresolved=receipt.get('unresolvedRecords'), conflicts=receipt.get('conflicts'))
            self._check(epoch)
            self._access.run(lambda: self._source.preserve_and_close(self._storage))
            with self._lock:
                self._state, self._class = 'ready', None
                self._progress['classLabel'] = None
            self._history.record('collection-finished', sent=len(pairs))
            if unmatched:
                # The classes the Centro recognizes were sent; the others need a link there.
                self._error(FrequencyError('CLASS_RECONCILIATION_REQUIRED'), label=', '.join(unmatched))
            return self.public_status()
        except Exception as error:
            self._error(error)
            try:
                self._check(epoch, lease=False)
                self._source.preserve_and_close(self._storage)
            except Exception:
                try: self._source.close()
                except Exception: pass
            return self.public_status()
        finally:
            heartbeat_stop.set()
            if heartbeat: heartbeat.join(timeout=1)
            if not _claimed: self._operation.release()
            self._on_finished(self.public_status()['state'] == 'error')

    @staticmethod
    def _pair_classes(sources, classes, shifts):
        """Smecel classes matched to the Centro's Relatório/Relação link."""
        pairs, unmatched = [], []
        for source in sources:
            key = class_key(source['name'])
            matches = {c['classId']: c for c in classes if key and class_key(c['sourceClassLabel']) == key}
            if len(matches) != 1:
                unmatched.append(source['name'])
                continue
            central = next(iter(matches.values()))
            if shifts is None or central['shift'] in shifts: pairs.append((source, central))
        return pairs, unmatched

    def recent_history(self, limit=50):
        return self._history.recent(limit)

    def _receipt(self, payload):
        reply = self._request({'operation': 'receipt', 'academicYear': 2026, 'requestId': payload['requestId']})
        if reply.get('state') != 'ready' or reply.get('operation') != 'receipt' or reply.get('requestId') != payload['requestId']:
            raise FrequencyError('unavailable')
        if reply.get('result') is not None: return self._collection_receipt(reply['result'], payload)
        return None

    def _collection_receipt(self, result, payload):
        self._committed(result, payload)
        if (result.get('classId') != payload['classId'] or type(result.get('revision')) is not int or result['revision'] < 0
                or any(type(result.get(k)) is not int or result[k] < 0 for k in ('resolvedRecords', 'unresolvedRecords', 'conflicts'))):
            raise FrequencyError('unavailable')
        stamp(result['receivedAt'])
        return result

    def _reconcile_receipts(self, epoch):
        # Reopening with an uncertain queue consults the original receipt
        # BEFORE acquiring a fresh concession or doing any source work.
        for entry in self._storage.queue():
            self._check(epoch, lease=False)
            payload = entry['payload']
            result = self._receipt(payload)
            if result is not None: self._storage.acknowledge(payload['requestId'])

    def _send(self, payload, epoch):
        # Every attempt has the identical payload/requestId and a new challenge.
        # A timeout is reconciled before a bounded retry, never called success.
        result = None
        for attempt in range(3):
            self._check(epoch)
            if attempt:
                result = self._receipt(payload)
                if result is not None: break
                if self._stop.wait(2 ** attempt): raise FrequencyError('CANCELLED')
            self._check(epoch)
            try:
                result = self._committed(self._request(payload), payload)
                break
            except (AccessDenied, FrequencyError) as error:
                if error.code not in {'unavailable', 'ACCESS_UNAVAILABLE'}: raise
                if attempt == 2: raise
        self._check(epoch)
        if result is None: raise FrequencyError('unavailable')
        self._collection_receipt(result, payload)
        self._storage.acknowledge(payload['requestId'])
        with self._lock:
            self._last_receipt = {k: result[k] for k in ('receivedAt', 'resolvedRecords', 'unresolvedRecords', 'conflicts')}

    def _drain(self, epoch):
        for entry in self._storage.queue():
            self._check(epoch)
            payload = entry['payload']
            receipt = self._receipt(payload)
            if receipt is not None:
                self._storage.acknowledge(payload['requestId'])
                continue
            # A takeover or changed CAS requires a fresh capture and visible
            # operator action. Never silently rewrite queued signed payloads.
            if payload.get('fencingToken') != self._lease['fencingToken']: raise FrequencyError('lease-fenced')
            self._send(payload, epoch)

    def save_settings(self, expected_revision, schedule):
        validate_schedule(schedule)
        if type(expected_revision) is not int or expected_revision < 0: raise FrequencyError('invalid-request')
        self._mutation('save-settings', expectedRevision=expected_revision, schedule=schedule)
        return self.refresh()

    def source_ready(self):
        with self._lock:
            self._source_blocked = False
            if self._state == 'login-required': self._state, self._code = 'reserve', None

    def school_pause(self, expected_revision, paused):
        if type(expected_revision) is not int or expected_revision < 0 or type(paused) is not bool: raise FrequencyError('invalid-request')
        self._mutation('set-paused', expectedRevision=expected_revision, paused=paused)
        if paused: self.cancel(purge=False, school_pause=True)
        else:
            with self._lock: self._school_paused = False
        return self.refresh()

    def local_pause(self, paused):
        if type(paused) is not bool: raise FrequencyError('invalid-request')
        if paused: self.cancel(purge=False, pause=True)
        else:
            with self._lock:
                self._paused = False
                self._state, self._code = 'reserve', None
        self._history.record('paused' if paused else 'resumed')
        return self.public_status()

    def cancel(self, purge=False, pause=False, school_pause=False):
        with self._lock:
            self._epoch += 1
            lease, self._lease = self._lease, None
            self._class = None
            self._state = 'paused' if pause or school_pause else 'connect'
            if pause: self._paused = True
            if school_pause: self._school_paused = True
            if purge:
                self._active = False
                self._status, self._last_receipt = None, None
                self._progress = {'completed': 0, 'total': 0, 'classLabel': None}
                self._fired.clear()
        # Cooperative EOF / Job Object interrupts an in-flight source capture.
        self._source.close()
        if purge: self._storage.clear()
        if pause and lease:
            try: self._mutation('release', fencingToken=lease['fencingToken'], code='LOCAL_PAUSE')
            except Exception: pass

    def discard_queue(self):
        # Explicit recapture after fencing/CAS; no automatic adoption.
        pending = []
        for entry in self._storage.queue():
            payload = entry['payload']
            try:
                receipt = self._receipt(payload)
            except FrequencyError as error:
                # The server retires request IDs at an annual reset: there is
                # no old receipt to retrieve, and replay is forbidden.
                if error.code != 'revision-conflict': raise
                receipt = None
            if receipt is not None: self._storage.acknowledge(payload['requestId'])
            else: pending.append(payload['requestId'])
        if pending and not self._confirm_discard(): raise FrequencyError('CANCELLED')
        for request_id in pending: self._storage.acknowledge(request_id)
        with self._lock: self._code = None
        return self.public_status()

    def shutdown(self):
        self._stop.set()
        with self._lock:
            self._epoch += 1
            self._closed = True
            lease, self._lease = self._lease, None
        try:
            if self._operation.locked(): self._source.close()
            else: self._source.preserve_and_close(self._storage)
        except Exception:
            self._source.close()
        if lease:
            try: self._mutation('release', fencingToken=lease['fencingToken'], code='CLOSED')
            except Exception: pass
        if self._thread: self._thread.join(timeout=1)
