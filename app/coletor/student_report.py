"""Observed student report adapter (Smecel "Relatório de alunos", owner decision 29/10/2026).

The Smecel's own export link (relatorio_alunos_personalizado_xlsx.php) is fetched by the page the
worker loaded, with the session's own request: no click on the page and no file on this computer.
The school is the session's current one, as the Smecel's school switch lists it
(ajax/listar_escolas_usuario.php: escola_atual), never a number in this code; the year is the
Coletor's own (the class list's). Only the fields listed here are asked for (the student's name
always comes): the 11 the Ecossistema's Conciliação uses (FIELDS) and the enrolment form's data for
the online re-enrolment (PROFILE, issue #91). Never any other one (NEVER_ASKED).

The xlsx is a zip of XML: it is read here, in memory, with the standard library only. The
Conciliação's cells go raw as the ADM's reader takes them (text as text, dates and numbers as Excel
numbers), so the Ecossistema applies its own rules to them; the enrolment form's cells are
normalized here (see PROFILE). The form's data is personal (documents, address, phones, health):
it only ever goes to the Ecossistema, never to a log, the history, the window or a file.
"""
import base64
import io
import re
import unicodedata
import zipfile
from urllib.parse import parse_qsl, urlencode, urlsplit
from xml.etree import ElementTree

from .class_catalog import CONTEXT_JS, ORGANIZATION, SCHOOL
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
# The enrolment form's data (issue #91), for the Portal's online re-enrolment and the printed form:
# (Smecel field, column title, key in the row's `profile`, how the cell is normalized).
#   text    trimmed, inner spaces collapsed; a number cell (an RG, a house number) as its digits
#   cpf     11 digits; a number cell lost its leading zeros and gets them back
#   cep     8 digits, likewise
#   digits  digits only (phones with their DDD, the CNS)
#   degree  1 = Irmão/Irmã, 2 = Tio/Tia, 3 = Avô/Avó, 4 = Outro, as the Smecel's student form
#   flag    SIM / NAO as a boolean
# Anything empty or out of its shape is None, never guessed.
PROFILE = (
    # Fixed data: the guardian only checks it.
    ("aluno_sexo", "SEXO", "sex", "text"),
    ("aluno_nacionalidade", "NACIONALIDADE", "nationality", "text"),
    ("aluno_uf_nascimento", "UF NASCIMENTO", "birthState", "text"),
    ("aluno_municipio_nascimento", "MUNICIPIO NASCIMENTO", "birthCity", "text"),
    ("aluno_cpf", "CPF", "cpf", "cpf"),
    ("aluno_filiacao2", "FILIACAO 2", "filiation2", "text"),
    ("aluno_rg_mae", "RG FILIACAO 1", "filiation1Rg", "text"),
    ("aluno_rg_pai", "RG FILIACAO 2", "filiation2Rg", "text"),
    ("aluno_identidade", "RG", "rg", "text"),
    ("aluno_emissor", "ORGAO EMISSOR", "rgIssuer", "text"),
    ("aluno_uf_emissor", "UF EMISSOR", "rgIssuerState", "text"),
    ("aluno_sus", "CNS/SUS", "sus", "digits"),
    # Volatile data: the guardian may update it.
    ("aluno_raca", "RACA/COR", "race", "text"),
    ("aluno_celular", "CELULAR", "mobile", "digits"),
    ("aluno_cep", "CEP", "cep", "cep"),
    ("aluno_endereco", "ENDERECO", "address", "text"),
    ("aluno_numero", "NUMERO", "addressNumber", "text"),
    ("aluno_complemento", "COMPLEMENTO", "addressComplement", "text"),
    ("aluno_bairro", "BAIRRO", "district", "text"),
    ("aluno_municipio", "MUNICIPIO RESIDENCIA", "city", "text"),
    ("aluno_uf", "UF RESIDENCIA", "state", "text"),
    ("aluno_tel_mae", "TELEFONE FILIACAO 1", "filiation1Phone", "digits"),
    ("aluno_tel_pai", "TELEFONE FILIACAO 2", "filiation2Phone", "digits"),
    ("aluno_nome_responsavel_legal", "RESPONSAVEL LEGAL", "guardianName", "text"),
    ("aluno_grau_responsavel_legal", "GRAU DO RESPONSAVEL", "guardianDegree", "degree"),
    ("aluno_cpf_responsavel_legal", "CPF RESPONSAVEL", "guardianCpf", "cpf"),
    ("transporte", "TRANSPORTE ESCOLAR", "schoolTransport", "flag"),
    ("aluno_alergia", "ALERGIA", "allergy", "flag"),
    ("aluno_alergia_qual", "QUAL ALERGIA", "allergyDetail", "text"),
    ("aluno_recebe_bolsa_familia", "BOLSA FAMILIA", "bolsaFamilia", "flag"),
    # Only for the printed form (the school's data; never shown in the Portal).
    ("aluno_aluno_com_deficiencia", "PESSOA COM DEFICIENCIA", "disability", "flag"),
    ("aluno_def_bvisao", "BAIXA VISAO", "lowVision", "flag"),
    ("aluno_def_cegueira", "CEGUEIRA", "blindness", "flag"),
    ("aluno_def_auditiva", "DEFICIENCIA AUDITIVA", "hearingDisability", "flag"),
    ("aluno_def_fisica", "DEFICIENCIA FISICA", "physicalDisability", "flag"),
    ("aluno_def_intelectual", "DEFICIENCIA INTELECTUAL", "intellectualDisability", "flag"),
    ("aluno_def_autista", "TEA/AUTISMO", "autism", "flag"),
)
HEADERS.update({title: key for _, title, key, _ in PROFILE})
# Never asked for (issue #91): the Smecel offers them, the Ecossistema does not use them.
NEVER_ASKED = frozenset({
    "resultado_final", "repetente", "dependencia", "boletim", "verificacao", "aluno_nome_social", "idade",
    "aluno_localizacao", "aluno_nis", "aluno_certidao", "aluno_cpf_mae", "aluno_cpf_pai",
    "aluno_rg_responsavel_legal", "aluno_telefone", "aluno_email", "aluno_endereco_completo", "aluno_laudo",
    "aluno_condicao_saude_categoria", "aluno_condicao_saude_descricao", "aluno_condicao_saude_data",
    "aluno_condicao_saude_status", "aluno_sangue_tipo", "aluno_sangue_rh", "vacina_atualizada"})
MAX_DIGITS = 20
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
    CONTEXT_JS};
  const list=await fetch('ajax/listar_escolas_usuario.php',{credentials:'same-origin',redirect:'manual'});
  if(list.status!==200)return {...scope,error:'schools_unavailable'};
  const schools=await list.json();
  const current=(schools.escolas||[]).filter(e=>parseInt(e.escola_id)===schools.escola_atual);
  if(schools.success!==true||current.length!==1)return {...scope,error:'school_unknown'};
  const school={id:String(schools.escola_atual),name:norm(current[0].escola_nome)};
  const url='relatorio_alunos_personalizado_xlsx.php?ano='+year+'&escola_id='+school.id+'&'+query;
  const r=await fetch(url,{credentials:'same-origin',redirect:'manual'});
  const buf=new Uint8Array(await r.arrayBuffer());
  if(buf.length>MAX_XLSX_BYTES)return {...scope,school,error:'report_too_large'};
  let s='';for(let i=0;i<buf.length;i+=0x8000)s+=String.fromCharCode(...buf.subarray(i,i+0x8000));
  return {...scope,school,status:r.status,type:r.headers.get('content-type'),size:buf.length,xlsx:btoa(s)};
}""".replace("MAX_XLSX_BYTES", str(MAX_XLSX_BYTES)).replace("CONTEXT_JS", CONTEXT_JS)


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
    choice), only FIELDS and PROFILE; ano and escola_id are added by the page from the session."""
    filters = [("turma_id", ""), ("situacao", ""), ("tipo_turma", "C"), ("turno", ""), ("etapa_id", ""),
               ("transporte", ""), ("deficiencia", ""), ("bolsa", ""), ("raca", ""), ("busca", "")]
    return urlencode(filters + [("campos[]", field) for field in (*FIELDS, *(item[0] for item in PROFILE))])


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
    # No document type, so no entity of any kind can expand inside the parser. The check reads
    # bytes: a part in UTF-16 or UTF-32 (a zero byte among its first ones) would hide one from it.
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw or b"\0" in raw[:256]:
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
    missing = sorted(title for title, field in HEADERS.items() if field not in columns.values())
    if missing:
        raise ValueError("Colunas ausentes no relatório: " + ", ".join(missing) + ".")
    return [(number, {columns[c]: v for c, v in cells.items() if c in columns}) for number, cells in sorted(rows.items())]


def _text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Formato de texto inválido no relatório.")
    if len(value) > MAX_TEXT:
        raise ValueError("Texto acima do limite no relatório.")
    return value.strip()


def _plain_text(value):
    """A profile text: trimmed, inner spaces collapsed, empty as None; a number cell as its digits."""
    if isinstance(value, int):
        value = str(value)
    elif isinstance(value, float):
        value = repr(value)
    elif value is not None and not isinstance(value, str):
        raise ValueError("Formato de texto inválido no relatório.")
    text = " ".join((value or "").split())
    if len(text) > MAX_TEXT:
        raise ValueError("Texto acima do limite no relatório.")
    return text or None


def _only_digits(value):
    """The digits of a cell; an integral number cell written out in full (never 1.2E+10). A fraction
    or a text with letters ("ISENTO", "1.2E+10", "não tem") is no document or phone number."""
    text = "" if isinstance(value, float) else _plain_text(value) or ""
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) <= MAX_DIGITS and not re.search(r"[^\W\d_]", text) else ""


def _padded(value, size):
    digits = _only_digits(value)
    return digits.zfill(size) if 0 < len(digits) <= size else None


def _flag(value):
    return {"SIM": True, "S": True, "NAO": False, "N": False}.get(_plain(value)) if isinstance(value, str) else None


def _degree(value):
    if isinstance(value, str) and re.fullmatch(r"\s*[1-4]\s*", value):
        value = int(value)
    return value if type(value) is int and 1 <= value <= 4 else None


PROFILE_READERS = {"text": _plain_text, "cpf": lambda value: _padded(value, 11), "cep": lambda value: _padded(value, 8),
                   "digits": lambda value: _only_digits(value) or None, "degree": _degree, "flag": _flag}


def rows_from_workbook(data):
    """The Ecossistema's report rows, one per enrolment of the school, in sheet order: the
    Conciliação's fields (reportRowV1) and the enrolment form's data under `profile`."""
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
        row["profile"] = {key: PROFILE_READERS[kind](cells.get(key)) for _, _, key, kind in PROFILE}
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
