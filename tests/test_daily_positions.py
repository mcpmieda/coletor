"""Six source positions are capacity, never six classes held per date."""
from collections import Counter
from dataclasses import asdict
import json
import re
import unittest
from coletor.demo import build_fixture
from coletor.parser import parse_annual_html
from coletor.validation import validate_for_transmission

ABSENT = '<strong><span class="ls-color-danger">X</span></strong>'
NON_SCHOOL = '<span class="ls-ico-calendar"></span>'


def variable_daily_positions():
    html = build_fixture(students=1, include_edge_cases=False)
    # Declared synthetic scenarios only. These dates are not a school calendar.
    rows = {
        2: ['•', ABSENT, '•', '•', '', ''],
        3: ['•', '•', ABSENT, '•', '•', ''],
        4: ['•', '•', '•', '•', '•', ABSENT],
        5: ['', '', '', '', '', ''],
        6: [NON_SCHOOL] * 6,
        7: ['', '', '', '', '', ABSENT],
    }
    for day, symbols in rows.items():
        for position, symbol in enumerate(symbols, 1):
            # The first matching day/position is the FEV cell in this generator.
            pattern = rf'(<div style="[^"]*" data-day="{day}" data-lesson="{position}">).*?(</div>)'
            html, changed = re.subn(pattern, lambda m: m[1] + symbol + m[2], html, count=1)
            assert changed == 1
    return html


class DailyPositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = parse_annual_html(variable_daily_positions(), 'TESTE-A', 2026)

    def day(self, day):
        return [r for r in self.snapshot.records if r.date == f'2026-02-{day:02d}']

    def test_four_five_six_marked_positions_share_capacity_without_inventing_classes(self):
        for day, marked in ((2, 4), (3, 5), (4, 6)):
            with self.subTest(day=day):
                records = self.day(day)
                self.assertEqual([r.lesson for r in records], list(range(1, 7)))
                self.assertEqual(sum(r.source_symbol != '' for r in records), marked)
                self.assertEqual(sum(r.state == 'unmarked' for r in records), 6 - marked)
                self.assertEqual(sum(r.state == 'absent' for r in records), 1)
                self.assertEqual(sum(r.state == 'planned_unknown' for r in records), marked - 1)
                self.assertFalse(any(r.state == 'present' for r in records))

    def test_blank_day_and_explicit_non_school_day_never_become_attendance(self):
        self.assertEqual(Counter(r.state for r in self.day(5)), {'unmarked': 6})
        self.assertEqual(Counter(r.state for r in self.day(6)), {'non_school_day': 6})
        self.assertFalse(any(r.state in {'present','absent','planned_unknown'} for r in self.day(5) + self.day(6)))

    def test_explicit_sixth_position_mark_survives_other_five_blanks(self):
        records = self.day(7)
        self.assertEqual([r.state for r in records], ['unmarked'] * 5 + ['absent'])
        self.assertEqual(records[-1].source_symbol, 'X')
        self.assertEqual(records[-1].lesson, 6)

    def test_slots_and_points_are_not_a_calendar_or_denominator(self):
        self.assertTrue(self.snapshot.source_document_complete)
        self.assertEqual(self.snapshot.summary.records, 334 * 6)
        self.assertEqual(self.snapshot.summary.states.get('present', 0), 0)
        self.assertEqual(self.snapshot.summary.states['absent'], 4)
        self.assertEqual(self.snapshot.summary.states['planned_unknown'], 12)
        result = validate_for_transmission(self.snapshot)
        self.assertFalse(result.allowed)
        self.assertIn('ATTENDANCE_UNRESOLVED', {i.code for i in result.issues})
        # Normalized records describe cells, not classes taught or a denominator.
        self.assertEqual(set(asdict(self.snapshot.summary)), {'students','records','states','blocking_issues'})
        self.assertNotIn('lessons_taught', json.dumps(asdict(self.snapshot)))
