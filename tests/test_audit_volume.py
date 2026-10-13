import importlib.util
from pathlib import Path
import re
import unittest
from coletor.service import preview
from coletor.limits import MAX_HTML_BYTES, MAX_REQUEST_BYTES
from coletor.demo import build_fixture
from coletor.parser import parse_annual_html
from coletor.validation import validate_for_transmission

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('volume_measure',ROOT/'scripts/measure_synthetic_volume.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class AuditCapacityTests(unittest.TestCase):
    def test_dense_64_cards_pass_service_with_shared_budgets(self):
        html = module.dense_cards(64)
        self.assertGreater(len(html.encode()),8*1024*1024)
        self.assertLess(len(html.encode()),MAX_HTML_BYTES)
        result = preview(html,'TESTE-A',2026)
        self.assertEqual(result['snapshot']['summary']['records'],64*334*6)
        self.assertEqual(len(result['snapshot']['students']),64)
        self.assertFalse(result['validation']['allowed'])

    def test_unknown_cardinalities_fail_closed_without_authorizing_payload(self):
        for count in (4,5,7):
            with self.subTest(count=count):
                html = build_fixture(students=1,include_edge_cases=False)
                header = ''.join(f'<div>{i}</div>' for i in range(1,7))
                changed = ''.join(f'<div>{i}</div>' for i in range(1,count+1))
                snapshot = parse_annual_html(html.replace(header,changed),'TESTE-A',2026)
                self.assertIn('LESSON_HEADER_INVALID',{i.code for i in snapshot.issues})
                self.assertFalse(snapshot.source_document_complete)
                self.assertFalse(validate_for_transmission(snapshot).allowed)

    def test_bytes_nodes_and_transport_remain_bounded(self):
        self.assertLess(MAX_REQUEST_BYTES,3*MAX_HTML_BYTES)
        too_large = parse_annual_html('x'*(MAX_HTML_BYTES+1),'TESTE-A',2026)
        self.assertIn('DOCUMENT_TOO_LARGE',{i.code for i in too_large.issues})
        from unittest.mock import patch
        with patch('coletor.parser.MAX_NODES',20):
            snapshot = parse_annual_html(build_fixture(),'TESTE-A',2026)
        self.assertEqual(snapshot.records,[])
        self.assertFalse(snapshot.source_document_complete)
