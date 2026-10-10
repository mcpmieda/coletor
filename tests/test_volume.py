"""Regression for compact source grids expanding into excessive snapshots."""
import re
import unittest
from unittest.mock import patch
from coletor.demo import build_fixture
from coletor.parser import parse_annual_html, MAX_STUDENTS


def compact_cards(count):
    html = build_fixture(students=1, include_edge_cases=False)
    html = re.sub(r'<td>\s*(?:<div style="[^"]*" data-day="[^"]*" data-lesson="[^"]*"></div>\s*){6}</td>', '<td></td>', html)
    start = html.index('<div style="page-break-inside: avoid;"')
    end = html.index('<footer')
    card = html[start:end]
    cards = ''.join(card.replace('data-student-row="1"',f'data-student-row="{i}"').replace('Aluno sintético 001',f'Aluno sintético {i:03d}') for i in range(1,count+1))
    return (html[:start] + cards + html[end:]).replace('data-student-count="1"',f'data-student-count="{count}"')


class VolumeTests(unittest.TestCase):
    def assert_volume_block(self, snapshot):
        self.assertEqual(snapshot.students, [])
        self.assertEqual(snapshot.records, [])
        self.assertFalse(snapshot.source_document_complete)
        self.assertIn('REPORT_VOLUME_EXCEEDED', {i.code for i in snapshot.issues})

    def test_compact_many_cards_block_before_expansion(self):
        source = compact_cards(MAX_STUDENTS+1)
        self.assertLess(len(source.encode()), 1024*1024)
        self.assert_volume_block(parse_annual_html(source,'TESTE-A',2026))

    def test_record_budget_blocks_without_partial_output(self):
        with patch('coletor.parser.MAX_RECORDS', 20):
            self.assert_volume_block(parse_annual_html(build_fixture(),'TESTE-A',2026))

    def test_issue_budget_blocks_without_partial_output(self):
        with patch('coletor.parser.MAX_ISSUES', 2):
            self.assert_volume_block(parse_annual_html(build_fixture(),'TESTE-A',2026))

    def test_32_cards_remain_supported(self):
        snapshot = parse_annual_html(compact_cards(32),'TESTE-A',2026)
        self.assertEqual(len(snapshot.students),32)
        self.assertEqual(len(snapshot.records),32*334*6)
        self.assertNotIn('REPORT_VOLUME_EXCEEDED',{i.code for i in snapshot.issues})

    def test_expected_ambiguous_marks_are_aggregated_without_dropping_roster(self):
        source = re.sub(r'(<div style="[^"]+" data-day="\d+" data-lesson="\d+">)</div>', r'\1•</div>', build_fixture(students=1, include_edge_cases=False), count=1001)
        snapshot = parse_annual_html(source,'TESTE-A',2026)
        self.assertEqual(len(snapshot.students),1)
        self.assertEqual(len(snapshot.records),334*6)
        self.assertEqual(snapshot.summary.states['planned_unknown'],1001)
        self.assertEqual(sum(i.code == 'SOURCE_SYMBOL_AMBIGUOUS' for i in snapshot.issues),1)
        self.assertNotIn('REPORT_VOLUME_EXCEEDED',{i.code for i in snapshot.issues})
