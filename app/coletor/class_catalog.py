"""Observed class-list adapter. It reads class metadata, never student links."""
import hashlib
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from .class_selection import ORIGIN, MAX_CLASSES

LIST_PATH = "/sistema/escola/turmaListar.php"
CLASS_LINK_PATH = "/sistema/escola/vinculoAlunoExibirTurma.php"
ORGANIZATION = "SECRETARIA DE EDUCAÇÃO DE MEDEIROS NETO"
SCHOOL = "ESCOLA IEDA ALVES DE OLIVEIRA MCPM"
CONTEXT_KEY = "school-display:" + hashlib.sha256((ORGANIZATION + "\n" + SCHOOL).encode()).hexdigest()

CATALOG_JS = """() => {
  const norm=s=>(s||'').normalize('NFC').replace(/\\s+/g,' ').trim();
  const text=norm(document.body.innerText);
  const years=[...document.querySelectorAll('a[role=combobox]')].map(n=>norm(n.innerText)).filter(s=>s.startsWith('ANO LETIVO:'));
  const search=document.querySelector('input[placeholder="Digite o nome ou parte do nome de uma turma"]');
  const rows=[...document.querySelectorAll('#tbodyTurmas tr')];
  if(rows.length>500)return {error:'catalog_too_large'};
  return {url:location.href,password_form:!!document.querySelector('input[type=password]'),
    recognized_table:document.querySelectorAll('#tabelaTurmas').length===1,
    context_organization:text.includes('SECRETARIA DE EDUCAÇÃO DE MEDEIROS NETO'),
    context_school:text.includes('ESCOLA IEDA ALVES DE OLIVEIRA MCPM'),
    title_years:[...(norm(document.title)+' '+text).matchAll(/Listar Turmas - Ano Letivo (\\d{4})/g)].map(m=>Number(m[1])),
    year_controls:years, search_present:!!search, filtered:!!search?.value.trim(),
    rows:rows.map(row=>{const c=row.cells;return {cells:c.length,visible:!!row.getClientRects().length,
      ordinal:norm(c[1]?.innerText),name:norm(c[3]?.innerText),stage:norm(c[4]?.innerText),
      matrix:norm(c[5]?.innerText),shift:norm(c[6]?.innerText),
      links:[...c[2]?.querySelectorAll('a[href]')||[]].map(a=>a.getAttribute('href'))};})};
}"""


def list_url(year):
    if type(year) is not int or not 2000 <= year <= 2100:
        raise ValueError("Informe um ano entre 2000 e 2100.")
    return f"{ORIGIN}{LIST_PATH}?ano={year}"


def matches_list(url, year):
    from .manual_session import allowed_request
    if not isinstance(url, str) or not allowed_request(url):
        return False
    parts = urlsplit(url)
    return parts.path == LIST_PATH and not parts.fragment and parse_qsl(parts.query, keep_blank_values=True) in ([], [("ano", str(year))])


def catalog_from_observation(value, year):
    if (type(value) is not dict or not matches_list(value.get("url"), year) or value.get("password_form")
            or value.get("recognized_table") is not True or value.get("search_present") is not True
            or value.get("context_organization") is not True or value.get("context_school") is not True
            or value.get("year_controls") != [f"ANO LETIVO: {year}"]
            or not value.get("title_years") or set(value["title_years"]) != {year}):
        raise ValueError("A lista não corresponde ao ano e ao contexto da escola reconhecidos. Confira a página no Smecel.")
    rows = value.get("rows")
    if type(rows) is not list or not 1 <= len(rows) <= MAX_CLASSES:
        raise ValueError("A lista está vazia ou fora do limite. Nenhuma seleção salva foi apagada.")
    classes, seen, ordinals = [], set(), []
    for row in rows:
        if type(row) is not dict or row.get("cells") != 7 or type(row.get("links")) is not list or len(row["links"]) != 1:
            raise ValueError("Uma linha da lista não corresponde à estrutura reconhecida.")
        href = row["links"][0]
        if not isinstance(href, str):
            raise ValueError("Link de turma não reconhecido.")
        link = urlsplit(urljoin(list_url(year), href))
        query = parse_qsl(link.query, keep_blank_values=True)
        if (link.scheme != "https" or link.netloc != "www.smecel.com.br" or link.path != CLASS_LINK_PATH
                or link.fragment or len(query) != 1 or query[0][0] != "ct"
                or not re.fullmatch(r"[1-9][0-9]{0,9}", query[0][1])):
            raise ValueError("Link de turma não reconhecido; nenhum link de alunos foi aberto.")
        key = query[0][1]
        if key in seen:
            raise ValueError("Código de turma duplicado na listagem.")
        seen.add(key)
        labels = {}
        for field in ("name", "stage", "matrix", "shift"):
            text = row.get(field)
            if type(text) is not str or not text.strip() or len(text) > 240:
                raise ValueError("Metadados de turma incompletos.")
            labels[field] = " ".join(text.split())
        if not re.fullmatch(r"[1-9][0-9]{0,3}", str(row.get("ordinal", ""))):
            raise ValueError("Ordem da listagem não reconhecida.")
        ordinals.append(int(row["ordinal"]))
        if row.get("visible") is True:
            classes.append({"class_id": key, "year": year, **labels})
    if not classes:
        raise ValueError("Nenhuma turma visível nesta lista. A seleção salva foi preservada.")
    return {"scope": {"origin": ORIGIN, "list_path": LIST_PATH, "year": year, "context_key": CONTEXT_KEY},
            "context_label": f"{ORGANIZATION} / {SCHOOL}", "classes": classes,
            "filtered": value.get("filtered") is True or len(classes) != len(rows) or ordinals != list(range(1, len(rows) + 1)),
            "observed_classes": len(classes), "list_complete_verified": False, "identity_verified": False}
