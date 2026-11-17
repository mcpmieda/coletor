"""The Smecel "Relatório de alunos" (owner decision 29/10/2026): reader and its own run, synthetic data."""
import base64
from datetime import datetime
import io
import json
from pathlib import Path
import threading
import unittest
import zipfile
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from coletor.device_provider import FrequencyError
from coletor.frequency_runtime import report_hash, report_times, validate_report_schedule
from coletor.manual_session import SessionError
from coletor.student_report import (FIELDS, NEVER_ASKED, PROFILE, export_query, report_from_observation,
                                    rows_from_workbook)
import tempfile
from coletor.frequency_runtime import FrequencyRuntime
from coletor.protected_storage import ProtectedStorage
from test_frequency_runtime import DEVICE, NOW, Access, Provider, Source, SyntheticCrypto

CORE_TITLES = ['Nome do aluno', 'Escola', 'Turma', 'Turno', 'Etapa', 'Situação da matrícula', 'Data da matrícula',
               'Data da transferência', 'Hash da matrícula', 'Código INEP', 'Nascimento', 'Filiação 1']
# The enrolment form's columns (issue #91) as the Smecel titles them, each with a synthetic cell as the
# export lays it (a CPF, a CEP and the phones as numbers, SIM/NAO as text, empties) and what is sent.
FORM = [('Sexo', 'FEMININO', 'FEMININO'), ('Nacionalidade', 'BRASILEIRA', 'BRASILEIRA'), ('UF nascimento', 'BA', 'BA'),
        ('Município nascimento', 'CIDADE  SINTETICA', 'CIDADE SINTETICA'), ('CPF', 1234567890, '01234567890'),
        ('Filiação 2', ' PAI SINTETICO ', 'PAI SINTETICO'), ('RG filiação 1', 1234567890, '1234567890'),
        ('RG filiação 2', None, None), ('RG', '12.345.678-90', '12.345.678-90'), ('Órgão emissor', 'SSP', 'SSP'),
        ('UF emissor', 'BA', 'BA'), ('CNS/SUS', 700000000000001, '700000000000001'), ('Raça/cor', 'PARDA', 'PARDA'),
        ('Celular', 73999990000, '73999990000'), ('CEP', 5990000, '05990000'), ('Endereço', 'RUA SINTETICA', 'RUA SINTETICA'),
        ('Número', 120, '120'), ('Complemento', None, None), ('Bairro', 'CENTRO', 'CENTRO'),
        ('Município residência', 'CIDADE SINTETICA', 'CIDADE SINTETICA'), ('UF residência', 'BA', 'BA'),
        ('Telefone filiação 1', 73999990001, '73999990001'), ('Telefone filiação 2', None, None),
        ('Responsável legal', 'AVO SINTETICA', 'AVO SINTETICA'), ('Grau do responsável', 3, 3),
        ('CPF responsável', '00000000191', '00000000191'), ('Transporte escolar', 'SIM', True), ('Alergia', 'NAO', False),
        ('Qual alergia', None, None), ('Bolsa Família', 'SIM', True), ('Pessoa com deficiência', 'NAO', False),
        ('Baixa visão', 'NAO', False), ('Cegueira', 'NAO', False), ('Deficiência auditiva', 'NAO', False),
        ('Deficiência física', 'NAO', False), ('Deficiência intelectual', 'NAO', False), ('TEA/autismo', 'NAO', False)]
TITLES = CORE_TITLES + [title for title, _, _ in FORM]
PROFILE_SENT = {item[2]: sent for item, (_, _, sent) in zip(PROFILE, FORM)}
SCHOOL = 'ESCOLA IEDA ALVES DE OLIVEIRA MCPM'


def line(name='ALUNA SINTETICA UM', school=SCHOOL, transferred=None, status='MATRICULADO', **form):
    """One row of the export; form: a column of the enrolment form (by its profile key) with another cell."""
    cells = {item[2]: cell for item, (_, cell, _) in zip(PROFILE, FORM)}
    cells.update(form)
    return [name, school, '6A 2026 - MATUTINO', 'MATUTINO', 'ENSINO FUNDAMENTAL DE 9 ANOS - 6º ANO', status,
            46023, transferred, 'hash-sintetico', 123456789012, 41640, 'MAE SINTETICA', *cells.values()]


def letters(column):
    """The sheet's column name: 0 = A, 25 = Z, 26 = AA (the export has 49 columns)."""
    name = ''
    column += 1
    while column:
        column, rest = divmod(column - 1, 26)
        name = chr(65 + rest) + name
    return name


class Raw(str):
    """A number cell whose value is written in the sheet's XML exactly as given."""


def xlsx(lines, titles=TITLES, date1904=False, formula=False):
    """A workbook shaped like the Smecel's export (SimpleXLSXGen): shared strings, numbers, empties."""
    strings, cells = [], []
    def ref(column, row): return f'{letters(column)}{row}'
    for row, values in enumerate([titles, *lines], start=1):
        out = []
        for column, value in enumerate(values):
            if value is None: out.append(f'<c r="{ref(column, row)}"/>')
            elif isinstance(value, str) and not isinstance(value, Raw):
                strings.append(value)
                out.append(f'<c r="{ref(column, row)}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                body = '<f>1+1</f>' if formula and row == 2 and column == 6 else ''
                out.append(f'<c r="{ref(column, row)}" s="3">{body}<v>{value}</v></c>')
        cells.append(f'<row r="{row}">{"".join(out)}</row>')
    main = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        pr = '<workbookPr date1904="1"/>' if date1904 else ''
        archive.writestr('xl/workbook.xml', f'<workbook {main}>{pr}<sheets><sheet name="Alunos" sheetId="1"/></sheets></workbook>')
        archive.writestr('xl/sharedStrings.xml', f'<sst {main}>' + ''.join(f'<si><t>{escape(s)}</t></si>' for s in strings) + '</sst>')
        archive.writestr('xl/worksheets/sheet1.xml', f'<worksheet {main}><sheetData>{"".join(cells)}</sheetData></worksheet>')
    return buffer.getvalue()


class ReaderTests(unittest.TestCase):
    def test_rows_raw_like_the_adm_reader(self):
        rows = rows_from_workbook(xlsx([line(), line('ALUNO SINTETICO DOIS', transferred=46300, status='TRANSFERIDO')]))
        self.assertEqual(rows[0], {'sourceRow': 2, 'name': 'ALUNA SINTETICA UM', 'classLabel': '6A 2026 - MATUTINO',
                                   'shift': 'MATUTINO', 'stageLabel': 'ENSINO FUNDAMENTAL DE 9 ANOS - 6º ANO',
                                   'status': 'MATRICULADO', 'enrollmentHash': 'hash-sintetico', 'filiation1': 'MAE SINTETICA',
                                   'inep': 123456789012, 'birthDate': 41640, 'enrolledAt': 46023, 'transferredAt': None,
                                   'profile': PROFILE_SENT})
        self.assertEqual((rows[1]['sourceRow'], rows[1]['transferredAt'], rows[1]['status']), (3, 46300, 'TRANSFERIDO'))
        # Integral Excel numbers stay ints: the hash is the same bytes as the Ecossistema's.
        self.assertIs(type(rows[1]['transferredAt']), int)

    def test_only_the_asked_columns_and_this_school(self):
        for extra in ('NIS', 'CPF filiação 1', 'Telefone', 'E-mail', 'Tipo sanguíneo'):  # Never asked for.
            with self.assertRaisesRegex(ValueError, 'Coluna não reconhecida'):
                rows_from_workbook(xlsx([line() + ['dado sintetico']], titles=TITLES + [extra]))
        with self.assertRaisesRegex(ValueError, 'Coluna não reconhecida'):  # The same column twice.
            rows_from_workbook(xlsx([line() + ['BA']], titles=TITLES + ['UF emissor']))
        # A column that did not come is named, so the failure says what is missing.
        with self.assertRaisesRegex(ValueError, r'Colunas ausentes no relatório: TEA/AUTISMO\.'):
            rows_from_workbook(xlsx([line()[:-1]], titles=TITLES[:-1]))
        without = [i for i, title in enumerate(TITLES) if title not in ('CPF', 'Filiação 1')]
        with self.assertRaisesRegex(ValueError, r'Colunas ausentes no relatório: CPF, FILIACAO 1\.'):
            rows_from_workbook(xlsx([[line()[i] for i in without]], titles=[TITLES[i] for i in without]))
        with self.assertRaisesRegex(ValueError, 'escola reconhecida'):
            rows_from_workbook(xlsx([line(school='OUTRA ESCOLA SINTETICA')]))
        with self.assertRaisesRegex(ValueError, 'Época de datas'):
            rows_from_workbook(xlsx([line()], date1904=True))
        with self.assertRaisesRegex(ValueError, 'Conteúdo inválido'):
            rows_from_workbook(xlsx([line()], formula=True))
        with self.assertRaises(ValueError):
            rows_from_workbook(b'not a zip')

    def test_the_export_asks_only_the_listed_fields_every_situation_curricular_classes(self):
        query = export_query()
        asked = [value for key, value in parse_qsl(query, keep_blank_values=True) if key == 'campos[]']
        # Exactly the Conciliação's 11 and the enrolment form's 37 (issue #91), each once.
        self.assertEqual(asked, [*FIELDS, *(item[0] for item in PROFILE)])
        self.assertEqual((len(FIELDS), len(PROFILE), len(set(asked))), (11, 37, 48))
        self.assertEqual(set(asked) & NEVER_ASKED, set())
        self.assertEqual(len(NEVER_ASKED), 24)
        self.assertIn('situacao=&', query)
        self.assertIn('tipo_turma=C', query)
        self.assertNotIn('escola_id', query)  # The page adds the session's own school.

    def read(self, **form):
        return rows_from_workbook(xlsx([line(**form)]))[0]['profile']

    def test_cpf_and_cep_keep_their_leading_zeros(self):
        # A number cell lost them: they come back.
        self.assertEqual(self.read(cpf=1234567890)['cpf'], '01234567890')
        self.assertEqual(self.read(cpf=191)['cpf'], '00000000191')
        self.assertEqual(self.read(guardianCpf=12345678909)['guardianCpf'], '12345678909')
        self.assertEqual(self.read(cpf='012.345.678-90')['cpf'], '01234567890')
        self.assertEqual(self.read(cpf='01234567890')['cpf'], '01234567890')
        self.assertEqual(self.read(cep=5990000)['cep'], '05990000')
        self.assertEqual(self.read(cep='05990-000')['cep'], '05990000')
        self.assertEqual(self.read(cep=45960000)['cep'], '45960000')
        # More digits than the document has, a fraction or no digit at all: nothing, never a guess.
        for cell in (123456789012, 1234567890.5, 'ISENTO', '', None):
            self.assertIsNone(self.read(cpf=cell)['cpf'])

    def test_zeros_never_make_a_document_out_of_something_else(self):
        # A date, part of a CPF or a phone typed in the CPF field, padded, looked like a document.
        for cell in ('12/03/2010', '123.456.789', 0, '000.000.000-00', '(73) 99999-0000', 11111111111, 1234567891):
            self.assertIsNone(self.read(cpf=cell)['cpf'], cell)
            self.assertIsNone(self.read(guardianCpf=cell)['guardianCpf'], cell)
        for cell in (4596, '4596', '999-999', 0):  # CEPs start at 01000-000.
            self.assertIsNone(self.read(cep=cell)['cep'], cell)
        self.assertEqual(self.read(cep=1000000)['cep'], '01000000')

    def test_digits_of_another_script_are_no_number(self):
        # The Ecossistema takes 0-9 only: one such cell had the whole report refused.
        for cell in ('０１２３４５６７８９０', '0123456789٠', '७३९९९९९००००'):
            profile = self.read(cpf=cell, mobile=cell, sus=cell, cep=cell)
            self.assertEqual((profile['cpf'], profile['mobile'], profile['sus'], profile['cep']), (None, None, None, None))
        self.assertIsNone(self.read(cep=123456789)['cep'])

    def test_a_number_cell_is_written_out_in_full_never_in_scientific_notation(self):
        # The sheet's XML may hold a long number as 1.23456789E+9 or 7.00000000000001E+14.
        self.assertEqual(self.read(cpf=Raw('1.23456789E+9'), sus=Raw('7.00000000000001E+14'), mobile=Raw('7.399999E+10')),
                         {**PROFILE_SENT, 'cpf': '01234567890', 'sus': '700000000000001', 'mobile': '73999990000'})
        # The same notation typed as text is no number at all.
        self.assertIsNone(self.read(cpf='1.23456789E+9')['cpf'])

    def test_phones_only_digits_with_their_ddd(self):
        self.assertEqual(self.read(mobile='(73) 99999-0000')['mobile'], '73999990000')
        self.assertEqual(self.read(filiation1Phone=7333330000)['filiation1Phone'], '7333330000')
        self.assertIsNone(self.read(filiation2Phone='não tem')['filiation2Phone'])
        self.assertIsNone(self.read(mobile='9' * 21)['mobile'])

    def test_text_trimmed_collapsed_and_empty_as_none(self):
        profile = self.read(address='  RUA   SINTETICA \t 2 ', addressNumber='S/N', addressComplement='   ', rgIssuer=2403769002)
        self.assertEqual((profile['address'], profile['addressNumber'], profile['addressComplement'], profile['rgIssuer']),
                         ('RUA SINTETICA 2', 'S/N', None, '2403769002'))
        # A text longer than the Ecossistema takes is left out; the rest of the report still goes.
        profile = self.read(address='A' * 301, allergyDetail='B ' * 200, mobile='9' * 301, district='C' * 300)
        self.assertEqual((profile['address'], profile['allergyDetail'], profile['mobile'], profile['district'], profile['cpf']),
                         (None, None, None, 'C' * 300, PROFILE_SENT['cpf']))

    def test_guardian_degree_is_one_to_four(self):
        for cell, sent in ((1, 1), (4, 4), ('2', 2), (0, None), (5, None), (2.5, None), ('TIO', None), (None, None)):
            self.assertEqual(self.read(guardianDegree=cell)['guardianDegree'], sent)

    def test_yes_and_no_are_booleans(self):
        for cell, sent in (('SIM', True), ('Sim', True), ('NAO', False), ('Não', False), ('', None), (None, None),
                           ('TALVEZ', None), (1, None)):
            self.assertIs(self.read(allergy=cell)['allergy'], sent)
        flags = [item[2] for item in PROFILE if item[3] == 'flag']
        self.assertEqual(len(flags), 10)
        for key in flags:
            self.assertIs(self.read(**{key: 'SIM'})[key], True)

    def test_observation_from_the_form_page_of_this_school(self):
        good = {'url': 'https://www.smecel.com.br/sistema/escola/relatorio_alunos_personalizado.php?ano=2026&situacao=1',
                'password_form': False, 'context_organization': True, 'context_school': True,
                'school': {'id': '341', 'name': SCHOOL}, 'status': 200,
                'type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'xlsx': base64.b64encode(xlsx([line()])).decode()}
        self.assertEqual(len(report_from_observation(good, 2026)['rows']), 1)
        for change in ({'school': {'id': '341', 'name': 'OUTRA ESCOLA'}}, {'password_form': True}, {'status': 302},
                       {'url': 'https://www.smecel.com.br/index.php'}, {'error': 'school_unknown'}):
            with self.assertRaises(ValueError): report_from_observation({**good, **change}, 2026)
        with self.assertRaises(ValueError): report_from_observation(good, 2025)


class ScheduleTests(unittest.TestCase):
    def test_times_and_limits(self):
        agenda = {'timezone': 'America/Bahia', 'enabled': True, 'every': 45, 'from': '07:10', 'to': '09:00', 'weekdays': [1, 2]}
        self.assertEqual(report_times(validate_report_schedule(agenda)), ['07:10', '07:55', '08:40'])
        self.assertEqual(report_times({**agenda, 'enabled': False}), [])
        for change in ({'every': 15}, {'from': '10:00'}, {'weekdays': [1, 1]}, {'timezone': 'Nowhere/Place'}, {'extra': 1}):
            with self.assertRaises(FrequencyError): validate_report_schedule({**agenda, **change})

    def test_hash_is_the_ecossistema_one(self):
        # Pinned with studentReportHashV2 (server/attendance/service-v2.ts) on the same synthetic rows;
        # tests/attendance/student-report-v2.test.ts pins the same value there.
        rows = rows_from_workbook(xlsx([line(), line('ALUNO SINTETICO DOIS', transferred=46300, status='TRANSFERIDO')]))
        self.assertEqual(report_hash(list(reversed(rows))), PINNED_HASH)
        # The Smecel swaps rows that tie from one export to the next: the position never counts.
        moved = [dict(rows[0], sourceRow=3), dict(rows[1], sourceRow=2)]
        self.assertEqual(report_hash(moved), PINNED_HASH)
        self.assertNotEqual(report_hash([dict(rows[0], transferredAt=46301), rows[1]]), PINNED_HASH)

    def test_hash_changes_with_any_field_of_the_enrolment_form(self):
        # A phone or an address changed in the Smecel sends the whole report (issue #91).
        rows = rows_from_workbook(xlsx([line()]))
        seen = {report_hash(rows)}
        for _, _, key, kind in PROFILE:
            other = {'text': 'OUTRO TEXTO SINTETICO', 'cpf': '98765432100', 'cep': '11111111', 'digits': '11999990000',
                     'degree': 1, 'flag': not rows[0]['profile'][key]}[kind]
            seen.add(report_hash([dict(rows[0], profile={**rows[0]['profile'], key: other})]))
        self.assertEqual(len(seen), len(PROFILE) + 1)


PINNED_HASH = 'UJiS35CRBdZZ0j-atvPpsO-81chuk_CexsuqK7DbnUI'


class ReportProvider(Provider):
    def __init__(self):
        super().__init__()
        self.held = None  # The hash of the last report the "server" applied.
        self.outcomes = []  # What the next full reports answer ('applied' when empty).
        self.agenda = None
    def frequency_request(self, payload):
        operation = payload['operation']
        if operation == 'status':
            value = super().frequency_request(payload)
            value['settings']['reportSchedule'] = self.agenda
            value['studentReport'] = None
            return value
        if operation not in {'student-report-collect', 'student-report-unchanged', 'save-report-settings'}:
            return super().frequency_request(payload)
        self.requests.append(payload)
        result = {'contractVersion': 2, 'state': 'committed', 'operation': operation, 'requestId': payload['requestId']}
        if operation == 'save-report-settings':
            self.agenda = payload['reportSchedule']
            result['settingsRevision'] = payload['expectedRevision'] + 1
        elif operation == 'student-report-unchanged':
            if payload['contentHash'] != self.held: raise FrequencyError('payload-required')
            result.update(changed=False, outcome='applied', rows=payload['rows'], linked=1, pending=0, differences=0, invalid=0)
        else:
            if payload['fencingToken'] != self.fence: raise FrequencyError('lease-fenced')
            outcome = self.outcomes.pop(0) if self.outcomes else 'applied'
            if outcome != 'preparing': self.held = report_hash(payload['rows'])
            result.update(changed=True, outcome=outcome, rows=len(payload['rows']), linked=1, pending=1, differences=1, invalid=1)
        self.results[payload['requestId']] = result
        return result


class ReportRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.provider, self.access, self.source = ReportProvider(), Access(), Source()
        self.storage = ProtectedStorage(self.directory.name, crypto=SyntheticCrypto(), consent=lambda: True, clock=lambda: self.provider.now)
        self.storage.bind(DEVICE, 1)
        self.runtime = FrequencyRuntime(self.access, self.provider, self.source, storage=self.storage, clock=lambda: self.provider.now)
        self.runtime._active = True
        self.addCleanup(self.runtime.shutdown)
        self.rows = rows_from_workbook(xlsx([line()]))
        self.reads = 0
        def read(year):
            self.reads += 1
            return {'rows': self.rows}
        self.source.operational_student_report = read

    def sent(self, operation): return [r for r in self.provider.requests if r['operation'] == operation]

    def test_whole_report_then_only_the_hash_while_unchanged(self):
        status = self.runtime.collect_report()
        self.assertFalse(status['report']['running'])
        self.assertIsNone(status['report']['code'])
        full = self.sent('student-report-collect')
        self.assertEqual(len(full), 1)
        self.assertEqual(full[0]['rows'], self.rows)
        self.assertEqual(full[0]['academicYear'], 2026)
        # The same report again: only its hash.
        self.runtime.collect_report()
        self.assertEqual(len(self.sent('student-report-collect')), 1)
        short = self.sent('student-report-unchanged')
        self.assertEqual((len(short), short[0]['contentHash'], short[0]['rows']), (1, report_hash(self.rows), 1))
        self.assertNotIn('ALUNA', str(short[0]))
        # The server holds another one (restored, another computer): the whole report goes.
        self.provider.held = 'other'
        self.runtime.collect_report()
        self.assertEqual(len(self.sent('student-report-collect')), 2)
        history = [e for e in self.runtime.recent_history(50) if e['kind'].startswith('report-')]
        finished = [e for e in history if e['kind'] == 'report-finished']
        self.assertEqual(len(finished), 3)
        self.assertEqual(finished[1].get('unchanged'), True)  # Newest first: the short one is the middle.
        self.assertEqual((finished[0]['sent'], finished[0]['unresolved'], finished[0]['conflicts']), (1, 1, 2))

    def test_the_enrolment_form_goes_only_to_the_ecossistema(self):
        # Issue #91: documents, address, phones and health flags never reach the history, the
        # window's status or a file of this computer; the local copy is the hash alone.
        self.storage.enable()           # The copies go to disk, protected by Windows.
        self.runtime.collect_report()   # The whole report.
        self.runtime.collect_report()   # Unchanged: the short message.
        sent = self.sent('student-report-collect')[0]['rows'][0]['profile']
        self.assertEqual(sent, PROFILE_SENT)
        personal = {str(value) for value in PROFILE_SENT.values() if isinstance(value, str)} | {'ALUNA SINTETICA', 'MAE SINTETICA'}
        self.assertEqual(self.storage.load_copy('student-report'),
                         {'contentHash': report_hash(self.rows), 'sentOn': self.storage.load_copy('student-report')['sentOn']})
        # Without what changes from run to run (a random id, a duration): '120', the synthetic house
        # number, turned up inside a requestId once in a few hundred runs (17/11/2026).
        steady = lambda items, *drop: [{k: v for k, v in item.items() if k not in drop} for item in items]
        shown = json.dumps([steady(self.runtime.recent_history(50), 'readMs', 'sendMs'), self.runtime.public_status(),
                            steady(self.sent('student-report-unchanged'), 'requestId')], ensure_ascii=False, default=str)
        on_disk = b''.join(bytes(b ^ 91 for b in path.read_bytes()) + path.read_bytes()   # SyntheticCrypto is a XOR.
                           for path in Path(self.directory.name).rglob('*') if path.is_file())
        self.assertIn(b'contentHash', on_disk)
        for value in personal:
            self.assertNotIn(value, shown)
            self.assertNotIn(value.encode(), on_disk)

    def test_a_browser_that_could_not_be_closed_after_the_report_went_is_no_failed_report(self):
        def held(storage): raise SessionError('A sessão foi interrompida, mas a limpeza não terminou.')
        self.source.preserve_and_close = held
        status = self.runtime.collect_report()
        self.assertIsNone(status['report']['code'])
        self.assertEqual([e['kind'] for e in self.runtime.recent_history(20)][:2], ['report-finished', 'report-started'])

    def test_whole_report_once_a_day(self):
        self.runtime.collect_report()
        self.provider.now += 86400
        self.runtime.collect_report()
        self.assertEqual(len(self.sent('student-report-collect')), 2)
        self.assertEqual(self.sent('student-report-unchanged'), [])

    def test_credentials_in_parts_send_the_same_report_again_until_applied(self):
        self.provider.outcomes = ['preparing', 'preparing', 'applied']
        self.runtime.collect_report()
        full = self.sent('student-report-collect')
        self.assertEqual(len(full), 3)
        self.assertEqual(len({r['requestId'] for r in full}), 3)
        self.assertEqual({str(r['rows']) for r in full}, {str(self.rows)})

    def test_a_report_left_for_review_is_noted(self):
        self.provider.outcomes = ['review']
        self.runtime.collect_report()
        finished = next(e for e in self.runtime.recent_history(20) if e['kind'] == 'report-finished')
        self.assertEqual(finished['code'], 'REPORT_REVIEW')

    def test_a_failed_read_is_the_report_s_own_and_never_the_frequency_s(self):
        def broken(year): raise SessionError('SOURCE_READ_FAILED')
        self.source.operational_student_report = broken
        status = self.runtime.collect_report()
        self.assertEqual(status['report']['code'], 'SOURCE_READ_FAILED')
        self.assertNotEqual(status['state'], 'error')
        self.assertEqual([e.get('code') for e in self.runtime.recent_history(20) if e['kind'] == 'report-failed'],
                         ['SOURCE_READ_FAILED'])
        self.assertEqual(self.sent('student-report-collect'), [])

    def test_another_computer_with_the_concession_reads_it_and_this_one_reads_nothing(self):
        # 10/11/2026: both computers read the Smecel at every time; the one without the concession
        # threw it away and its history showed a run "interrupted before finishing".
        self.provider.fail_lease = True
        status = self.runtime.collect_report()
        self.assertEqual(status['report']['code'], 'lease-busy')
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.sent('student-report-collect'), [])
        self.assertFalse(any(e['kind'].startswith('report-') for e in self.runtime.recent_history(20)))

    def test_save_report_agenda(self):
        agenda = {'timezone': 'America/Bahia', 'enabled': True, 'every': 30, 'from': '07:00', 'to': '17:00', 'weekdays': [1]}
        self.runtime.save_report_settings(0, agenda)
        self.assertEqual(self.provider.agenda, agenda)
        with self.assertRaises(FrequencyError): self.runtime.save_report_settings(0, {**agenda, 'every': 10})

    def at(self, hhmm):
        """Moves the clock to that time of NOW's day in the school's zone."""
        day = datetime.fromtimestamp(NOW, ZoneInfo('America/Bahia'))
        hour, minute = map(int, hhmm.split(':'))
        self.provider.now = day.replace(hour=hour, minute=minute, second=5).timestamp()
        return (day.weekday() + 1) % 7

    def test_the_agenda_starts_it_and_a_busy_time_runs_once_after(self):
        weekday = self.at('08:00')
        self.provider.agenda = {'timezone': 'America/Bahia', 'enabled': True, 'every': 30, 'from': '08:00', 'to': '09:00', 'weekdays': [weekday]}
        started = threading.Event()
        self.runtime.collect_report = lambda _claimed=False: started.set()
        # A run going on (its own status checks see the agenda): the time waits.
        self.runtime._fresh()
        self.runtime._operation.acquire()
        self.runtime.tick()
        self.assertFalse(started.is_set())
        self.runtime._operation.release()
        self.at('08:10')  # Not a time of the agenda: the waiting one runs, once.
        self.runtime.tick()
        self.assertTrue(started.wait(2))
        started.clear()
        self.runtime.tick()
        self.assertFalse(started.wait(0.2))
        # The next time of the agenda.
        self.at('08:30')
        self.runtime.tick()
        self.assertTrue(started.wait(2))

    def test_off_or_another_weekday_never_starts_it(self):
        weekday = self.at('08:00')
        started = threading.Event()
        self.runtime.collect_report = lambda _claimed=False: started.set()
        for agenda in ({'timezone': 'America/Bahia', 'enabled': False, 'every': 30, 'from': '08:00', 'to': '09:00', 'weekdays': [weekday]},
                       {'timezone': 'America/Bahia', 'enabled': True, 'every': 30, 'from': '08:00', 'to': '09:00', 'weekdays': [(weekday + 1) % 7]},
                       None):
            self.provider.agenda = agenda
            self.runtime._report_fired.clear()
            self.runtime.tick()
            self.assertFalse(started.wait(0.1))

    def test_the_report_alone_paused_skips_its_times_and_the_frequency_pause_is_untouched(self):
        # Owner request 05/11/2026: a pause of the report's own, on this computer.
        weekday = self.at('08:00')
        self.provider.agenda = {'timezone': 'America/Bahia', 'enabled': True, 'every': 30, 'from': '08:00', 'to': '09:00', 'weekdays': [weekday]}
        started = threading.Event()
        self.runtime.collect_report = lambda _claimed=False: started.set()
        status = self.runtime.report_pause(True)
        self.assertTrue(status['report']['paused'])
        self.assertFalse(status['localPaused'])
        self.runtime.tick()
        self.assertFalse(started.wait(0.2))
        # A time skipped while paused is not run on resuming; the next one is.
        self.assertFalse(self.runtime.report_pause(False)['report']['paused'])
        self.at('08:10')
        self.runtime.tick()
        self.assertFalse(started.wait(0.2))
        self.at('08:30')
        self.runtime.tick()
        self.assertTrue(started.wait(2))
        kinds = [e['kind'] for e in self.runtime.recent_history(50)]
        self.assertEqual([k for k in kinds if k.startswith('report-')], ['report-resumed', 'report-paused'])

    def test_a_report_asked_while_paused_reads_nothing(self):
        self.runtime.report_pause(True)
        status = self.runtime.collect_report()
        self.assertEqual(status['report']['code'], 'CANCELLED')
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.sent('student-report-collect'), [])

    def test_restoring_the_saved_pause_at_opening_writes_no_history(self):
        self.runtime.report_pause(True, record=False)
        self.assertTrue(self.runtime.public_status()['report']['paused'])
        self.assertFalse(any(e['kind'] == 'report-paused' for e in self.runtime.recent_history(50)))


if __name__ == '__main__':
    unittest.main()
