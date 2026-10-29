"""Observed incidents adapter (Smecel "Ocorrências", owner decision 29/10/2026).

The list page (ocorrencias.php, filtered by the school year) names every student with an incident
in that year, 30 per page, with how many each one has; the eye opens the student's page
(ocorrencias_aluno.php), which already holds every incident in full: no click is needed. Both are
read with the session's own requests, the pages in turn and the students a few at a time, in the
page the worker loaded itself. The list repeats a "ranking" table on every page: only the second
table (the list) is read.

A student with two enrolments of the year (AEE, atividade complementar, a second one in the same
class) has each incident shown twice on the student's page, with the same Smecel id: one record per
id is kept. The reading is complete only when every page and every student was read and each
student's incidents match the count of the list, and only a complete reading may make the
Ecossistema mark a record as removed.
"""
import re
from datetime import date
from urllib.parse import parse_qsl, urlsplit

from .class_catalog import ORGANIZATION, SCHOOL
from .class_selection import ORIGIN

LIST_PATH = "/sistema/escola/ocorrencias.php"
STUDENT_PATH = "/sistema/escola/ocorrencias_aluno.php"
MAX_STUDENTS = 5000
MAX_INCIDENTS = 500
MAX_DESCRIPTION = 8000
SMECEL_ID = re.compile(r"[1-9][0-9]{0,11}")

# Runs in the list page the worker loaded. The number of pages comes from the page itself
# ("171 alunos e turmas no filtro atual, 30 por página"), never from this code.
INCIDENTS_JS = """async (year) => {
  const norm=s=>(s||'').normalize('NFC').replace(/\\s+/g,' ').trim();
  const parse=html=>new DOMParser().parseFromString(html,'text/html');
  const get=async url=>{const r=await fetch(url,{credentials:'same-origin',redirect:'manual'});
    if(r.status!==200)throw new Error('status');return parse(await r.text());};
  const text=norm(document.body.innerText);
  const scope={url:location.href,password_form:!!document.querySelector('input[type=password]'),
    context_organization:text.includes('SECRETARIA DE EDUCAÇÃO DE MEDEIROS NETO'),
    context_school:text.includes('ESCOLA IEDA ALVES DE OLIVEIRA MCPM'),
    year_selected:document.querySelector('select[name=ano]')?.value??null};
  const counter=text.match(/(\\d+) alunos e turmas no filtro atual, (\\d+) por página/);
  if(!counter)return {...scope,error:'incidents_counter_missing'};
  const total=Number(counter[1]),perPage=Number(counter[2]);
  const pages=Math.max(1,Math.ceil(total/perPage));
  const rowsOf=doc=>{const table=doc.querySelectorAll('table')[1];
    return table?[...table.querySelectorAll('tbody tr')].map(tr=>{const a=tr.querySelector('a[href*="ocorrencias_aluno.php"]');
      return {href:a?.getAttribute('href')??null,name:norm(tr.cells[1]?.textContent),
        count:Number(norm(tr.querySelector('strong')?.textContent))};}):null;};
  const rows=[],failedPages=[];
  for(let page=1;page<=pages;page++){
    try{const found=rowsOf(page===1?document:await get(`ocorrencias.php?ano=${year}&turma=&aluno=&origem=&aba=lista&pagina=${page}`));
      if(found===null)failedPages.push(page);else rows.push(...found);}
    catch{failedPages.push(page);}
  }
  const field=(box,label)=>{const strong=[...box.querySelectorAll('strong')].find(s=>norm(s.textContent)===label+':');
    if(!strong)return null;let value='';for(let n=strong.nextSibling;n&&n.nodeName!=='BR'&&n.nodeName!=='STRONG';n=n.nextSibling)value+=n.textContent;
    return norm(value);};
  const student=async href=>{const doc=await get(href);
    const enrolments=[...(doc.querySelector('table')?.querySelectorAll('tbody tr')??[])].map(tr=>({year:norm(tr.cells[0]?.textContent),label:norm(tr.cells[1]?.textContent)}));
    const records=[...doc.querySelectorAll('.ls-box')].map(box=>{const print=box.querySelector('a[href*="print_ocorrencia.php?ocorrencia="]');
      if(!print)return null;const title=box.querySelector('h5');
      return {id:new URL(print.getAttribute('href'),location.href).searchParams.get('ocorrencia'),
        kind:norm(title?.childNodes[0]?.textContent),heading:norm(title?.querySelector('small')?.textContent),
        type:field(box,'TIPO'),date:field(box,'DATA'),year:field(box,'ANO LETIVO'),
        leave:field(box,'PERÍODO DE AFASTAMENTO'),leave_days:field(box,'TOTAL DE DIAS EM AFASTAMENTO'),
        description:norm(box.querySelector('i')?.textContent)};}).filter(Boolean);
    return {enrolments,records};};
  const hrefs=[...new Set(rows.map(r=>r.href).filter(Boolean))];
  const students={},failedStudents=[];
  for(let i=0;i<hrefs.length;i+=8)
    await Promise.all(hrefs.slice(i,i+8).map(async href=>{try{students[href]=await student(href);}catch{failedStudents.push(href);}}));
  return {...scope,total,per_page:perPage,pages,failed_pages:failedPages,rows,students,failed_students:failedStudents};
}"""


def list_url(year):
    return f"{ORIGIN}{LIST_PATH}?ano={year}&aba=lista"


def matches_list(url, year):
    from .manual_session import allowed_request
    if not isinstance(url, str) or not allowed_request(url):
        return False
    parts = urlsplit(url)
    return (parts.path == LIST_PATH and not parts.fragment
            and sorted(parse_qsl(parts.query, keep_blank_values=True)) == [("aba", "lista"), ("ano", str(year))])


def _student_id(href, year):
    parts = urlsplit(href) if isinstance(href, str) else None
    query = dict(parse_qsl(parts.query, keep_blank_values=True)) if parts else {}
    if (parts is None or parts.path.rsplit("/", 1)[-1] != STUDENT_PATH.rsplit("/", 1)[-1]
            or set(query) != {"aluno", "ano_letivo"} or query["ano_letivo"] != str(year)
            or not SMECEL_ID.fullmatch(query["aluno"])):
        raise ValueError("Link de aluno das ocorrências não reconhecido.")
    return query["aluno"]


def _date(value):
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value or "")
    if not match:
        raise ValueError("Data de ocorrência não reconhecida.")
    return date(int(match[3]), int(match[2]), int(match[1])).isoformat()


def _leave(period, days):
    """A suspension's leave. The Smecel leaves its start, its end or its days blank at times
    ("até 24/11/2026", "14/09/2026 até", "até" with no days, seen on 29/10/2026): a blank part is
    None, never guessed; a leave with nothing at all is no leave."""
    match = re.fullmatch(r"(\S*) ?até ?(\S*)", period)
    if not match or not isinstance(days, str) or not re.fullmatch(r"\d{0,3}", days):
        raise ValueError("Afastamento da ocorrência não reconhecido.")
    leave = {"from": _date(match[1]) if match[1] else None, "to": _date(match[2]) if match[2] else None,
             "days": int(days) if days else None}
    if (leave["from"] and leave["to"] and leave["from"] > leave["to"]) or (leave["days"] or 0) > 366:
        raise ValueError("Afastamento da ocorrência não reconhecido.")
    return leave if any(value is not None for value in leave.values()) else None


def _record(record, year):
    """One incident as the Ecossistema contract takes it; None when it cannot be read whole."""
    if type(record) is not dict or not isinstance(record.get("id"), str) or not SMECEL_ID.fullmatch(record["id"]):
        raise ValueError("Ocorrência sem identificador do Smecel.")
    kind, heading, description = record.get("type"), record.get("heading"), record.get("description")
    prefix = f"({year} - "
    if (not isinstance(kind, str) or not 1 <= len(kind) <= 80 or record.get("kind") != kind
            or record.get("year") != str(year) or not isinstance(heading, str)
            or not heading.startswith(prefix) or not heading.endswith(")")):
        raise ValueError("Ocorrência fora da estrutura reconhecida.")
    label = heading[len(prefix):-1].strip()
    if not isinstance(description, str) or not 1 <= len(description) <= MAX_DESCRIPTION or not 1 <= len(label) <= 300:
        return None  # Not refused: the reading is just not complete.
    occurred = _date(record.get("date"))
    leave = None if record.get("leave") is None else _leave(record["leave"], record.get("leave_days"))
    return {"sourceIncidentId": record["id"], "kind": kind, "date": occurred, "sourceClassLabel": label,
            "leave": leave, "description": description}


def incidents_from_observation(value, year):
    """{'complete': bool, 'students': [{'sourceStudentId', 'name', 'classLabels', 'incidents'}]}."""
    if (type(value) is not dict or "error" in value or not matches_list(value.get("url"), year)
            or value.get("password_form") or value.get("context_organization") is not True
            or value.get("context_school") is not True or value.get("year_selected") != str(year)):
        raise ValueError(f"As ocorrências não correspondem ao ano e à escola reconhecidos ({ORGANIZATION} / {SCHOOL}).")
    rows, observed = value.get("rows"), value.get("students")
    if type(rows) is not list or type(observed) is not dict or type(value.get("total")) is not int:
        raise ValueError("A lista de ocorrências não corresponde à estrutura reconhecida.")
    complete = not value.get("failed_pages") and not value.get("failed_students") and len(rows) == value["total"]
    counts, names = {}, {}
    for row in rows:
        if type(row) is not dict or not isinstance(row.get("name"), str) or type(row.get("count")) is not int:
            raise ValueError("Uma linha da lista de ocorrências não corresponde à estrutura reconhecida.")
        student = _student_id(row.get("href"), year)
        # A student listed in two classes shows the same total in each row.
        counts[student] = max(counts.get(student, 0), row["count"])
        names.setdefault(student, row["name"])
    students = []
    for href, page in observed.items():
        student = _student_id(href, year)
        if type(page) is not dict or type(page.get("records")) is not list or type(page.get("enrolments")) is not list:
            raise ValueError("A página de ocorrências do aluno não corresponde à estrutura reconhecida.")
        incidents, unreadable = {}, False
        for raw in page["records"]:
            record = _record(raw, year)
            if record is None:
                unreadable = True
            elif incidents.setdefault(record["sourceIncidentId"], record) != record:
                raise ValueError("A mesma ocorrência aparece com conteúdos diferentes.")
        if unreadable or len(incidents) != counts.get(student) or len(incidents) > MAX_INCIDENTS:
            complete = False
        labels = sorted({e["label"] for e in page["enrolments"]
                         if type(e) is dict and e.get("year") == str(year) and isinstance(e.get("label"), str) and e["label"]})
        if incidents and 1 <= len(names.get(student, "")) <= 300:
            students.append({"sourceStudentId": student, "name": names[student], "classLabels": labels,
                             "incidents": sorted(incidents.values(), key=lambda i: int(i["sourceIncidentId"]))[:MAX_INCIDENTS]})
    if len(students) > MAX_STUDENTS:
        raise ValueError("Ocorrências acima do limite.")
    return {"complete": complete and len(students) == len(counts), "students": students}
