"""A collection time created while the computer was quiet runs once, late (ecossistema#1450, finding 1)."""
from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from coletor.frequency_runtime import QUIET_REFRESH_SECONDS, missed_new_slots

ZONE = ZoneInfo('America/Bahia')


def status(times):
    # Monday (weekday 1 in the Ecossistema's numbering), morning shift.
    rules = [{'weekday': 1, 'shift': 'matutino', 'enabled': True, 'times': times, 'recheck': None}]
    return {'settings': {'schedule': {'timezone': 'America/Bahia', 'rules': rules}}}


def at(hour, minute):
    return datetime(2026, 11, 16, hour, minute, tzinfo=ZONE).timestamp()


class MissedNewSlotsTests(unittest.TestCase):
    def test_a_time_created_meanwhile_and_already_passed_is_returned(self):
        self.assertEqual(missed_new_slots(status([]), at(13, 56), status(['14:00']), at(14, 4)),
                         {('2026-11-16', 'matutino', '14:00')})

    def test_a_time_still_ahead_or_already_known_is_not(self):
        self.assertEqual(missed_new_slots(status([]), at(13, 56), status(['14:30']), at(14, 4)), set())
        self.assertEqual(missed_new_slots(status(['14:00']), at(13, 50), status(['14:00']), at(14, 4)), set())

    def test_a_long_gap_never_replays(self):
        late = at(13, 50) + QUIET_REFRESH_SECONDS + 120
        self.assertEqual(missed_new_slots(status([]), at(13, 50), status(['14:00']), late), set())

    def test_no_previous_answer_or_a_malformed_one_returns_nothing(self):
        self.assertEqual(missed_new_slots(None, None, status(['14:00']), at(14, 4)), set())
        self.assertEqual(missed_new_slots({'settings': {}}, at(13, 50), status(['14:00']), at(14, 4)), set())


if __name__ == '__main__':
    unittest.main()
