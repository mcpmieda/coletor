"""Fail-closed checks for a future API integration, without any I/O.

This module NEVER computes deletion, replacement, or missing-row deltas. A
planned class marker is not evidence of attendance. The current application
must keep transmission disabled until a real authenticated API adapter exists.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date
import hashlib
import json

from .models import AnnualSnapshot, Issue, MappingValidation, ValidationResult


def canonical_snapshot_id(snapshot: AnnualSnapshot) -> str:
    """Hash normalized contents, including issues, but excluding the hash itself."""
    body = asdict(snapshot)
    body.pop("snapshot_id", None)
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_for_transmission(
    snapshot: AnnualSnapshot,
    mapping: MappingValidation | None = None,
) -> ValidationResult:
    """Return all blockers without including display names in diagnostics.

    This pure validation does not contact the API and does not prove a receipt
    authentic. Only a future trusted API adapter may supply ``mapping``.
    """
    issues = [issue for issue in snapshot.issues if issue.severity == "error"]

    def block(code: str, message: str, ref: str | None = None) -> None:
        issues.append(Issue(code, "error", message, source_student_ref=ref))

    # No trusted adapter or receipt verifier exists in this preview. Neither
    # HTML attributes nor a local mapping object can establish authenticity.
    block("TRANSMISSION_DISABLED", "Envio desativado nesta versão de prévia local.")
    block("SOURCE_PROVENANCE_REQUIRED", "A origem precisa de validação externa autenticada, ainda não implementada.")
    if snapshot.source_format.startswith("synthetic"):
        block("SYNTHETIC_TRANSMISSION_FORBIDDEN", "Dados demonstrativos nunca podem compor um payload autorizado.")

    if snapshot.schema_version != "1.0":
        block("SNAPSHOT_SCHEMA_UNSUPPORTED", "Versão de snapshot não suportada.")
    if snapshot.snapshot_id != canonical_snapshot_id(snapshot):
        block("SNAPSHOT_CHANGED", "O snapshot foi alterado após a leitura; faça nova coleta.")
    if not snapshot.source_document_complete:
        block("DOCUMENT_INCOMPLETE", "A integridade do documento anual não foi confirmada.")
    if snapshot.source_student_refs_durable:
        block("IDENTITY_UNSAFE", "As referências locais não podem ser tratadas como identidade durável.")

    refs = [student.source_student_ref for student in snapshot.students]
    ref_set = set(refs)
    if not refs or len(ref_set) != len(refs):
        block("STUDENT_REFS_INVALID", "As referências de ficha estão ausentes ou duplicadas.")
    seen: set[tuple[str, str, int]] = set()
    for record in snapshot.records:
        key = (record.source_student_ref, record.date, record.lesson)
        if key in seen:
            block("DUPLICATE_RECORD", "Há mais de um registro para a mesma ficha, data e aula.", record.source_student_ref)
        seen.add(key)
        if record.source_student_ref not in ref_set:
            block("RECORD_STUDENT_UNKNOWN", "Um registro aponta para uma ficha ausente.")
        try:
            parsed_date = date.fromisoformat(record.date)
            valid_date = parsed_date.year == snapshot.year and parsed_date.isoformat() == record.date
        except (TypeError, ValueError):
            valid_date = False
        if not valid_date or type(record.lesson) is not int or not 1 <= record.lesson <= 6:
            block("RECORD_POSITION_INVALID", "A data ou posição de aula é inválida.", record.source_student_ref)
        if record.state in {"planned_unknown", "unknown"}:
            # Count one global blocker instead of leaking source tokens in errors.
            if not any(issue.code == "ATTENDANCE_UNRESOLVED" for issue in issues):
                block("ATTENDANCE_UNRESOLVED", "Há marcações sem significado de frequência confirmado.")
        elif record.state == "excused_absent":
            if not any(issue.code == "EXCUSED_ABSENCE_API_MAPPING_REQUIRED" for issue in issues):
                block("EXCUSED_ABSENCE_API_MAPPING_REQUIRED", "O tratamento de falta justificada precisa ser confirmado pelo contrato da API.")
        elif record.state not in {"present", "absent", "unmarked", "non_school_day", "outside_enrollment"}:
            block("ATTENDANCE_STATE_INVALID", "Foi encontrado um estado de frequência inválido.")

    expected_states = dict(sorted(Counter(record.state for record in snapshot.records).items()))
    if (snapshot.summary.students != len(snapshot.students)
            or snapshot.summary.records != len(snapshot.records)
            or snapshot.summary.states != expected_states
            or snapshot.summary.blocking_issues != sum(i.severity == "error" for i in snapshot.issues)):
        block("SNAPSHOT_SUMMARY_INVALID", "O resumo não corresponde aos registros lidos.")

    if mapping is None or not mapping.validated_by_api or not mapping.api_validation_id:
        block("API_MAPPING_REQUIRED", "O vínculo com studentUid precisa ser validado pela API.")
    else:
        if (mapping.snapshot_id != snapshot.snapshot_id or mapping.class_id != snapshot.class_id
                or mapping.year != snapshot.year):
            block("API_MAPPING_SCOPE_MISMATCH", "O vínculo validado pertence a outra coleta, turma ou ano.")
        if set(mapping.source_to_student_uid) != ref_set:
            block("API_MAPPING_INCOMPLETE", "A API precisa validar cada ficha desta coleta exatamente uma vez.")
        values = list(mapping.source_to_student_uid.values())
        if any(not isinstance(value, str) or not value.strip() for value in values):
            block("API_MAPPING_UID_INVALID", "O vínculo contém um studentUid inválido.")
        elif len(set(values)) != len(values):
            block("API_MAPPING_DUPLICATE_UID", "Duas fichas não podem usar o mesmo studentUid.")

    # Diagnostics are stable and compact. Repeated row issues stay in snapshot.
    unique = list({(i.code, i.source_student_ref, i.date, i.lesson): i for i in issues}.values())
    return ValidationResult(allowed=not unique, issues=unique)


def build_safe_payload(snapshot: AnnualSnapshot, mapping: MappingValidation | None) -> dict:
    """Build additive explicit attendance upserts only; never infer absences.

    The return value is NOT sent anywhere. Raises with error codes only, never
    names, source HTML, tokens, credentials, or roster data.
    """
    result = validate_for_transmission(snapshot, mapping)
    if not result.allowed:
        codes = sorted({issue.code for issue in result.issues})
        raise ValueError("TRANSMISSION_BLOCKED: " + ",".join(codes))
    assert mapping is not None
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot.snapshot_id,
        "class_id": snapshot.class_id,
        "year": snapshot.year,
        "api_validation_id": mapping.api_validation_id,
        "mode": "upsert_explicit_only",
        "records": [
            {
                "studentUid": mapping.source_to_student_uid[record.source_student_ref],
                "date": record.date,
                "lesson": record.lesson,
                "state": record.state,
            }
            for record in snapshot.records
            if record.state in {"present", "absent"}
        ],
    }
