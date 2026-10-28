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
from .local_copy import content_hash, is_current, schedule_hash, unchanged_payload
from .manual_session import SessionError
from .protected_storage import ProtectedStorage, StorageError

SAFE_CODES = {'invalid-request', 'not-authorized', 'unavailable', 'revision-conflict', 'lease-busy',
              'lease-fenced', 'paused', 'source-invalid', 'identity-review', 'SOURCE_LOGIN_REQUIRED',
              'SOURCE_CLASS_UNAVAILABLE', 'SOURCE_CLASS_AMBIGUOUS', 'NO_SELECTED_CLASSES', 'NO_CLASSES_IN_SHIFT',
              'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT', 'QUEUE_REQUEST_CONFLICT',
              'ACCESS_REQUIRED', 'ACCESS_UNAVAILABLE', 'CANCELLED', 'SOURCE_LOGIN_FAILED',
              'CLASS_RECONCILIATION_REQUIRED', 'SOURCE_LIST_FILTERED', 'CENTER_CLASSES_REQUIRED', 'CLOCK_OUT_OF_SYNC',
              'PENDING_BATCHES', 'SOURCE_READ_FAILED', 'payload-required'}
# Problems an operator must see even with the window hidden in the tray.
ALERT_CODES = {'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED', 'CLASS_RECONCILIATION_REQUIRED', 'SOURCE_LIST_FILTERED',
               'CENTER_CLASSES_REQUIRED', 'NO_SELECTED_CLASSES', 'SOURCE_CLASS_UNAVAILABLE', 'lease-fenced',
               'revision-conflict', 'not-authorized', 'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT',
               'PENDING_BATCHES', 'CLOCK_OUT_OF_SYNC'}
LEASE_SECONDS = 300
# Same limit as the Ecossistema's frequencyScheduleV2 (recheck included).
MAX_DAILY_TIMES = 48
# Routine waits are not failures: a reserve computer or a school pause.
# NO_CLASSES_IN_SHIFT: a slot of a shift this school (or this PC's choice) has
# no linked class for. Nothing to do, and nothing wrong.
QUIET_CODES = {'lease-busy', 'paused', 'CANCELLED', 'NO_CLASSES_IN_SHIFT'}
# A network or Ecossistema blip (a PC waking up, Wi-Fi dropping) heals by itself
# at the next 30 s check; it reaches the history only if it lasts this long.
TRANSIENT_CODES = {'ACCESS_UNAVAILABLE', 'unavailable'}
TRANSIENT_GRACE_SECONDS = 600
# The weekly grid rarely changes: it is read at most this often, at the end of a collection run.
SCHEDULE_READ_SECONDS = 3600


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
                or not isinstance(rule['times'], list) or len(rule['times']) > MAX_DAILY_TIMES): raise FrequencyError('invalid-request')
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
        if len(times) + (1 if recheck is not None else 0) > MAX_DAILY_TIMES: raise FrequencyError('invalid-request')
    return copy.deepcopy(schedule)


# Positions of the Smecel diary that had a lesson: a point ("aula prevista/presença", given up to the
# capture), an absence (red X) or a justified absence (yellow icon or blue X). The calendar icon,
# "fora do período de matrícula" and blank positions never count as a lesson.
LESSON_STATES = frozenset({'planned_unknown', 'absent', 'excused_absent'})
# The whole local history (it keeps at most 2000 entries) when checking a mark was already logged.
MAX_HISTORY_SCAN = 2000


# How far around a day the class's marks still tell how many lessons that weekday has.
LESSON_EVIDENCE_DAYS = 28
# A whole-day absence covers at least this many lessons (school days have five or six).
WHOLE_DAY_MIN_LESSONS = 4


def lessons_per_day(records):
    """How many lessons each school day really had, from the whole class's diary.

    The Smecel shows six positions with a point on every school day, but a day of five lessons has
    no sixth lesson: in 2026 every class had its 6th lesson only on Tuesdays and Thursdays, and not
    one mark ever fell on a Monday, Wednesday or Friday 6th position (owner request 21/10/2026).

    Only direct evidence drops a position: on that day, or on the same weekday within four weeks
    either side, a student missed every lesson before it (from the first) but has no mark in it,
    and no student of the class has a mark in it. That is the whole-day absence of a five-lesson
    day ("XXXXX."). A position with any mark always counts. A day whose weekday has no mark at all
    nearby takes the class's most common answer; otherwise every position stays (None).
    """
    days, marked = set(), {}
    for record in records:
        if record['state'] in LESSON_STATES:
            days.add(record['date'])
        if record['state'] in ('absent', 'excused_absent'):
            marked.setdefault((record['date'], record['source_student_ref']), set()).add(record['lesson'])
    by_weekday = {}
    for (date, _), slots in marked.items():
        by_weekday.setdefault(datetime.fromisoformat(date).weekday(), []).append((date, slots))
    window = timedelta(days=LESSON_EVIDENCE_DAYS)
    counts, evidence = {}, {}
    for date in days:
        day = datetime.fromisoformat(date)
        near = [slots for other, slots in by_weekday.get(day.weekday(), ())
                if abs(datetime.fromisoformat(other) - day) <= window]
        evidence[date] = bool(near)
        used = set().union(*near) if near else set()
        # A student missed lessons 1..k and nothing else: lesson k+1, if nobody ever has a mark in
        # it there, did not happen.
        # At least four lessons missed: a late arrival (missed only 1..2) is never read as the day.
        phantom = [max(slots) + 1 for slots in near
                   if len(slots) >= WHOLE_DAY_MIN_LESSONS and slots == set(range(1, max(slots) + 1))
                   and max(slots) < 6 and max(slots) + 1 not in used]
        counts[date] = min(phantom) - 1 if phantom else None
    known = [n for n in counts.values() if n is not None]
    typical = max(sorted(set(known)), key=known.count) if known else None
    return {date: (n if n is not None or evidence[date] else typical) for date, n in counts.items()}


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
    # The same name twice in a class (two enrolments of one student) is told apart by its ordinal.
    # The Smecel page may swap the two cards between captures, so the ordinal follows each card's
    # lesson period (first, then last lesson date), not its position on the page; the position only
    # breaks a tie. Otherwise every capture moved all their days from one card to the other
    # (owner request 21/10/2026).
    period = {}
    for record in snapshot['records']:
        if record['state'] in LESSON_STATES:
            first, last = period.get(record['source_student_ref'], (record['date'], record['date']))
            period[record['source_student_ref']] = (min(first, record['date']), max(last, record['date']))
    order = {s['source_student_ref']: index for index, s in enumerate(students)}
    def stable(student):
        first, last = period.get(student['source_student_ref'], ('9999-12-31', '9999-12-31'))
        return (first, last, order[student['source_student_ref']])
    for student in sorted(students, key=stable):
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
    marks, coverage, unresolved_days = [], {}, set()
    cutoff = datetime.fromtimestamp(stamp(capture['captured_at']), ZoneInfo(timezone_name)).date().isoformat()
    day_lessons = lessons_per_day(snapshot['records'])
    for record in snapshot['records']:
        if record['date'] > cutoff: continue
        state = record['state']
        if state not in LESSON_STATES and state != 'unknown': continue
        if record['source_student_ref'] not in keys or not 1 <= record['lesson'] <= 6: raise FrequencyError('source-invalid')
        key = keys[record['source_student_ref']]
        # A point past the day's last real lesson (the "6th lesson" of a five-lesson day) is no lesson.
        last = day_lessons.get(record['date'])
        if state == 'planned_unknown' and last is not None and record['lesson'] > last: continue
        if state == 'unknown':
            # A position without a confirmed meaning: the day is sent, but never as complete.
            unresolved_days.add((key, record['date']))
            continue
        # Lesson days (owner decision 20/10/2026): every position of the Smecel diary with a lesson
        # (a point, an X or a justified mark) up to the capture, so 5- or 6-lesson days, weekends,
        # holidays (calendar icon) and days outside the enrolment need no configuration.
        coverage.setdefault((key, record['date']), set()).add(record['lesson'])
        if state in ('absent', 'excused_absent'):
            marks.append({'recordKey': key, 'date': record['date'], 'slot': record['lesson'],
                          'mark': 'X' if state == 'absent' else 'J'})
    version = hashlib.sha256(canonical_frequency({'academicYear': 2026, 'sourceClassId': source_class['class_id'],
        'observedAt': capture['captured_at'], 'htmlSha256': capture['html_sha256'], 'parserVersion': 'smecel-annual-v3'})).hexdigest()
    return {'operation': 'collect', 'academicYear': 2026, 'requestId': request_id, 'fencingToken': fencing,
            'classId': server_class['classId'], 'expectedRevision': server_class['revision'],
            'sourceVersion': 'sha256:' + version, 'sourceClassId': source_class['class_id'],
            'sourceClassLabel': source_class['name'], 'observedAt': capture['captured_at'], 'rosterComplete': False,
            'records': records, 'marks': marks,
            'coverage': [{'recordKey': k, 'date': d, 'slots': sorted(slots), 'complete': (k, d) not in unresolved_days}
                         for (k, d), slots in sorted(coverage.items())]}


class FrequencyRuntime:
    def __init__(self, access, provider, source, directory=None, *, storage=None, clock=time.time,
                 on_started=lambda: None, on_finished=lambda failed: None, confirm_discard=discard_confirmation,
                 history=None, on_alert=lambda code: None):
        self._access, self._provider, self._source, self._clock = access, provider, source, clock
        self._storage = storage or ProtectedStorage(directory, clock=clock)
        self._history = history or CollectorHistory(self._storage.directory.parent, clock=clock)
        self._on_alert = on_alert
        self._lock = threading.RLock()
        self._bracket = threading.local()
        self._operation = threading.Lock()
        self._epoch = 0
        self._active, self._paused, self._closed = False, False, False
        self._exiting = False  # An update asked the app to quit: start nothing new.
        self._school_paused = False
        self._confirm_discard = confirm_discard
        self._state, self._code = 'connect', None
        self._transient = None  # (code, first seen, already in history)
        self._status, self._lease, self._class, self._last_receipt = None, None, None, None
        self._progress = {'completed': 0, 'total': 0, 'classLabel': None}
        self._minute = None
        self._fired = set()
        self._pending_slots, self._last_schedule = set(), None
        self._stale = {}  # Fenced, uncommitted batches by source class (see _drain).
        self._schedule_read_at = None  # When the weekly grid was last read (this session).
        self._source_blocked = False
        # Shifts of a run whose Smecel session expired, read again at the next tick with the saved
        # login (owner request 23/10/2026: never wait for the next slot). Once per failed run.
        self._login_retry = None
        self._login_missed = set()  # Slots that passed while waiting for someone to sign in.
        self._last_tick = 0
        self._thread = None
        self._stop = threading.Event()
        self._on_started, self._on_finished = on_started, on_finished

    def _request(self, payload):
        if getattr(self._bracket, 'active', False):
            return self._provider.frequency_request(payload)
        return self._access.run(lambda: self._provider.frequency_request(payload))

    def _verified(self, work):
        """Run consecutive steps inside ONE access bracket on this thread.

        Every bracket is still opened and closed by a fresh online verification
        with the same identity, as a single access.run. Only the duplicate
        checks between back-to-back steps disappear. Other threads (heartbeat)
        keep their own brackets; transmissions stay outside this one."""
        def bracketed():
            self._bracket.active = True
            try: return work()
            finally: self._bracket.active = False
        return self._access.run(bracketed)

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
            server_time = stamp(value['serverTime'])
            received_at = self._clock()
            # For a synchronized client the server's timestamp must lie
            # between local request start and response reception (allow 5s).
            # This catches both signs of Windows clock drift without treating
            # ordinary network latency as clock drift.
            if server_time < requested_at - 5 or server_time > received_at + 5:
                raise FrequencyError('CLOCK_OUT_OF_SYNC')
            settings = value['settings']
            if type(settings['revision']) is not int or settings['revision'] < 0 or type(settings['paused']) is not bool: raise ValueError()
            if settings['schedule'] is not None: validate_schedule(settings['schedule'])
            for c in value['classes']:
                if (type(c['classId']) is not int or c['classId'] < 1 or type(c['revision']) is not int
                        or c['revision'] < 0 or not label(c['sourceClassLabel'])): raise ValueError()
        except (KeyError, ValueError, TypeError): raise FrequencyError('unavailable') from None
        # Internal-only metadata; never exposed through the desktop bridge.
        value['_request_started_at'] = requested_at
        # Status is proof-bound to the current generation. An unreceipted
        # queue encrypted for the previous generation must not be silently
        # erased or used as if it belonged to the new one.
        self._bind_storage()
        with self._lock:
            self._status = value
            self._school_paused = value['settings']['paused']
            # The Ecossistema answered: a "no connection" notice left by an earlier attempt (the
            # computer woke up before its network) no longer holds until the next scheduled time.
            if self._code == 'ACCESS_UNAVAILABLE' and self._state == 'reserve':
                self._code = None
                self._transient = None
            # Its time agrees with this computer's: a clock notice left by an earlier check no
            # longer holds once the Windows clock is fixed, and the collector waits again.
            elif self._code == 'CLOCK_OUT_OF_SYNC':
                self._state, self._code = 'reserve', None
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
        # No network for a moment is a wait, not a fault: the collector retries
        # by itself, so every consumer (tray, window, fox, snapshot) sees 'reserve'.
        if code in {'lease-busy', 'NO_CLASSES_IN_SHIFT', 'ACCESS_UNAVAILABLE'}: return 'reserve'
        if code in {'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED'}: return 'login-required'
        if code in {'paused', 'CANCELLED'}: return 'paused'
        return 'error'

    def _error(self, error, label=None):
        code = getattr(error, 'code', 'unavailable')
        if isinstance(error, SessionError):
            # A diary that failed after the list was validated is a read
            # problem, retried at the next time; anything else asks for login.
            code = str(error) if str(error) in {'SOURCE_LOGIN_FAILED', 'SOURCE_READ_FAILED'} else 'SOURCE_LOGIN_REQUIRED'
        if code not in SAFE_CODES: code = 'unavailable'
        # With a saved Smecel login an expired session is retried at the next
        # scheduled time. A refused password or no saved login waits for a person.
        blocks_source = code == 'SOURCE_LOGIN_FAILED' or (
            code == 'SOURCE_LOGIN_REQUIRED' and self._storage.load_credential() is None)
        with self._lock:
            changed = self._code != code
            interrupted_run = self._state == 'collecting'
            self._code = code
            if blocks_source: self._source_blocked = True
            self._state = self._state_for(code)
            if code in {'lease-fenced', 'not-authorized', 'paused'}: self._lease = None
        if code in TRANSIENT_CODES and not interrupted_run:
            now = self._clock()
            if changed or self._transient is None or self._transient[0] != code:
                self._transient = (code, now, False)
            if not self._transient[2] and now - self._transient[1] >= TRANSIENT_GRACE_SECONDS:
                self._transient = (code, self._transient[1], True)
                self._history.record('failure', code=code, label=label)
        elif code not in QUIET_CODES and changed: self._history.record('failure', code=code, label=label)
        if code in ALERT_CODES and changed:
            try: self._on_alert(code)
            except Exception: pass

    def public_status(self):
        count = getattr(self._source, 'saved_class_count', None)
        try: selected = count() if count else None
        except Exception: selected = None
        with self._lock:
            return {'selectedClasses': selected, 'classesMode': 'all' if selected is None and count else 'chosen',
                    'state': self._state, 'code': self._code, 'active': self._active, 'localPaused': self._paused,
                    'persistent': self._storage.persistent, 'progress': dict(self._progress),
                    'credential': self._storage.credential_status(),
                    'lastReceipt': self._last_receipt,
                    # Status shown locally contains operational settings only.
                    'settings': copy.deepcopy(self._status['settings']) if self._status else None}

    def refresh(self):
        self._fresh()
        return self.public_status()

    def _bind_storage(self):
        # A synthetic/unconfigured access port has no native device provider.
        # It cannot authorize collection; only a real provider supplies a
        # generation against which protected storage can be bound.
        if self._provider is None: return
        try:
            binding = self._provider.storage_binding()
        except AccessDenied:
            return  # Not yet paired; no storage authority is available.
        self._storage.bind(*binding)  # Pending batches and corruption MUST propagate.
        # Bound with the live generation and still undecryptable: an older
        # generation's queue that nothing can receipt. Set aside, kept and logged,
        # so collection continues without anyone discarding it by hand.
        if self._storage.quarantine_unreadable_queue():
            self._history.record('queue-quarantined')
        restored, self._storage.restored = self._storage.restored, 0
        if restored: self._history.record('queue-restored', sent=restored)

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
        # The server's maximum: a slow network (several seconds per request) must
        # not let one class outlive its concession and fence the whole run.
        request = {'operation': 'lease', 'academicYear': 2026, 'requestId': str(uuid.uuid4()), 'durationSeconds': LEASE_SECONDS}
        requested_at = self._clock()
        reply = self._committed(self._request(request), request)
        if type(reply.get('fencingToken')) is not int or reply['fencingToken'] < 1: raise FrequencyError('unavailable')
        # The database issues exactly the requested lease *after*
        # this request begins. A deadline based on the request start is a safe
        # lower bound even when the preceding status or network is slow. Do not
        # infer the full lease of freshness from the time the reply arrived.
        if stamp(reply['expiresAt']) <= stamp(status['serverTime']): raise FrequencyError('lease-fenced')
        deadline = requested_at + LEASE_SECONDS - 2
        if deadline <= self._clock(): raise FrequencyError('lease-fenced')
        with self._lock:
            self._lease = {**reply, 'deadline': deadline}
            if self._source_blocked: self._state, self._code = 'login-required', 'SOURCE_LOGIN_REQUIRED'
            elif self._code not in {None, 'lease-busy', 'unavailable', 'CANCELLED', 'paused'}: self._state = 'error'
            # Each class renews the lease: a run in progress stays 'collecting', so the window keeps
            # its progress bar and the heartbeat reports the run (21/10/2026: it showed 'ready').
            elif self._state == 'collecting': self._code = None
            else: self._state, self._code = 'ready', None

    def _has_saved_selection(self):
        # This is only a cheap negative readiness check. A persisted choice is
        # never authorization to collect: operational_catalog revalidates it
        # against the live Smecel class list before any source capture.
        check = getattr(self._source, 'has_saved_class_selection', None)
        return check() if check is not None else True

    def _release_if_ineligible(self, status=None):
        """Yield an owned school lease on a known local blocker or empty agenda.

        Use the server's current token rather than a possibly expired cached
        token. If network access fails, the server TTL remains the safe fallback.
        A foreign device's lease must never be touched.
        """
        try:
            if status is None: status = self._fresh()
            lease = status.get('lease')
            if lease is not None and lease.get('deviceId') == self._provider.storage_binding()[0]:
                self._mutation('release', fencingToken=lease['fencingToken'], code='NOT_READY')
        except Exception:
            pass  # Safe fallback is expiry; never mask the actionable blocker.
        finally:
            with self._lock: self._lease = None

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
            if self._closed or self._exiting or not self._active or self._paused: return
            epoch = self._epoch
        if self._operation.locked():
            self._note_busy_slot()
            return
        status = self._fresh()
        if status['settings']['paused']:
            self.cancel(purge=False, school_pause=True)
            return
        if self._code == 'CENTER_CLASSES_REQUIRED' and status['classes']:
            with self._lock: self._code, self._state = None, 'reserve'
        schedule = status['settings']['schedule']
        self._last_schedule = schedule
        # A device with no executable agenda or a known source blocker must
        # not monopolise the school lease. Eligible leaders still heartbeat
        # every 30 s so that the admin sees connected/standby computers.
        if schedule is None or not any(
            r['enabled'] and (r['times'] or r['recheck']) for r in schedule['rules']
        ):
            self._pending_slots = set()  # An emptied agenda cancels delayed slots.
            self._release_if_ineligible(status)
            return
        if not status['classes']:
            self._error(FrequencyError('CENTER_CLASSES_REQUIRED'))
            self._release_if_ineligible(status)
            return
        if not self._has_saved_selection():
            self._error(FrequencyError('NO_SELECTED_CLASSES'))
            self._release_if_ineligible(status)
            return
        if self._code == 'NO_SELECTED_CLASSES':
            self.source_ready()
        retry, self._login_retry = self._login_retry, None
        if retry is not None and not self._source_blocked:
            # The previous run met an expired Smecel session and a login is saved: read again now.
            if not self._operation.acquire(blocking=False): return
            self._history.record('login-retry')
            def run_retry():
                try: self.collect(retry['shifts'], _claimed=True, _retry=True)
                finally: self._operation.release()
            threading.Thread(target=run_retry, daemon=True, name='collector-capture').start()
            return
        # An expired session with a saved login is not a blocker: the next slot signs in again.
        blockers = {'SOURCE_LOGIN_FAILED', 'NO_SELECTED_CLASSES',
                    'CENTER_CLASSES_REQUIRED', 'SOURCE_CLASS_UNAVAILABLE',
                    'SOURCE_CLASS_AMBIGUOUS', 'source-invalid', 'identity-review',
                    'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT', 'PENDING_BATCHES'}
        if self._source_blocked or self._code in blockers:
            # Slots missed while waiting for someone to sign in run once, right after the login.
            if self._source_blocked:
                before = set(self._pending_slots)
                self._note_busy_slot()
                self._login_missed |= self._pending_slots - before
            self._release_if_ineligible(status)
            return
        # A school-wide lease is reserved only by collect(), after verifying
        # real Smecel selections intersect the currently scheduled shifts.
        # Keeping one while idle would starve a PC responsible for another
        # shift, even if this machine has unrelated saved classes.
        self._release_if_ineligible(status)
        now = datetime.fromtimestamp(self._clock(), ZoneInfo(schedule['timezone']))
        minute = now.strftime('%Y-%m-%dT%H:%M%z')
        if minute == self._minute: return
        self._minute = minute  # No replay after sleep/offline, including DST.
        civil_day, wall_time = now.date().isoformat(), now.strftime('%H:%M')
        oldest = (now.date() - timedelta(days=7)).isoformat()
        self._fired = {key for key in self._fired if key[0] >= oldest}
        shifts = {r['shift'] for r in schedule['rules'] if r['enabled'] and r['weekday'] == (now.weekday() + 1) % 7
                  and wall_time in [*r['times'], r['recheck']] and (civil_day, r['shift'], wall_time) not in self._fired}
        keys = {(civil_day, shift, wall_time) for shift in shifts}
        # Slots that came while a long collection was still running run once,
        # coalesced, right after it ends (never in parallel, never after sleep).
        # Each delayed slot must still exist in the agenda as it is now: an
        # edited, removed or disabled time is cancelled, not run.
        today = (now.weekday() + 1) % 7
        live = {(r['shift'], t) for r in schedule['rules'] if r['enabled'] and r['weekday'] == today
                for t in [*r['times'], *([r['recheck']] if r['recheck'] else [])]}
        pending = {k for k in self._pending_slots if k not in self._fired}
        late = {k for k in pending if k[0] == civil_day and (k[1], k[2]) in live}
        cancelled = pending - late
        self._pending_slots = set()
        if cancelled:
            self._history.record('late-cancelled', label=', '.join(sorted({k[2] for k in cancelled})))
        if late:
            shifts |= {k[1] for k in late}; keys |= late
            kind = 'login-catch-up' if late & self._login_missed else 'late-start'
            self._history.record(kind, label=', '.join(sorted({k[2] for k in late})))
        self._login_missed &= self._pending_slots
        if shifts:
            # lease-fenced and revision-conflict are NOT blockers: a fenced batch
            # waits for a confirmed re-read and the next status carries the new
            # class revision, so the next slot heals them without anyone.
            if self._source_blocked or self._code in {'source-invalid',
                   'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT', 'SOURCE_CLASS_UNAVAILABLE',
                   'SOURCE_CLASS_AMBIGUOUS', 'identity-review'}: return
            if not self._operation.acquire(blocking=False):
                self._pending_slots |= late
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

    def _note_unknown_marks(self, preview, class_label):
        """One log entry per unknown Smecel mark, ever: which mark it is and where it was first seen.

        The position is not counted until the collector learns the mark (owner request 20/10/2026);
        the same mark in other classes or later collections is not logged again.
        """
        symbols = sorted({r.get('source_symbol') or 'icon:unrecognized'
                          for r in preview['snapshot']['records'] if r['state'] == 'unknown'})
        if not symbols: return
        seen = {e.get('code') for e in self._history.recent(MAX_HISTORY_SCAN) if e['kind'] == 'unknown-mark'}
        for symbol in symbols:
            if symbol not in seen: self._history.record('unknown-mark', code=symbol, label=class_label)

    def _note_busy_slot(self):
        """Remember a scheduled minute that found the previous collection busy."""
        schedule = self._last_schedule
        if not schedule: return
        now = datetime.fromtimestamp(self._clock(), ZoneInfo(schedule['timezone']))
        civil_day, wall_time = now.date().isoformat(), now.strftime('%H:%M')
        for r in schedule['rules']:
            if (r['enabled'] and r['weekday'] == (now.weekday() + 1) % 7 and wall_time in [*r['times'], r['recheck']]
                    and (civil_day, r['shift'], wall_time) not in self._fired):
                self._pending_slots.add((civil_day, r['shift'], wall_time))

    def collect(self, shifts=None, *, _claimed=False, _retry=False):
        # A scheduled invocation already owns the operation lock so its minute
        # cannot be marked fired before a capture is accepted.
        if not _claimed and not self._operation.acquire(blocking=False): return self.public_status()
        if self._exiting:
            # The installer is replacing the program: no capture starts now.
            if not _claimed: self._operation.release()
            return self.public_status()
        self._on_started()
        heartbeat_stop = threading.Event()
        heartbeat, started = None, False
        try:
            with self._lock:
                epoch = self._epoch
                if not self._active or self._paused: raise FrequencyError('CANCELLED')
            status = self._fresh()
            self._reconcile_receipts(epoch)
            # Ineligible devices do not take the school-wide lease from a
            # healthy standby collector just to discover a known blocker.
            if not status['classes']: raise FrequencyError('CENTER_CLASSES_REQUIRED')
            if not self._has_saved_selection(): raise FrequencyError('NO_SELECTED_CLASSES')
            if self._source_blocked: raise SessionError('SOURCE_LOGIN_REQUIRED')
            # Discover first. A saved ID without a class of the requested
            # shift must never acquire the school lease from an eligible PC.
            catalog = self._access.run(lambda: self._source.operational_catalog(self._storage))
            self._check(epoch, lease=False)  # No lease is owned until eligibility is confirmed.
            selected = set(catalog['selected_class_ids'])
            sources = [c for c in catalog['catalog']['classes'] if c['class_id'] in selected]
            if catalog['unavailable_class_ids']: raise FrequencyError('SOURCE_CLASS_UNAVAILABLE')
            if not sources: raise FrequencyError('NO_SELECTED_CLASSES')
            pairs, unmatched = self._pair_classes(sources, status['classes'], shifts)
            if not pairs:
                # Zero coverage cannot be a successful scheduled window and
                # must not consume another computer's school leadership. It is
                # not a blocker either: the next slot (other shift) still runs.
                if unmatched:
                    error = FrequencyError('CLASS_RECONCILIATION_REQUIRED')
                    error.label = ', '.join(unmatched)
                    raise error
                raise FrequencyError('NO_CLASSES_IN_SHIFT')
            self._acquire(status)
            self._check(epoch)
            self._drain(epoch)
            with self._lock:
                self._state, self._code = 'collecting', None
                self._progress = {'completed': 0, 'total': len(pairs), 'classLabel': None}
            self._history.record('collection-started', sent=len(pairs))
            started = True
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
                def read_class(source=source, central=central):
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
                    try:
                        preview = self._source.operational_capture(source['class_id'])
                    except SessionError:
                        # The list was just validated: a failed diary is a read
                        # problem (shown as such), not a reason to ask for login.
                        raise SessionError('SOURCE_READ_FAILED') from None
                    self._check(epoch, lease=False)
                    after_capture = self._fresh()
                    if after_capture['settings']['paused']: raise FrequencyError('paused')
                    if self._lease is None or self._lease['deadline'] <= self._clock():
                        self._acquire(after_capture, force=True)
                        self._check(epoch)
                    return current, preview, after_capture
                # Status, concession, source read and the post-read status share
                # one verified bracket; the transmission below opens its own.
                read_started = time.monotonic()
                current, preview, after_capture = self._verified(read_class)
                send_started = time.monotonic()
                school_zone = (after_capture['settings']['schedule'] or {'timezone': 'America/Bahia'})['timezone']
                payload = collection_payload(preview, source, current, self._lease['fencingToken'], str(uuid.uuid4()), school_zone)
                self._note_unknown_marks(preview, source['name'])
                del preview
                self._deliver(payload, epoch, school_zone)
                self._supersede(source['class_id'])
                with self._lock:
                    self._progress['completed'] += 1
                    receipt = dict(self._last_receipt or {})
                self._history.record('class-sent', label=source['name'], sent=receipt.get('resolvedRecords'),
                                     unresolved=receipt.get('unresolvedRecords'), conflicts=receipt.get('conflicts'),
                                     read_ms=round((send_started - read_started) * 1000),
                                     send_ms=round((time.monotonic() - send_started) * 1000))
            self._check(epoch)
            self._collect_schedule(epoch, catalog, status, (status['settings']['schedule'] or {'timezone': 'America/Bahia'})['timezone'])
            self._access.run(lambda: self._source.preserve_and_close(self._storage))
            with self._lock:
                self._state, self._class = 'ready', None
                self._progress['classLabel'] = None
            # The outcome is decided before the closing fact, so the history shows
            # a run with a pending alert as such, never as a clean success.
            closing = ('CLASS_RECONCILIATION_REQUIRED' if unmatched else
                       # "Todas" promises the whole school: a filtered or partial
                       # Smecel list must not look complete.
                       'SOURCE_LIST_FILTERED' if catalog.get('all_classes') and catalog['catalog'].get('filtered') else None)
            self._history.record('collection-finished', sent=len(pairs), code=closing)
            if closing:
                self._error(FrequencyError(closing), label=', '.join(unmatched) if unmatched else None)
            return self.public_status()
        except Exception as error:
            self._error(error, label=getattr(error, 'label', None))
            code = getattr(error, 'code', None)
            if not _retry and self._code == 'SOURCE_LOGIN_REQUIRED' and not self._source_blocked:
                with self._lock: self._login_retry = {'shifts': shifts}
            if started and code in QUIET_CODES:
                # A run stopped by a pause, a school pause or another PC's lease
                # still gets a closing fact (other codes are recorded as failures),
                # so the history never shows it running forever.
                self._history.record('collection-stopped', code=code)
            if getattr(error, 'code', None) in {
                'NO_SELECTED_CLASSES', 'NO_CLASSES_IN_SHIFT', 'CLASS_RECONCILIATION_REQUIRED',
                'SOURCE_CLASS_UNAVAILABLE', 'SOURCE_CLASS_AMBIGUOUS',
                'CENTER_CLASSES_REQUIRED', 'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED',
                'PROTECTED_STORAGE_UNAVAILABLE', 'PROTECTED_STORAGE_LIMIT', 'PENDING_BATCHES', 'source-invalid',
                'identity-review', 'revision-conflict',
            } or isinstance(error, SessionError):
                self._release_if_ineligible()
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
        entries = self._storage.queue()
        expired = self._storage.take_expired()
        if expired: self._history.record('queue-expired', sent=expired)
        for entry in entries:
            self._check(epoch, lease=False)
            payload = entry['payload']
            result = self._receipt(payload)
            if result is not None: self._storage.acknowledge(payload['requestId'])

    def _deliver(self, payload, epoch, zone):
        """Send the class's diary only when it changed (owner decision 22/10/2026).

        The copy of what this computer last sent says whether the diary is the same; then only the
        short message goes (students and the content's hash, every guard of a collection kept). The
        server compares with what it holds and may answer 'payload-required' (its data was restored,
        a student's link changed in the Centro...): then, and whenever there is no usable copy
        (formatted or restored PC, cleared data), the whole diary goes as before, through the
        protected queue, and the copy is replaced with it. Each class still goes in full once a day."""
        key = 'frequency-' + payload['sourceClassId']
        digest = content_hash(payload)
        today = datetime.fromtimestamp(self._clock(), ZoneInfo(zone)).date().isoformat()
        copy = self._load_copy(key)
        if is_current(copy, payload, digest, today):
            try:
                self._send(unchanged_payload(payload, digest, str(uuid.uuid4())), epoch, queued=False)
                return
            except FrequencyError as error:
                if error.code != 'payload-required': raise
        with self._lock:
            self._check(epoch)
            self._storage.enqueue(payload)
        self._send(payload, epoch)
        self._save_copy(key, {'classId': payload['classId'], 'sourceClassId': payload['sourceClassId'],
                              'contentHash': digest, 'fullOn': today,
                              'content': {field: payload[field] for field in
                                          ('sourceClassLabel', 'rosterComplete', 'records', 'coverage', 'marks')}})

    def _collect_schedule(self, epoch, catalog, status, zone):
        """The school's weekly grid for the Portal's "Horário" (owner decision 22/10/2026).

        Read at most hourly, in the same verified session and under the same lease as the diaries.
        Sent only when a class's grid differs from the local copy, or once a day; the server keeps a
        version per change and only freshness otherwise. Each grid goes with the class's Smecel id
        (the frequency's), matched to the Centro through the class list like the diaries. A failure
        here never fails the frequency run: the grid is tried again at the next run."""
        now = self._clock()
        if self._schedule_read_at is not None and now - self._schedule_read_at < SCHEDULE_READ_SECONDS: return
        try:
            def read():
                self._check(epoch, lease=False)
                return self._source.operational_schedule()
            # Read and compare first; the lease is taken again only when there is something to send.
            grids = self._verified(read)
            self._schedule_read_at = now
            pairs, _ = self._pair_classes(catalog['catalog']['classes'], status['classes'], None)
            items = [{'classId': central['classId'], 'sourceClassId': source['class_id'],
                      'sourceClassLabel': source['name'], 'lessons': grids[source['class_id']]['lessons']}
                     for source, central in pairs if source['class_id'] in grids]
            if not items: return
            today = datetime.fromtimestamp(now, ZoneInfo(zone)).date().isoformat()
            hashes = {str(item['classId']): schedule_hash(item) for item in items}
            copy = self._load_copy('schedule')
            if isinstance(copy, dict) and copy.get('hashes') == hashes and copy.get('sentOn') == today: return
            observed = datetime.fromtimestamp(now, timezone.utc).isoformat()
            version = hashlib.sha256(canonical_frequency({'academicYear': 2026, 'observedAt': observed,
                                                          'grids': hashes})).hexdigest()
            def lease():
                fresh = self._fresh()
                if fresh['settings']['paused']: raise FrequencyError('paused')
                if self._lease is None or self._lease['deadline'] <= self._clock(): self._acquire(fresh, force=True)
                self._check(epoch)
            self._verified(lease)
            payload = {'operation': 'schedule-collect', 'academicYear': 2026, 'requestId': str(uuid.uuid4()),
                       'fencingToken': self._lease['fencingToken'], 'sourceVersion': 'sha256:' + version,
                       'observedAt': observed, 'classes': items}
            reply = self._committed(self._request(payload), payload)
            changed = [c for c in reply.get('classes') or [] if isinstance(c, dict) and c.get('changed') is True]
            self._save_copy('schedule', {'hashes': hashes, 'sentOn': today, 'classes': items})
            self._history.record('schedule-sent', sent=len(changed))
        except Exception as error:
            # A stop, a pause or a lost authority (the institutional access itself, or the Ecossistema's
            # answer) stops the run as anywhere else; any other problem with the grid is only noted,
            # and the frequency already sent stands. FrequencyError is an AccessDenied too.
            code = getattr(error, 'code', None)
            if type(error) is AccessDenied or code in {'CANCELLED', 'paused', 'lease-fenced', 'not-authorized'}: raise
            self._history.record('failure', code=code if code in SAFE_CODES else 'SOURCE_READ_FAILED',
                                 label='Grade de horários')

    def _load_copy(self, key):
        try: return self._storage.load_copy(key)
        except StorageError: return None

    def _save_copy(self, key, value):
        # A copy that cannot be written only costs a whole diary next time; never a failed run.
        try: self._storage.save_copy(key, value)
        except StorageError: pass

    def _send(self, payload, epoch, queued=True):
        # Every attempt has the identical payload/requestId and a new challenge.
        # A timeout is reconciled before a bounded retry, never called success.
        # `queued`: the payload waits in the protected queue (a whole diary); the short message of
        # an unchanged diary does not, since losing it costs nothing but the next run.
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
        if queued: self._storage.acknowledge(payload['requestId'])
        with self._lock:
            self._last_receipt = {k: result[k] for k in ('receivedAt', 'resolvedRecords', 'unresolvedRecords', 'conflicts')}

    def _drain(self, epoch):
        """Send what the current grant can still deliver. A batch from an older
        concession that the server confirms it never committed (no receipt)
        stays protected until a fresh read of the same class is confirmed, so a
        failed re-read never loses the previous observation."""
        self._stale = {}
        for entry in self._storage.queue():
            self._check(epoch)
            payload = entry['payload']
            receipt = self._receipt(payload)
            if receipt is not None:
                self._storage.acknowledge(payload['requestId'])
                continue
            # Never rewritten or re-signed: it is superseded by this run's
            # confirmed re-read (see _supersede), so nobody discards it by hand.
            if payload.get('fencingToken') != self._lease['fencingToken']:
                self._stale.setdefault(payload.get('sourceClassId'), []).append(payload)
                continue
            self._send(payload, epoch)

    def _supersede(self, source_class_id):
        """Drop a stale batch only after a fresh read of the same class has a
        server receipt. Absence from this run (other shift, unselected,
        unmatched or filtered list) proves nothing, so those stay protected."""
        stale = self._stale
        for payload in stale.pop(source_class_id, []):
            self._storage.acknowledge(payload['requestId'])
            self._history.record('superseded', label=payload.get('sourceClassLabel'))

    def save_settings(self, expected_revision, schedule):
        validate_schedule(schedule)
        if type(expected_revision) is not int or expected_revision < 0: raise FrequencyError('invalid-request')
        self._mutation('save-settings', expectedRevision=expected_revision, schedule=schedule)
        return self.refresh()

    def source_ready(self):
        with self._lock:
            self._source_blocked = False
            if self._code in {'SOURCE_LOGIN_REQUIRED', 'SOURCE_LOGIN_FAILED',
                              'NO_SELECTED_CLASSES', 'SOURCE_CLASS_UNAVAILABLE'}:
                self._state, self._code = 'reserve', None

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
            self._pending_slots = set()  # A pause never leaves a delayed run behind.
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

    def finish_for_exit(self, timeout):
        """Update request: start no new collection and wait for the one in flight.

        Returns False when it is still running after timeout; the caller then
        quits anyway and shutdown() cancels it cooperatively (lease released).
        """
        with self._lock: self._exiting = True
        if not self._operation.acquire(timeout=timeout): return False
        self._operation.release()
        return True

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
