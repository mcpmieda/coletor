"""The hashes shared with the Ecossistema and the short message for an unchanged diary."""
import unittest

from coletor.local_copy import content_hash, is_current, schedule_hash, unchanged_payload

# The same reference values as tests/attendance/content-hash-v2.test.ts in the Ecossistema: if one
# side changes alone, every collection goes in full (safe, but the saving is lost).
CONTENT = {
    'classId': 7, 'sourceClassId': '13331', 'sourceClassLabel': '6A 2026 - MATUTINO', 'rosterComplete': True,
    'records': [{'recordKey': 'source:a', 'originalName': 'JOÃO DA CONCEIÇÃO', 'originalClass': '6A 2026 - MATUTINO'},
                {'recordKey': 'source:b', 'originalName': 'ÁGATA ÑANDU', 'originalClass': '6A 2026 - MATUTINO'}],
    'coverage': [{'recordKey': 'source:a', 'date': '2026-10-20', 'slots': [1, 2, 3, 4, 5, 6], 'complete': True},
                 {'recordKey': 'source:b', 'date': '2026-10-20', 'slots': [1, 2, 3, 4, 5, 6], 'complete': False}],
    'marks': [{'recordKey': 'source:a', 'date': '2026-10-20', 'slot': 2, 'mark': 'X'}],
}
SCHEDULE = {'classId': 7, 'sourceClassId': '13331', 'sourceClassLabel': '6A 2026 - MATUTINO',
            'lessons': [{'weekday': 2, 'slot': 1, 'subject': 'CIENCIAS'},
                        {'weekday': 1, 'slot': 1, 'subject': 'ATIVIDADE DE VIDA DIÁRIA / PRÁTICA'}]}


class LocalCopyTests(unittest.TestCase):
    def test_content_hash_matches_the_ecossistema(self):
        payload = {'operation': 'collect', 'requestId': 'x', 'fencingToken': 3, 'observedAt': 'now', **CONTENT}
        # Only the diary counts: when or by whom it was read never changes the hash.
        self.assertEqual(content_hash(payload), 'ejvrOzgythGCyeAvblqIQp41cxV93nD11YHa99P6I6U')

    def test_schedule_hash_matches_the_ecossistema_in_any_order(self):
        self.assertEqual(schedule_hash(SCHEDULE), 'gvV54qYzWAbdp_6ZJk6hsRABYj-Vzb2dYc0XiRmTD6k')
        reversed_lessons = {**SCHEDULE, 'lessons': list(reversed(SCHEDULE['lessons']))}
        self.assertEqual(schedule_hash(reversed_lessons), 'gvV54qYzWAbdp_6ZJk6hsRABYj-Vzb2dYc0XiRmTD6k')

    def test_unchanged_payload_keeps_every_guard_and_drops_coverage_and_marks(self):
        payload = {'operation': 'collect', 'academicYear': 2026, 'requestId': 'old', 'fencingToken': 3,
                   'expectedRevision': 5, 'sourceVersion': 'sha256:' + 'a' * 64, 'observedAt': '2026-10-22T10:00:00Z',
                   **CONTENT}
        brief = unchanged_payload(payload, 'h' * 43, 'new')
        self.assertEqual(brief['operation'], 'collect-unchanged')
        self.assertEqual(brief['requestId'], 'new')
        self.assertEqual(brief['contentHash'], 'h' * 43)
        self.assertNotIn('coverage', brief)
        self.assertNotIn('marks', brief)
        for field in ('fencingToken', 'expectedRevision', 'sourceVersion', 'observedAt', 'records', 'classId'):
            self.assertEqual(brief[field], payload[field])

    def test_a_copy_is_current_only_for_the_same_class_content_and_day(self):
        payload = {'classId': 7, 'sourceClassId': '13331'}
        copy = {'classId': 7, 'sourceClassId': '13331', 'contentHash': 'h', 'fullOn': '2026-10-22'}
        self.assertTrue(is_current(copy, payload, 'h', '2026-10-22'))
        self.assertFalse(is_current(copy, payload, 'other', '2026-10-22'))
        self.assertFalse(is_current(copy, payload, 'h', '2026-10-23'))  # A new day goes in full once.
        self.assertFalse(is_current({**copy, 'classId': 8}, payload, 'h', '2026-10-22'))
        self.assertFalse(is_current(None, payload, 'h', '2026-10-22'))  # No copy (formatted PC): in full.


if __name__ == '__main__':
    unittest.main()
