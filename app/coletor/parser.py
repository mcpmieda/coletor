"""Conservative, deterministic HTML reader for annual attendance reports.

Only recognized structure is parsed; missing/ambiguous information is reported,
never guessed. This module does not open pages, follow links, or perform I/O.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from html.parser import HTMLParser
import re
import unicodedata

from .models import AnnualSnapshot, AttendanceRecord, Issue, SnapshotSummary, Student
from .validation import canonical_snapshot_id

from .limits import MAX_HTML_BYTES, MAX_STUDENTS, MAX_RECORDS, MAX_ISSUES, MAX_NODES


class _VolumeExceeded(ValueError):
    def __init__(self, issues=None):
        self.issues = list(issues or [])[:20]
        super().__init__("REPORT_VOLUME_EXCEEDED")

MONTHS = {"FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
          "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list["_Node | str"] = field(default_factory=list)

    def text(self) -> str:
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def walk(self, tag: str | None = None):
        for child in self.children:
            if isinstance(child, _Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.walk(tag)


class _TreeReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]
        self.malformed = False
        self.closed_tags: set[str] = set()
        self.node_count = 0

    def handle_starttag(self, tag, attrs):
        self.node_count += 1
        if self.node_count > MAX_NODES or len(self.stack) > 256:
            raise ValueError("HTML_LIMIT_EXCEEDED")
        attributes = dict((key, value or "") for key, value in attrs)
        if len(attributes) != len(attrs):
            self.malformed = True
        node = _Node(tag, attributes)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            # Browser recovery is not evidence that an annual export is whole.
            self.malformed = True
            for index in range(len(self.stack) - 1, 0, -1):
                if self.stack[index].tag == tag:
                    self.stack = self.stack[:index]
                    self.closed_tags.add(tag)
                    break
            return
        self.stack.pop()
        self.closed_tags.add(tag)

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


# Student card header, located by label rather than by field count: since
# 10/2026 some cards carry an extra trailing value (e.g. a situation badge).
HEADER_LABELS = ("Aluno(a):", "Nascimento:", "Filiação:", "Turma:", "Data da matrícula:")
MAX_EXTRA_HEADER_FIELDS = 3


def _labeled_fields(small: "_Node") -> list[tuple[str, str]]:
    """(label, value) for each <strong>, label = the text right before it."""
    pairs, pending = [], []

    def visit(node):
        for child in node.children:
            if isinstance(child, str):
                pending.append(child)
            elif child.tag == "strong":
                pairs.append((_normalized("".join(pending)), _normalized(child.text())))
                pending.clear()
            else:
                visit(child)
    visit(small)
    return pairs


def _student_header(small: "_Node") -> dict[str, str] | None:
    """Values of the five known labels in their order; trailing extras allowed."""
    pairs = _labeled_fields(small)
    if not len(HEADER_LABELS) <= len(pairs) <= len(HEADER_LABELS) + MAX_EXTRA_HEADER_FIELDS:
        return None
    if [label for label, _ in pairs[:len(HEADER_LABELS)]] != list(HEADER_LABELS):
        return None
    if any(label in HEADER_LABELS for label, _ in pairs[len(HEADER_LABELS):]):
        return None
    return dict(pairs[:len(HEADER_LABELS)])


def _finish(class_id, year, complete, source_format, students, records, issues):
    students.sort(key=lambda student: student.source_student_ref)
    records.sort(key=lambda record: (record.source_student_ref, record.date, record.lesson))
    issues.sort(key=lambda issue: (issue.code, issue.source_student_ref or "", issue.date or "", issue.lesson or 0))
    snapshot = AnnualSnapshot(
        schema_version="1.0", snapshot_id="", class_id=str(class_id), year=year,
        source_format=source_format, source_document_complete=complete,
        source_student_refs_durable=False, students=students, records=records, issues=issues,
        summary=SnapshotSummary(len(students), len(records), dict(sorted(Counter(r.state for r in records).items())),
                                sum(i.severity == "error" for i in issues)),
    )
    return replace(snapshot, snapshot_id=canonical_snapshot_id(snapshot))


def parse_annual_html(html: str, class_id: str, year: int) -> AnnualSnapshot:
    """Parse one fully captured annual report; return blockers instead of logging.

    ``class_id`` and ``year`` are expected values and must agree with the report.
    A snapshot can be useful for preview while still blocked for transmission.
    No name-to-identity lookup occurs. Empty slots are never interpreted absent.
    """
    issues: list[Issue] = []
    students: list[Student] = []
    records: list[AttendanceRecord] = []

    def issue(code, message, ref=None, when=None, lesson=None, severity="error"):
        if len(issues) >= MAX_ISSUES:
            raise _VolumeExceeded(issues)
        issues.append(Issue(code, severity, message, ref, when, lesson))

    if not isinstance(class_id, str) or not class_id.strip() or type(year) is not int or not 1 <= year <= 9999:
        issue("EXPECTED_SCOPE_INVALID", "Informe turma e ano válidos para a coleta.")
        return _finish(str(class_id or ""), year if type(year) is int else 0, False, "unrecognized", students, records, issues)
    if not isinstance(html, str) or not html.strip():
        issue("DOCUMENT_EMPTY", "O documento HTML está vazio.")
        return _finish(class_id, year, False, "unrecognized", students, records, issues)
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        issue("DOCUMENT_TOO_LARGE", "O documento excede o limite seguro de leitura.")
        return _finish(class_id, year, False, "unrecognized", students, records, issues)
    tree = _TreeReader()
    try:
        tree.feed(html)
        tree.close()
    except (ValueError, RecursionError):
        issue("DOCUMENT_MALFORMED", "O documento HTML não pôde ser lido com segurança.")
        return _finish(class_id, year, False, "unrecognized", students, records, issues)
    structurally_closed = (not tree.malformed and len(tree.stack) == 1
                           and {"html", "body"}.issubset(tree.closed_tags))
    if not structurally_closed:
        issue("DOCUMENT_MALFORMED", "O HTML está incompleto ou sua estrutura não é suportada.")
    if any(node.attrs.get("type", "").lower() == "password" for node in tree.root.walk("input")):
        issue("LOGIN_PAGE", "A captura contém uma página de autenticação.")
        return _finish(class_id, year, False, "login", students, records, issues)

    real_containers = [node for node in tree.root.walk("div") if "container-fluid" in node.attrs.get("class", "").split()]
    if real_containers:
        try:
            return _parse_smecel_grid(tree, class_id, year, structurally_closed, issues)
        except _VolumeExceeded as error:
            issues.extend(error.issues)
            issues.append(Issue("REPORT_VOLUME_EXCEEDED", "error", "O relatório excede o volume seguro de uma turma; nenhuma prévia parcial foi mantida."))
            return _finish(class_id, year, False, "unrecognized", [], [], issues)

    issue("REPORT_STRUCTURE_UNSUPPORTED", "O documento não corresponde a uma estrutura anual reconhecida.")
    return _finish(class_id, year, False, "unrecognized", students, records, issues)


def _direct(node: _Node, tag: str | None = None) -> list[_Node]:
    return [child for child in node.children if isinstance(child, _Node) and (tag is None or child.tag == tag)]


def _has_class(node: _Node, value: str) -> bool:
    return value in node.attrs.get("class", "").split()


def _parse_smecel_grid(tree, class_id, year, structurally_closed, initial_issues):
    """Read the observed annual grid. Its visual row position is not identity.

    Evidence for the adapter is a sanitized structural inspection. Raw source
    HTML contains neither structured MAT nor a verified roster-count manifest.
    Reading the grid consequently does NOT certify safe transmission.
    """
    issues = list(initial_issues)
    students = []
    records = []
    reported_issue_keys = set()

    def issue(code, message, ref=None, when=None, lesson=None, severity="error"):
        # Repeated marks are records, not thousands of duplicate diagnostics.
        # Keep the first location per code/card; full states remain in records.
        key = (code, ref)
        if key in reported_issue_keys:
            return
        reported_issue_keys.add(key)
        if len(issues) >= MAX_ISSUES:
            raise _VolumeExceeded(issues)
        issues.append(Issue(code, severity, message, ref, when, lesson))

    containers = [node for node in tree.root.walk("div") if _has_class(node, "container-fluid")]
    if len(containers) != 1:
        issue("REPORT_STRUCTURE_UNSUPPORTED", "A estrutura do relatório anual não pôde ser identificada de forma única.")
        return _finish(class_id, year, False, "unrecognized", students, records, issues)
    report = containers[0]
    synthetic = report.attrs.get("data-report") == "synthetic-smecel-annual-v1"
    source_format = "synthetic-smecel-annual-v1" if synthetic else "smecel-annual-v1"
    if synthetic:
        issue("SYNTHETIC_DATA", "Documento demonstrativo com alunos explicitamente sintéticos.", severity="warning")
    cards = [node for node in _direct(report, "div") if any(_has_class(child, "ls-box1") for child in node.walk("div"))]
    if len(cards) > MAX_STUDENTS:
        raise _VolumeExceeded(issues)
    if not cards:
        issue("ROSTER_EMPTY", "Não foram encontradas fichas anuais na estrutura esperada.")
    if synthetic:
        expected_count = report.attrs.get("data-student-count", "")
        if not expected_count.isdigit() or int(expected_count) != len(cards):
            issue("ROSTER_INCOMPLETE", "A quantidade de fichas não corresponde ao total declarado.")
        if report.attrs.get("data-class-id") != class_id:
            issue("CLASS_MISMATCH", "A turma do documento difere da turma solicitada.")
        if report.attrs.get("data-year") != str(year):
            issue("YEAR_MISMATCH", "O ano do documento difere do ano solicitado.")
        if len([node for node in report.walk() if node.attrs.get("data-report-end") == "complete"]) != 1:
            issue("REPORT_END_MISSING", "O término do relatório não pôde ser confirmado.")
    else:
        issue("ROSTER_COMPLETENESS_UNVERIFIED", "O HTML não declara o total esperado de fichas; uma captura parcial não pode ser descartada.")
        issue("CLASS_ID_UNVERIFIED", "O relatório não fornece vínculo estruturado entre o rótulo da turma e o identificador solicitado.")

    seen_card_signatures = set()
    seen_refs = set()
    seen_keys = set()
    for ordinal, card in enumerate(cards, 1):
        row = card.attrs.get("data-student-row", str(ordinal)) if synthetic else str(ordinal)
        ref = "row:" + (row if row.isdigit() else str(ordinal))
        if not row.isdigit() or ref in seen_refs:
            issue("DUPLICATE_STUDENT_ROW" if ref in seen_refs else "STUDENT_ROW_INVALID", "A referência local de uma ficha é inválida ou duplicada.", ref)
        seen_refs.add(ref)
        boxes = [node for node in card.walk("div") if _has_class(node, "ls-box1")]
        smalls = list(boxes[0].walk("small")) if len(boxes) == 1 else []
        header = _student_header(smalls[0]) if len(smalls) == 1 else None
        if header is None:
            issue("STUDENT_HEADER_INVALID", "O cabeçalho de uma ficha não corresponde à estrutura esperada.", ref)
            name, class_label = "", ""
        else:
            name = header["Aluno(a):"]
            class_label = header["Turma:"]
        if len(name) > 200:
            name = name[:200]
            issue("STUDENT_NAME_TOO_LONG", "Um cabeçalho contém texto além do limite seguro.", ref)
        if not name:
            issue("STUDENT_NAME_MISSING", "O nome de exibição da ficha não foi encontrado.", ref)
        # Only display_name is kept. Birth dates, parents and enrollment dates
        # deliberately never enter the result, payload or diagnostics.
        students.append(Student(ref, name, None, class_label))
        if synthetic and class_label != class_id:
            issue("CLASS_MISMATCH", "O rótulo da turma de uma ficha difere da turma solicitada.", ref)
        titles = [node for node in _direct(card, "p") if _has_class(node, "ls-txt-center")]
        expected_title = f"FREQUENCIA ESCOLAR {year}"
        if len(titles) != 1 or _normalized(titles[0].text()) != expected_title:
            issue("YEAR_MISMATCH", "O título anual está ausente ou apresenta outro ano.", ref)
        tables = [node for node in _direct(card, "table") if _has_class(node, "bordasimples")]
        annual_tables = []
        for table in tables:
            tbodies = _direct(table, "tbody")
            rows = _direct(tbodies[0], "tr") if len(tbodies) == 1 else _direct(table, "tr")
            if rows and _direct(rows[0], "td") and _normalized(_direct(rows[0], "td")[0].text()) == "Meses":
                annual_tables.append((table, rows))
        if len(annual_tables) != 1:
            issue("ANNUAL_TABLE_INVALID", "A grade anual não foi identificada de forma única na ficha.", ref)
            continue
        table, rows = annual_tables[0]
        if len(rows) != 34:
            issue("GRID_COVERAGE_INVALID", "A grade anual precisa conter cabeçalhos, 31 dias e o total de faltas.", ref)
        header = _direct(rows[0], "td")
        observed_months = [_normalized(cell.text()) for cell in header[1:]]
        expected_months = [f"{month}/{year}" for month in MONTHS]
        if observed_months != expected_months:
            issue("MONTH_COVERAGE_INVALID", "As colunas anuais precisam conter FEV a DEZ, na ordem e no ano esperados.", ref)
        if len(header) != 12 or len(rows) < 2:
            issue("GRID_COVERAGE_INVALID", "Os cabeçalhos da grade anual estão incompletos.", ref)
            continue
        lesson_cells = _direct(rows[1], "td")
        if len(lesson_cells) != 12 or _normalized(lesson_cells[0].text()) != "Aulas":
            issue("LESSON_HEADER_INVALID", "O cabeçalho de posições de aula está incompleto.", ref)
        else:
            for cell in lesson_cells[1:]:
                wrappers = _direct(cell, "div")
                positions = _direct(wrappers[0], "div") if len(wrappers) == 1 else []
                if [_normalized(node.text()) for node in positions] != [str(i) for i in range(1, 7)]:
                    issue("LESSON_HEADER_INVALID", "As posições de aula precisam ser de 1 a 6 na ordem original.", ref)
                    break
        day_rows = []
        totals = []
        for row_node in rows[2:]:
            cells = _direct(row_node, "td")
            if cells and _normalized(cells[0].text()) == "FALTAS":
                totals.append(cells)
            else:
                day_rows.append(cells)
        if len(totals) != 1 or len(totals[0]) != 12:
            issue("TOTALS_ROW_INVALID", "A linha final de totais mensais está ausente ou incompleta.", ref)
        if [(_normalized(cells[0].text()) if cells else "") for cells in day_rows] != [str(i) for i in range(1, 32)]:
            issue("GRID_COVERAGE_INVALID", "As linhas de dias precisam conter 1 a 31, sem repetição e na ordem original.", ref)
        legend_nodes = [node for node in card.walk("i")]
        legend = _plain(" ".join(node.text() for node in legend_nodes))
        if not legend or "aula prevista/presenca" not in legend.replace(" / ", "/"):
            issue("LEGEND_UNVERIFIED", "A legenda de frequência está ausente ou não foi reconhecida.", ref)
        card_symbols = []
        for cells in day_rows:
            day_text = _normalized(cells[0].text()) if cells else ""
            if len(cells) != 12 or not day_text.isdigit() or not 1 <= int(day_text) <= 31:
                issue("GRID_COVERAGE_INVALID", "Uma linha de dias não contém as onze colunas mensais esperadas.", ref)
                continue
            for month_index, cell in enumerate(cells[1:]):
                month = list(MONTHS.values())[month_index]
                slots = _direct(cell, "div")
                if not slots and not _normalized(cell.text()) and not _direct(cell):
                    # Observed empty monthly cells retain six unmarked slots.
                    slots = [_Node("div", {}) for _ in range(6)]
                elif len(slots) != 6:
                    issue("GRID_COVERAGE_INVALID", "Uma célula mensal não contém as seis posições de aula esperadas.", ref)
                    continue
                for lesson, slot in enumerate(slots, 1):
                    symbol = _normalized(slot.text())
                    if len(symbol) > 32:
                        symbol = symbol[:32]
                        issue("SOURCE_SYMBOL_TOO_LONG", "Uma posição de aula contém conteúdo inesperado.", ref)
                    state, symbol = _source_state(symbol, slot, legend)
                    card_symbols.append((month, int(day_text), lesson, symbol, state))
                    try:
                        when = date(year, month, int(day_text)).isoformat()
                    except ValueError:
                        if state not in {"unmarked", "non_school_day", "outside_enrollment"}:
                            issue("INVALID_DATE_MARKED", "Existe marcação em um dia que não existe no calendário.", ref, None, lesson)
                        continue
                    if state == "unknown":
                        issue("SOURCE_SYMBOL_UNKNOWN", "Uma marcação de frequência não possui significado confirmado.", ref, when, lesson)
                    elif state == "planned_unknown":
                        issue("SOURCE_SYMBOL_AMBIGUOUS", "A marcação pode indicar aula prevista; não confirma presença.", ref, when, lesson, "warning")
                    key = (ref, when, lesson)
                    if key in seen_keys:
                        issue("DUPLICATE_RECORD", "A mesma ficha, data e posição de aula aparece mais de uma vez.", ref, when, lesson)
                        continue
                    seen_keys.add(key)
                    if len(records) >= MAX_RECORDS:
                        raise _VolumeExceeded(issues)
                    records.append(AttendanceRecord(ref, when, lesson, state, symbol))
        signature = (name, class_label, tuple(card_symbols))
        if signature in seen_card_signatures:
            issue("DUPLICATE_CARD_CONTENT", "Duas fichas possuem conteúdo repetido; confirme a captura antes de continuar.", ref)
        seen_card_signatures.add(signature)
    complete = structurally_closed and bool(cards) and not any(i.severity == "error" for i in issues)
    return _finish(class_id, year, complete, source_format, students, records, issues)


def _plain(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", _normalized(value).lower()) if not unicodedata.combining(ch))


def _source_state(symbol, slot, legend):
    """Require the observed symbol, shape and legend together; never color alone."""
    direct = _direct(slot)
    if not symbol and not direct:
        return "unmarked", ""
    if symbol == "•" and not direct and "aula prevista/presenca" in legend.replace(" / ", "/"):
        return "planned_unknown", symbol
    if len(direct) == 1 and direct[0].tag == "strong":
        spans = _direct(direct[0], "span")
        if len(spans) == 1:
            span = spans[0]
            if symbol == "X" and _has_class(span, "ls-color-danger") and "falta nao justificada" in legend:
                return "absent", "X"
            if not symbol and _has_class(span, "ls-color-warning") and _has_class(span, "ls-ico-info") and "falta justificada" in legend:
                return "excused_absent", "icon:ls-color-warning.ls-ico-info"
            # Blue X, "falta com motivo informado" (owner decision 20/10/2026): for the school it is
            # a justified absence, like the yellow icon. Matched by its shape and the start of its
            # legend only, never by "(nao abona)": if Smecel ever changes whether it excuses the
            # absence, our own classification and counts stay the same.
            if symbol == "X" and _has_class(span, "ls-color-info") and "falta com motivo informado" in legend:
                return "excused_absent", "X:ls-color-info"
    if len(direct) == 1 and direct[0].tag == "span" and not symbol:
        span = direct[0]
        if _has_class(span, "ls-ico-calendar") and "dia nao letivo" in legend:
            return "non_school_day", "icon:ls-ico-calendar"
        if _has_class(span, "ls-ico-minus") and "fora do periodo de matricula" in legend:
            return "outside_enrollment", "icon:ls-ico-minus"
    # Empty unsupported markup must not silently disappear as an empty cell. The description says
    # what the mark shows (its text and visual classes, never anything personal), so the collector's
    # log can name it: "X [ls-color-info]" or "[ls-ico-star]".
    return "unknown", _describe_unknown(symbol, slot)


def _describe_unknown(symbol: str, slot: "_Node") -> str:
    classes = []
    for node in slot.walk():
        for name in node.attrs.get("class", "").split():
            if name not in classes and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
                classes.append(name)
    description = " ".join(part for part in (symbol, f"[{' '.join(classes)}]" if classes else "") if part)
    return description[:32] or "icon:unrecognized"
