"""Observed student report adapter (Smecel "Relatório de alunos", owner decision 29/10/2026).

The Smecel's own export link (relatorio_alunos_personalizado_xlsx.php) is fetched by the page the
worker loaded, with the session's own request: no click on the page and no file on this computer.
The school is the session's current one, as the Smecel's school switch lists it
(ajax/listar_escolas_usuario.php: escola_atual), never a number in this code; the year is the
Coletor's own (the class list's). Only the 11 fields the Ecossistema's Conciliação uses are asked
for (the student's name always comes); never the other ones (CPF, health, address, phones...).

The xlsx is a zip of XML: it is read here, in memory, with the standard library only, cell values
raw as the ADM's reader takes them (text as text, dates and numbers as Excel numbers), so the
Ecossistema applies its own rules to them.
"""
import base64
import io
import re
import unicodedata
import zipfile
from urllib.parse import parse_qsl, urlencode, urlsplit
from xml.etree import ElementTree

from .class_catalog import ORGANIZATION, SCHOOL
from .class_selection import ORIGIN

FORM_PATH = "/sistema/escola/relatorio_alunos_personalizado.php"
EXPORT_PATH = "relatorio_alunos_personalizado_xlsx.php"
SCHOOLS_PATH = "ajax/listar_escolas_usuario.php"
# The Smecel's field names, in the order the export lays out its columns.
FIELDS = ("escola_nome", "turma_nome", "turma_turno", "etapa_nome", "situacao_matricula", "data_matricula",
          "data_transferencia", "vinculo_aluno_hash", "aluno_cod_inep", "aluno_nascimento", "aluno_filiacao1")
# Every column title of that export (the student's name comes first, always) and its field in the
# Ecossistema's report row (STUDENT_REPORT_HEADERS_V1 there). "Escola" checks the school.
HEADERS = {"NOME DO ALUNO": "name", "ESCOLA": "school", "TURMA": "classLabel", "TURNO": "shift",
           "ETAPA": "stageLabel", "SITUACAO DA MATRICULA": "status", "DATA DA MATRICULA": "enrolledAt",
           "DATA DA TRANSFERENCIA": "transferredAt", "HASH DA MATRICULA": "enrollmentHash",
           "CODIGO INEP": "inep", "NASCIMENTO": "birthDate", "FILIACAO 1": "filiation1"}
TEXT_FIELDS = ("name", "classLabel", "shift", "stageLabel", "status", "enrollmentHash")
RAW_FIELDS = ("inep", "birthDate", "enrolledAt", "transferredAt")
MAX_ROWS = 10000
MAX_XLSX_BYTES = 25 * 1024 * 1024
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_TEXT = 300
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Runs in the report's form page the worker loaded. Returns the xlsx as base64, never as a file.
REPORT_JS = """async ({year, query}) => {
  const norm=s=>(s||'').normalize('NFC').replace(/\\s+/g,' ').trim();
  const text=norm(document.body.innerText);
  const scope={url:location.href,password_form:!!document.querySelector('input[type=password]'),
    context_organization:text.includes('SECRETARIA DE EDUCAÇÃO DE MEDEIROS NETO'),
    context_school:text.includes('ESCOLA IEDA ALVES DE OLIVEIRA MCPM')};
  const list=await fetch('ajax/listar_escolas_usuario.php',{credentials:'same-origin',redirect:'manual'});
  if(list.status!==200)return {...scope,error:'schools_unavailable'};
  const schools=await list.json();
  const current=(schools.escolas||[]).filter(e=>parseInt(e.escola_id)===schools.escola_atual);
  if(schools.success!==true||current.length!==1)return {...scope,error:'school_unknown'};
  const school={id:String(schools.escola_atual),name:norm(current[0].escola_nome)};
  const url='relatorio_alunos_personalizado_xlsx.php?ano='+year+'&escola_id='+school.id+'&'+query;
  const r=await fetch(url,{credentials:'same-origin',redirect:'manual'});
  const buf=new Uint8Array(await r.arrayBuffer());
  if(buf.length>25*1024*1024)return {...scope,school,error:'report_too_large'};
  let s='';for(let i=0;i<buf.length;i+=0x8000)s+=String.fromCharCode(...buf.subarray(i,i+0x8000));
  return {...scope,school,status:r.status,type:r.headers.get('content-type'),size:buf.length,xlsx:btoa(s)};
}"""


def form_url(year):
    if type(year) is not int or not 2000 <= year <= 2100:
        raise ValueError("Informe um ano entre 2000 e 2100.")
    return f"{ORIGIN}{FORM_PATH}?ano={year}"


def matches_form(url, year):
    """The form page itself, or the same page with the filters the Smecel adds to its address."""
    from .manual_session import allowed_request
    if not isinstance(url, str) or not allowed_request(url):
        return False
    parts = urlsplit(url)
    return parts.path == FORM_PATH and not parts.fragment and ("ano", str(year)) in parse_qsl(parts.query)


def export_query():
    """Every student's enrolment of the year (Situação = Todas), curricular classes only (owner's
    choice), only the 11 fields; ano and escola_id are added by the page from the session."""
    filters = [("turma_id", ""), ("situacao", ""), ("tipo_turma", "C"), ("turno", ""), ("etapa_id", ""),
               ("transporte", ""), ("deficiencia", ""), ("bolsa", ""), ("raca", ""), ("busca", "")]
    return urlencode(filters + [("campos[]", field) for field in FIELDS])


def _plain(value):
    text = unicodedata.normalize("NFD", value if isinstance(value, str) else "")
    text = "".join(c for c in text if not "̀" <= c <= "ͯ").upper()
    return " ".join(text.split())


def _xml(archive, name):
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART_BYTES:
        raise ValueError("Relatório fora do limite permitido.")
    raw = archive.read(info)
    # No document type, so no entity of any kind can expand inside the parser.
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("Relatório com conteúdo não reconhecido.")
    return ElementTree.fromstring(raw)


def _column(reference):
    letters = re.match(r"([A-Z]+)(\d+)$", reference or "")
    if not letters:
        raise ValueError("Célula do relatório não reconhecida.")
    index = 0
    for char in letters[1]:
        index = index * 26 + ord(char) - 64
    return index - 1, int(letters[2])


def _cell(cell, strings):
    """Text as text, a number as a number (an integral one as an int), empty as None; a formula, an
    error or a boolean is never a value of the Smecel's export (as in the ADM's reader)."""
    kind = cell.get("t", "n")
    if cell.find("m:f", NS) is not None or kind in {"e", "b", "str"}:
        raise ValueError("Conteúdo inválido no relatório. Confira a exportação do Smecel.")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{{{NS['m']}}}t"))
    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return None
    if kind == "s":
        index = int(value.text)
        if not 0 <= index < len(strings):
            raise ValueError("Conteúdo inválido no relatório.")
        return strings[index]
    number = float(value.text)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("Conteúdo inválido no relatório.")
    return int(number) if number.is_integer() else number


def read_workbook(data):
    """[(sheet row number, {title: value})] of the export's only sheet."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_XLSX_BYTES:
        raise ValueError("Relatório vazio ou fora do limite permitido.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("O Smecel não devolveu uma planilha.") from None
    with archive:
        if len(archive.infolist()) > 50:
            raise ValueError("Relatório com conteúdo não reconhecido.")
        workbook = _xml(archive, "xl/workbook.xml")
        if workbook is None or len(workbook.findall("m:sheets/m:sheet", NS)) != 1:
            raise ValueError("O relatório deve conter uma única aba.")
        properties = workbook.find("m:workbookPr", NS)
        # Dates are Excel numbers from 1900, as the Ecossistema reads them (date1904 false).
        if properties is not None and properties.get("date1904") in {"1", "true"}:
            raise ValueError("Época de datas Excel não reconhecida.")
        shared = _xml(archive, "xl/sharedStrings.xml")
        strings = [] if shared is None else ["".join(t.text or "" for t in item.iter(f"{{{NS['m']}}}t"))
                                             for item in shared.findall("m:si", NS)]
        sheet = _xml(archive, "xl/worksheets/sheet1.xml")
        if sheet is None:
            raise ValueError("Relatório vazio.")
    rows = {}
    for row in sheet.iterfind("m:sheetData/m:row", NS):
        for cell in row.findall("m:c", NS):
            column, number = _column(cell.get("r"))
            if column > 300 or number > MAX_ROWS + 1:
                raise ValueError("Dimensões do relatório fora do limite permitido.")
            rows.setdefault(number, {})[column] = _cell(cell, strings)
    titles = rows.pop(1, {})
    columns = {}
    for column, title in titles.items():
        field = HEADERS.get(_plain(title)) if isinstance(title, str) else None
        if field is None or field in columns.values():
            # Never a column the Coletor did not ask for (personal data the Ecossistema does not use).
            raise ValueError("Coluna não reconhecida no relatório.")
        columns[column] = field
    if set(columns.values()) != set(HEADERS.values()):
        raise ValueError("Colunas ausentes no relatório.")
    return [(number, {columns[c]: v for c, v in cells.items() if c in columns}) for number, cells in sorted(rows.items())]


def _text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Formato de texto inválido no relatório.")
    if len(value) > MAX_TEXT:
        raise ValueError("Texto acima do limite no relatório.")
    return value.strip()


def rows_from_workbook(data):
    """The Ecossistema's report rows (reportRowV1), one per enrolment of the school, in sheet order."""
    rows = []
    for number, cells in read_workbook(data):
        if not any(v not in (None, "") for v in cells.values()):
            continue
        if _plain(cells.get("school")) != _plain(SCHOOL):
            raise ValueError(f"O relatório não é da escola reconhecida ({SCHOOL}).")
        row = {"sourceRow": number, **{field: _text(cells.get(field)) for field in TEXT_FIELDS}}
        row["filiation1"] = _text(cells.get("filiation1")) or None
        for field in RAW_FIELDS:
            value = cells.get(field)
            if isinstance(value, str) and len(value) > 40:
                raise ValueError("Data ou código acima do limite no relatório.")
            row[field] = value
        rows.append(row)
    if not rows:
        raise ValueError("Relatório sem alunos.")
    if len(rows) > MAX_ROWS:
        raise ValueError("Relatório acima do limite.")
    return rows


def report_from_observation(value, year):
    """{'rows': [...]} from the worker's reading; refused unless it is this school's export."""
    if (type(value) is not dict or "error" in value or not matches_form(value.get("url"), year)
            or value.get("password_form") or value.get("context_organization") is not True
            or value.get("context_school") is not True):
        raise ValueError(f"O relatório não corresponde à escola reconhecida ({ORGANIZATION} / {SCHOOL}).")
    school = value.get("school")
    if (type(school) is not dict or not re.fullmatch(r"[1-9][0-9]{0,9}", str(school.get("id", "")))
            or _plain(school.get("name")) != _plain(SCHOOL)):
        raise ValueError("A escola atual da sessão do Smecel não é a reconhecida.")
    if value.get("status") != 200 or "spreadsheetml" not in str(value.get("type")):
        raise ValueError("O Smecel não devolveu o relatório.")
    try:
        data = base64.b64decode(value.get("xlsx") or "", validate=True)
    except (ValueError, TypeError):
        raise ValueError("Relatório não reconhecido.") from None
    return {"rows": rows_from_workbook(data)}
