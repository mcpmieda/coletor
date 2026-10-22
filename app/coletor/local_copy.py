"""What this computer last sent, to skip a send when nothing changed (owner decision 22/10/2026).

The hashes are the Ecossistema's own (frequencyContentHashV2 and frequencyScheduleHashV2 in
shared/attendance-contracts/frequency-v2.ts): canonical JSON, SHA-256, base64url without padding.
The same reference values are pinned on both sides (tests/attendance/content-hash-v2.test.ts there,
tests/test_local_copy.py here). The local copy only decides whether to try the short message; the
server still compares with what it holds and asks for the whole diary when anything differs.
"""
import base64
import hashlib

from .device_provider import canonical_frequency

# The fields of a `collect` the server's content hash covers, in its own terms.
CONTENT_FIELDS = ('classId', 'sourceClassId', 'sourceClassLabel', 'rosterComplete', 'records', 'coverage', 'marks')
# A `collect` without coverage and marks is the short message's body.
UNCHANGED_FIELDS = ('academicYear', 'fencingToken', 'classId', 'expectedRevision', 'sourceVersion', 'sourceClassId',
                    'sourceClassLabel', 'observedAt', 'rosterComplete', 'records')


def payload_hash(value):
    """frequencyPayloadHashV2: the same bytes in Python and JavaScript."""
    return base64.urlsafe_b64encode(hashlib.sha256(canonical_frequency(value)).digest()).decode('ascii').rstrip('=')


def content_hash(payload):
    """frequencyContentHashV2 of a `collect` payload: the class's diary, not when or by whom it was read."""
    return payload_hash({field: payload[field] for field in CONTENT_FIELDS})


def schedule_hash(item):
    """frequencyScheduleHashV2 of one class's weekly grid; the lessons' order does not matter."""
    lessons = sorted(item['lessons'], key=lambda lesson: (lesson['weekday'], lesson['slot']))
    return payload_hash({'classId': item['classId'], 'sourceClassId': item['sourceClassId'],
                         'sourceClassLabel': item['sourceClassLabel'], 'lessons': lessons})


def unchanged_payload(payload, digest, request_id):
    """The short message for an unchanged diary: every guard of the collection, no coverage or marks."""
    return {'operation': 'collect-unchanged', 'requestId': request_id,
            **{field: payload[field] for field in UNCHANGED_FIELDS}, 'contentHash': digest}


def is_current(copy, payload, digest, today):
    """The short message is tried only for the same class and content, and only after a whole diary
    of this class was confirmed today: once a day every class still goes in full, a safety net
    should the copy and the server ever disagree without the server noticing."""
    return (isinstance(copy, dict) and copy.get('classId') == payload['classId']
            and copy.get('sourceClassId') == payload['sourceClassId']
            and copy.get('contentHash') == digest and copy.get('fullOn') == today)
