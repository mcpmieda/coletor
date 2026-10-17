from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
import importlib.util
import json
import re
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
spec = importlib.util.spec_from_file_location("generate_fixture", ROOT / "scripts" / "generate_fixture.py")
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
build_fixture = fixture_module.build_fixture

from coletor.models import MappingValidation
from coletor.parser import parse_annual_html
from coletor.validation import build_safe_payload, canonical_snapshot_id, validate_for_transmission


class AnnualParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean_html = build_fixture(include_edge_cases=False)
        cls.clean = parse_annual_html(cls.clean_html, "TESTE-A", 2026)
        cls.edge_html = build_fixture()
        cls.edge = parse_annual_html(cls.edge_html, "TESTE-A", 2026)

    def codes(self, snapshot):
        return {issue.code for issue in snapshot.issues}

    def mapping(self, snapshot=None):
        snapshot = snapshot or self.clean
        return MappingValidation(snapshot.snapshot_id, snapshot.class_id, snapshot.year,
                                 {s.source_student_ref: f"api-test-uid-{i}" for i, s in enumerate(snapshot.students)},
                                 validated_by_api=True, api_validation_id="fake-receipt-unit-test-only")

    def test_fixture_is_explicitly_synthetic_and_matches_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "synthetic.html"
            target.write_text(build_fixture(), encoding="utf-8")
            self.assertEqual(target.read_text(encoding="utf-8"), self.edge_html)
        self.assertEqual([s.display_name for s in self.edge.students],
                         ["Aluno sintético 001", "Aluno sintético 002", "Aluno sintético 003"])
        self.assertIn("synthetic", self.edge.source_format)

    def test_every_valid_calendar_day_has_six_distinct_slots(self):
        self.assertTrue(self.clean.source_document_complete)
        self.assertEqual(len(self.clean.records), 3 * (365 - 31) * 6)
        self.assertEqual(Counter(r.lesson for r in self.clean.records), {i: 3 * 334 for i in range(1, 7)})
        self.assertFalse(any(r.date == "2026-02-29" for r in self.clean.records))
        self.assertFalse(any(r.date == "2026-04-31" for r in self.clean.records))

    def test_leap_year_has_february_29(self):
        leap = parse_annual_html(build_fixture(year=2024, include_edge_cases=False), "TESTE-A", 2024)
        self.assertEqual(len(leap.records), 3 * (366 - 31) * 6)
        self.assertEqual(sum(r.date == "2024-02-29" for r in leap.records), 18)
        self.assertTrue(leap.source_document_complete)

    def test_ambiguous_tokens_never_become_present(self):
        records = [r for r in self.edge.records if r.source_symbol == "•"]
        self.assertEqual(len(records), 1)
        self.assertTrue(all(r.state == "planned_unknown" for r in records))
        result = validate_for_transmission(self.edge, self.mapping(self.edge))
        self.assertFalse(result.allowed)
        self.assertIn("ATTENDANCE_UNRESOLVED", {i.code for i in result.issues})

    def test_unknown_code_is_preserved_but_blocks(self):
        unknown = [r for r in self.edge.records if r.source_symbol == "?"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].state, "unknown")
        self.assertIn("SOURCE_SYMBOL_UNKNOWN", self.codes(self.edge))

    def test_marked_invalid_date_is_not_a_record(self):
        self.assertIn("INVALID_DATE_MARKED", self.codes(self.edge))
        self.assertFalse(any(r.date.endswith("02-31") for r in self.edge.records))
        self.assertFalse(validate_for_transmission(self.edge, self.mapping(self.edge)).allowed)

    def test_blank_is_neither_present_nor_absent(self):
        blanks = [r for r in self.clean.records if r.source_symbol == ""]
        self.assertTrue(blanks)
        self.assertTrue(all(r.state == "unmarked" for r in blanks))

    def test_no_mat_no_durable_identity(self):
        self.assertTrue(all(s.mat is None for s in self.clean.students))
        self.assertFalse(self.clean.source_student_refs_durable)
        serialized = json.dumps(asdict(self.clean), ensure_ascii=False)
        self.assertNotIn("studentUid", serialized)
        self.assertEqual([s.source_student_ref for s in self.clean.students], ["row:1", "row:2", "row:3"])

    def test_determinism_and_json_serialization(self):
        second = parse_annual_html(self.clean_html, "TESTE-A", 2026)
        self.assertEqual(asdict(self.clean), asdict(second))
        self.assertEqual(json.loads(json.dumps(asdict(self.clean)))["snapshot_id"], self.clean.snapshot_id)
        self.assertEqual(self.clean.snapshot_id, canonical_snapshot_id(self.clean))

    def test_login_and_empty_document_are_blocked(self):
        login = parse_annual_html('<html><body><form><input type="password"></form></body></html>', "TESTE-A", 2026)
        self.assertIn("LOGIN_PAGE", self.codes(login))
        self.assertFalse(login.source_document_complete)
        self.assertIn("DOCUMENT_EMPTY", self.codes(parse_annual_html("", "TESTE-A", 2026)))

    def test_arbitrary_html_is_not_guessed(self):
        snapshot = parse_annual_html('<html><body><h1>Diário 2026</h1><p>Aluno sintético 001 P</p></body></html>', "TESTE-A", 2026)
        self.assertEqual(snapshot.records, [])
        self.assertIn("REPORT_STRUCTURE_UNSUPPORTED", self.codes(snapshot))

    def test_scope_mismatch_is_blocked(self):
        self.assertIn("CLASS_MISMATCH", self.codes(parse_annual_html(self.clean_html, "OUTRA", 2026)))
        self.assertIn("YEAR_MISMATCH", self.codes(parse_annual_html(self.clean_html, "TESTE-A", 2025)))

    def test_truncated_and_malformed_document_are_blocked(self):
        truncated = parse_annual_html(self.clean_html[:-100], "TESTE-A", 2026)
        self.assertFalse(truncated.source_document_complete)
        self.assertIn("DOCUMENT_MALFORMED", self.codes(truncated))
        malformed = parse_annual_html(self.clean_html.replace('</tbody>', '</wrong>', 1), "TESTE-A", 2026)
        self.assertIn("DOCUMENT_MALFORMED", self.codes(malformed))

    def test_missing_card_month_and_cell_are_detected(self):
        fewer = parse_annual_html(self.clean_html.replace('data-student-count="3"', 'data-student-count="4"'), "TESTE-A", 2026)
        self.assertIn("ROSTER_INCOMPLETE", self.codes(fewer))
        month = parse_annual_html(self.clean_html.replace('<td>FEV/2026</td>', '<td>JAN/2026</td>', 1), "TESTE-A", 2026)
        self.assertIn("MONTH_COVERAGE_INVALID", self.codes(month))
        cell = parse_annual_html(self.clean_html.replace(f'<div style="{fixture_module.SLOT_STYLE}" data-day="1" data-lesson="1"></div>', '', 1), "TESTE-A", 2026)
        self.assertIn("GRID_COVERAGE_INVALID", self.codes(cell))

    def test_duplicate_rows_and_slots_are_rejected(self):
        duplicate_row = parse_annual_html(self.clean_html.replace('data-student-row="2"', 'data-student-row="1"'), "TESTE-A", 2026)
        self.assertIn("DUPLICATE_STUDENT_ROW", self.codes(duplicate_row))
        cell = f'<div style="{fixture_module.SLOT_STYLE}" data-day="1" data-lesson="1"></div>'
        duplicate_cell = parse_annual_html(self.clean_html.replace(cell, cell + cell, 1), "TESTE-A", 2026)
        self.assertIn("GRID_COVERAGE_INVALID", self.codes(duplicate_cell))

    def test_absent_api_receipt_blocks_and_names_are_not_in_errors(self):
        result = validate_for_transmission(self.clean)
        self.assertFalse(result.allowed)
        self.assertIn("API_MAPPING_REQUIRED", {i.code for i in result.issues})
        with self.assertRaises(ValueError) as caught:
            build_safe_payload(self.clean, None)
        self.assertNotIn("Aluno", str(caught.exception))
        self.assertTrue(all("Aluno" not in i.message for i in self.edge.issues + result.issues))

    def test_mapping_is_bound_to_exact_snapshot_scope_and_roster(self):
        for mapping, expected in (
            (replace(self.mapping(), snapshot_id="another"), "API_MAPPING_SCOPE_MISMATCH"),
            (replace(self.mapping(), class_id="another"), "API_MAPPING_SCOPE_MISMATCH"),
            (replace(self.mapping(), year=2025), "API_MAPPING_SCOPE_MISMATCH"),
            (replace(self.mapping(), source_to_student_uid={}), "API_MAPPING_INCOMPLETE"),
            (replace(self.mapping(), source_to_student_uid={s.source_student_ref: "same" for s in self.clean.students}), "API_MAPPING_DUPLICATE_UID"),
            (replace(self.mapping(), validated_by_api=False), "API_MAPPING_REQUIRED"),
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, {i.code for i in validate_for_transmission(self.clean, mapping).issues})

    def test_edited_snapshot_and_duplicate_record_are_rejected(self):
        changed = replace(self.clean, records=self.clean.records[1:])
        self.assertIn("SNAPSHOT_CHANGED", {i.code for i in validate_for_transmission(changed, self.mapping()).issues})
        duplicate = replace(self.clean, records=self.clean.records + self.clean.records[:1])
        self.assertIn("DUPLICATE_RECORD", {i.code for i in validate_for_transmission(duplicate, self.mapping()).issues})

    def test_synthetic_payload_is_forbidden_even_with_complete_mapping(self):
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_TRANSMISSION_FORBIDDEN"):
            build_safe_payload(self.clean, self.mapping())

    def test_forged_source_label_and_receipt_cannot_authorize_prototype(self):
        forged = replace(self.clean, source_format="smecel-annual-v1")
        forged = replace(forged, snapshot_id=canonical_snapshot_id(forged))
        result = validate_for_transmission(forged, self.mapping(forged))
        self.assertFalse(result.allowed)
        self.assertIn("SOURCE_PROVENANCE_REQUIRED", {i.code for i in result.issues})
        with self.assertRaisesRegex(ValueError, "TRANSMISSION_DISABLED"):
            build_safe_payload(forged, self.mapping(forged))

    def test_real_shape_is_previewed_but_provenance_remains_blocked(self):
        raw = re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"', '', self.clean_html)
        snapshot = parse_annual_html(raw, "13331", 2026)
        self.assertEqual(snapshot.source_format, "smecel-annual-v1")
        self.assertEqual(len(snapshot.students), 3)
        self.assertIn("CLASS_ID_UNVERIFIED", self.codes(snapshot))
        self.assertIn("ROSTER_COMPLETENESS_UNVERIFIED", self.codes(snapshot))
        self.assertFalse(snapshot.source_document_complete)
        self.assertFalse(validate_for_transmission(snapshot, self.mapping(snapshot)).allowed)

    def test_icon_states_are_preserved_without_inventing_presence(self):
        records = {r.lesson: r for r in self.edge.records if r.source_student_ref == "row:1" and r.date == "2026-02-02"}
        self.assertEqual(records[1].state, "absent")
        self.assertEqual(records[2].state, "excused_absent")
        self.assertEqual(records[3].state, "planned_unknown")
        self.assertEqual(records[4].state, "non_school_day")
        self.assertEqual(records[5].state, "outside_enrollment")
        self.assertEqual(records[6].state, "unknown")
        self.assertEqual(records[2].source_symbol, "icon:ls-color-warning.ls-ico-info")
        self.assertFalse(any(r.state == "present" for r in self.edge.records))

    def test_symbol_shape_class_and_legend_must_agree(self):
        for html in (
            self.clean_html.replace('class="ls-color-danger"', 'class="ls-color-warning"', 1),
            self.clean_html.replace('falta não justificada', 'significado não confirmado'),
            self.clean_html.replace('<strong><span class="ls-color-danger">X</span></strong>', 'X', 1),
        ):
            snapshot = parse_annual_html(html, "TESTE-A", 2026)
            self.assertIn("SOURCE_SYMBOL_UNKNOWN", self.codes(snapshot))
        missing_legend = re.sub(r'<p style="margin:8px 0 0 0;">.*?</p>', '', self.clean_html)
        self.assertIn("LEGEND_UNVERIFIED", self.codes(parse_annual_html(missing_legend, "TESTE-A", 2026)))

    def test_empty_month_cell_and_nbsp_stay_unmarked(self):
        empty_cell = '<td>\n' + ''.join(f'<div style="{fixture_module.SLOT_STYLE}" data-day="1" data-lesson="{i}"></div>\n' for i in range(1, 7)) + '</td>'
        html = self.clean_html.replace(empty_cell, '<td></td>', 1)
        self.assertNotEqual(html, self.clean_html)
        snapshot = parse_annual_html(html, "TESTE-A", 2026)
        self.assertEqual(snapshot.records, self.clean.records)
        nbsp = parse_annual_html(self.clean_html.replace('data-day="1" data-lesson="1"></div>', 'data-day="1" data-lesson="1">&nbsp;</div>', 1), "TESTE-A", 2026)
        self.assertEqual(nbsp.records, self.clean.records)

    def test_sensitive_header_fields_are_not_retained(self):
        snapshot = parse_annual_html(self.clean_html.replace('[não coletado]', 'private-header-canary'), "TESTE-A", 2026)
        self.assertNotIn('private-header-canary', json.dumps(asdict(snapshot)))

    def test_lesson_order_is_verified_independent_of_css_width(self):
        changed = self.clean_html.replace('<div>1</div><div>2</div>', '<div>2</div><div>1</div>', 1)
        self.assertIn("LESSON_HEADER_INVALID", self.codes(parse_annual_html(changed, "TESTE-A", 2026)))
        css = self.clean_html.replace('width:16.666666666667%', 'width:17%')
        self.assertEqual(parse_annual_html(css, "TESTE-A", 2026).records, self.clean.records)


class StudentHeaderByLabelTests(unittest.TestCase):
    """Since 10/2026 some Smecel cards append a value after Data da matrícula."""
    END = "Data da matrícula: <strong>[não coletado]</strong>"

    def parse(self, html):
        snapshot = parse_annual_html(html, "TESTE-A", 2026)
        return snapshot, Counter(i.code for i in snapshot.issues if i.severity == "error")

    def test_trailing_extra_value_keeps_the_student(self):
        html = build_fixture(include_edge_cases=False).replace(
            self.END, self.END + "<br><strong>SITUAÇÃO SINTÉTICA</strong>", 2)
        snapshot, errors = self.parse(html)
        self.assertNotIn("STUDENT_HEADER_INVALID", errors)
        self.assertNotIn("STUDENT_NAME_MISSING", errors)
        self.assertEqual(snapshot.students[0].display_name, "Aluno sintético 001")
        self.assertEqual(snapshot.students[1].display_name, "Aluno sintético 002")

    def test_missing_reordered_or_repeated_labels_fail_closed(self):
        base = build_fixture(include_edge_cases=False)
        for html in (base.replace("Nascimento: <strong>[não coletado]</strong><br>", "", 1),
                     base.replace("Turma:", "Classe:", 1),
                     base.replace(self.END, self.END + "<br>Turma: <strong>X</strong>", 1),
                     base.replace(self.END, self.END + "".join("<strong>x</strong>" for _ in range(4)), 1)):
            _, errors = self.parse(html)
            self.assertIn("STUDENT_HEADER_INVALID", errors)


if __name__ == "__main__":
    unittest.main()
