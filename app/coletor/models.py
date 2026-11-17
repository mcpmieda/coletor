"""Small JSON-serializable domain models; no credentials or network dependencies.

``source_student_ref`` identifies a card/row in one source snapshot. It is NOT
studentUid, MAT, or a stable identifier, and must not be reused across snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from typing import Literal

AttendanceState = Literal["present", "absent", "excused_absent", "non_school_day", "outside_enrollment", "planned_unknown", "unmarked", "unknown"]
Severity = Literal["error", "warning"]


def plain(value):
    """The same dict as dataclasses.asdict for these models (flat fields, lists of flat models, one
    dict of counts), without its recursive deep copy: a class's diary has 80,000 records, and
    asdict took about a second each of the three times a reading called it."""
    result = dict(vars(value))
    for key, item in result.items():
        if isinstance(item, list):
            result[key] = [dict(vars(entry)) if is_dataclass(entry) else entry for entry in item]
        elif is_dataclass(item):
            result[key] = plain(item)
        elif isinstance(item, dict):
            result[key] = dict(item)
    return result


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    source_student_ref: str | None = None
    date: str | None = None
    lesson: int | None = None


@dataclass(frozen=True)
class Student:
    source_student_ref: str
    display_name: str
    # This report has no structured MAT. A name never supplies one.
    mat: str | None = None
    original_class: str | None = None


@dataclass(frozen=True)
class AttendanceRecord:
    source_student_ref: str
    date: str
    # Native cell position (capacity), not evidence of a class held that day.
    lesson: int
    state: AttendanceState
    source_symbol: str


@dataclass(frozen=True)
class SnapshotSummary:
    students: int
    # Count of normalized source positions, including unmarked cells.
    records: int
    states: dict[str, int]
    blocking_issues: int


@dataclass(frozen=True)
class AnnualSnapshot:
    schema_version: str
    snapshot_id: str
    class_id: str
    year: int
    source_format: str
    source_document_complete: bool
    source_student_refs_durable: bool
    students: list[Student]
    records: list[AttendanceRecord]
    issues: list[Issue]
    summary: SnapshotSummary


@dataclass(frozen=True)
class MappingValidation:
    """Trusted API validation receipt, supplied by an authenticated adapter.

    This is a boundary object, NOT a local verification mechanism. Never create
    a successful instance from GUI JSON, a user tickbox, or name matching.
    The future API adapter must obtain and verify the receipt server-side.
    No adapter exists in this offline scaffold.
    """

    snapshot_id: str
    class_id: str
    year: int
    source_to_student_uid: dict[str, str]
    validated_by_api: bool = False
    api_validation_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    issues: list[Issue] = field(default_factory=list)
