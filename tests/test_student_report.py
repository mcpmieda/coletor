"""The Smecel "Relatório de alunos" (owner decision 29/10/2026): reader and its own run, synthetic data."""
import base64
from datetime import datetime
import io
import threading
import unittest
import zipfile
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from coletor.device_provider import FrequencyError
from coletor.frequency_runtime import report_hash, report_times, validate_report_schedule
from coletor.manual_session import SessionError
from coletor.student_report import FIELDS, export_query, report_from_observation, rows_from_workbook
import tempfile
from coletor.frequency_runtime import FrequencyRuntime
from coletor.protected_storage import ProtectedStorage
from test_frequency_runtime import DEVICE, NOW, Access, Provider, Source, SyntheticCrypto

TITLES = ['Nome do aluno', 'Escola', 'Turma', 'Turno', 'Etapa', 'Situação da matrícula', 'Data da matrícula',
          'Data da transferência', 'Hash da matrícula', 'Código INEP', 'Nascimento', 'Filiação 1']
SCHOOL = 'ESCOLA IEDA ALVES DE OLIVEIRA MCPM'


def line(name='ALUNA SINTETICA UM', school=SCHOOL, transferred=None, status='MATRICULADO'):
    return [name, school, '6A 2026 - MATUTINO', 'MATUTINO', 'ENSINO FUNDAMENTAL DE 9 ANOS - 6º ANO', status,
            46023, transferred, 'hash-sintetico', 123456789012, 41640, 'MAE SINTETICA']


def xlsx(lines, titles=TITLES, date1904=False, formula=False):
    """A workbook shaped like the Smecel's export (SimpleXLSXGen): shared strings, numbers, empties."""
    strings, cells = [], []
    def ref(column, row): return f'{chr(65 + column)}{row}'
    for row, values in enumerate([titles, *lines], start=1):
        out = []
        for column, value in enumerate(values):
            if value is None: out.append(f'<c r="{ref(column, row)}"/>')
            elif isinstance(value, str):
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
                                   'inep': 123456789012, 'birthDate': 41640, 'enrolledAt': 46023, 'transferredAt': None})
        self.assertEqual((rows[1]['sourceRow'], rows[1]['transferredAt'], rows[1]['status']), (3, 46300, 'TRANSFERIDO'))
        # Integral Excel numbers stay ints: the hash is the same bytes as the Ecossistema's.
        self.assertIs(type(rows[1]['transferredAt']), int)

    def test_only_the_asked_columns_and_this_school(self):
        with self.assertRaisesRegex(ValueError, 'Coluna não reconhecida'):
            rows_from_workbook(xlsx([line() + ['000.000.000-00']], titles=TITLES + ['CPF']))
        with self.assertRaisesRegex(ValueError, 'Colunas ausentes'):
            rows_from_workbook(xlsx([line()[:-1]], titles=TITLES[:-1]))
        with self.assertRaisesRegex(ValueError, 'escola reconhecida'):
            rows_from_workbook(xlsx([line(school='OUTRA ESCOLA SINTETICA')]))
        with self.assertRaisesRegex(ValueError, 'Época de datas'):
            rows_from_workbook(xlsx([line()], date1904=True))
        with self.assertRaisesRegex(ValueError, 'Conteúdo inválido'):
            rows_from_workbook(xlsx([line()], formula=True))
        with self.assertRaises(ValueError):
            rows_from_workbook(b'not a zip')

    def test_the_export_asks_eleven_fields_every_situation_curricular_classes(self):
        query = export_query()
        self.assertEqual(len(FIELDS), 11)
        self.assertIn('situacao=&', query)
        self.assertIn('tipo_turma=C', query)
        self.assertNotIn('cpf', query)
        self.assertNotIn('escola_id', query)  # The page adds the session's own school.

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


PINNED_HASH = '0prs5ns-7GNFFBx7M8Tvr-DtB2o9mNDnRKGTfWrr6Ag'


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


if __name__ == '__main__':
    unittest.main()
