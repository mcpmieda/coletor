"""Observed weekly-grid adapter (Smecel "Grade de horários", owner decision 22/10/2026).

One page holds every class: a block per class with its title, its Smecel id in the links and a table
of Monday to Friday by lesson position. Only the subject's full name is kept, exactly as the Smecel
stores it ("LINGUA PORTUGUESA", no accent added); the teacher is never read; a free position
("VAGA") is left out. Anything that does not match the recognized structure rejects the whole page.
"""
import re
from urllib.parse import parse_qsl, urlsplit

from .class_catalog import ORGANIZATION, SCHOOL
from .class_selection import ORIGIN

GRADE_PATH = "/sistema/escola/grade.php"
WEEKDAYS = ("SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA")
MAX_BLOCKS = 64
MAX_SUBJECT = 120

# The Smecel loads each class's table only when it comes into view (ajax/grade_turma.php, owner
# report 23/10/2026: "as tabelas só carregam quando desce tudo"). Before reading, every block is
# brought into view in turn and the page is given up to 30 s for all of them to arrive; the count
# still loading is returned, and a page with any left is never read.
SCHEDULE_LOAD_JS = """async () => {
  const pending=()=>document.querySelectorAll('div.grade-turma .skeleton-loading-container').length;
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  for(const block of document.querySelectorAll('div.grade-turma')){
    block.scrollIntoView({block:'center'});
    await wait(150);
  }
  const started=Date.now();
  while(pending()&&Date.now()-started<30000)await wait(250);
  window.scrollTo(0,0);
  return {pending:pending()};
}"""

SCHEDULE_JS = """() => {
  // textContent, not innerText: on a narrow window the Smecel hides the full names (CSS), and
  // innerText would read them as empty.
  const norm=s=>(s||'').normalize('NFC').replace(/\\s+/g,' ').trim();
  const text=norm(document.body.innerText);
  const blocks=[...document.querySelectorAll('div.grade-turma')];
  if(blocks.length>64)return {error:'schedule_too_large'};
  return {url:location.href,password_form:!!document.querySelector('input[type=password]'),
    context_organization:text.includes('SECRETARIA DE EDUCAÇÃO DE MEDEIROS NETO'),
    context_school:text.includes('ESCOLA IEDA ALVES DE OLIVEIRA MCPM'),
    years:[...text.matchAll(/\\d+ turmas Ano letivo (\\d{4})/g)].map(m=>Number(m[1])),
    blocks:blocks.map(block=>{
      const tables=block.querySelectorAll('table');
      const table=tables.length===1?tables[0]:null;
      return {title:norm(block.querySelector('h3')?.innerText),tables:tables.length,
        links:[...block.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')),
        days:table?[...table.querySelectorAll('thead th')].slice(1).map(th=>norm(th.querySelector('span.ls-display-none-xs')?.textContent)):[],
        rows:table?[...table.querySelectorAll('tbody tr')].map(tr=>[...tr.cells].map((td,i)=>i===0?{position:norm(td.innerText)}:{
          free:!!td.querySelector('.ls-color-warning')&&norm(td.innerText)==='VAGA',
          names:[...td.querySelectorAll('span.ls-display-none-xs')].map(s=>norm(s.textContent))})):[]};
    })};
}"""


def grade_url():
    return f"{ORIGIN}{GRADE_PATH}"


def matches_grade(url):
    from .manual_session import allowed_request
    if not isinstance(url, str) or not allowed_request(url):
        return False
    parts = urlsplit(url)
    return parts.path == GRADE_PATH and not parts.fragment and not parse_qsl(parts.query, keep_blank_values=True)


def _class_id(links):
    """The block's Smecel class id, the same in every link that names a class (anotações, editar,
    montagem); the frequency uses the same id (class_catalog's ct)."""
    ids = set()
    for href in links:
        if not isinstance(href, str):
            raise ValueError("Link da grade não reconhecido.")
        for key, value in parse_qsl(urlsplit(href).query, keep_blank_values=True):
            if key in {"turma", "c"}:
                ids.add(value)
    if len(ids) != 1 or not re.fullmatch(r"[1-9][0-9]{0,9}", next(iter(ids))):
        raise ValueError("A grade não identifica a turma de forma única.")
    return next(iter(ids))


def schedule_from_observation(value, year=2026):
    """{class_id: {'title', 'lessons': [{'weekday' 1-5, 'slot' 1-6, 'subject'}]}} for every block."""
    if (type(value) is not dict or not matches_grade(value.get("url")) or value.get("password_form")
            or value.get("context_organization") is not True or value.get("context_school") is not True
            or value.get("years") != [year]):
        raise ValueError(f"A grade não corresponde ao ano e à escola reconhecidos ({ORGANIZATION} / {SCHOOL}).")
    blocks = value.get("blocks")
    if type(blocks) is not list or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise ValueError("A grade está vazia ou fora do limite.")
    grids = {}
    for block in blocks:
        if type(block) is not dict or block.get("tables") != 1 or not isinstance(block.get("title"), str):
            raise ValueError("Um bloco da grade não corresponde à estrutura reconhecida.")
        class_id = _class_id(block.get("links") if type(block.get("links")) is list else [None])
        if class_id in grids:
            raise ValueError("Turma repetida na grade.")
        if block.get("days") != list(WEEKDAYS):
            raise ValueError("Os dias da grade não são segunda a sexta.")
        rows = block.get("rows")
        if type(rows) is not list or not 1 <= len(rows) <= 6:
            raise ValueError("As aulas da grade não estão entre a 1ª e a 6ª.")
        lessons = []
        for slot, row in enumerate(rows, start=1):
            if (type(row) is not list or len(row) != 6 or type(row[0]) is not dict
                    or row[0].get("position") != str(slot)):
                raise ValueError("Uma linha da grade não corresponde à estrutura reconhecida.")
            for weekday, cell in enumerate(row[1:], start=1):
                if type(cell) is not dict or type(cell.get("names")) is not list:
                    raise ValueError("Uma aula da grade não corresponde à estrutura reconhecida.")
                if cell.get("free") is True and not cell["names"]:
                    continue
                if (cell.get("free") is not False or len(cell["names"]) != 1 or type(cell["names"][0]) is not str
                        or not 1 <= len(cell["names"][0]) <= MAX_SUBJECT):
                    raise ValueError("Uma aula da grade não tem uma única disciplina reconhecida.")
                lessons.append({"weekday": weekday, "slot": slot, "subject": cell["names"][0]})
        grids[class_id] = {"title": " ".join(block["title"].split()), "lessons": lessons}
    return grids
