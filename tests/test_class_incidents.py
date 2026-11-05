"""Synthetic Smecel "Ocorrências" observations (owner decision 29/10/2026): no real student data."""
import copy
import unittest

from coletor.class_incidents import incidents_from_observation

YEAR = 2026
LIST = 'https://www.smecel.com.br/sistema/escola/ocorrencias.php?ano=2026&aba=lista'


def record(identifier, **fields):
    value = {'id': identifier, 'kind': 'ADVERTÊNCIA', 'type': 'ADVERTÊNCIA', 'heading': '(2026 - 6A 2026 - MATUTINO)',
             'date': '08/09/2026', 'year': '2026', 'leave': None, 'leave_days': None,
             'description': 'Descrição sintética.'}
    value.update(fields)
    return value


def observation():
    first = 'ocorrencias_aluno.php?aluno=101&ano_letivo=2026'
    second = 'ocorrencias_aluno.php?aluno=102&ano_letivo=2026'
    suspension = record('9002', kind='SUSPENSÃO', type='SUSPENSÃO', leave='22/10/2026 até 28/10/2026', leave_days='03')
    return {'url': LIST, 'password_form': False, 'context_organization': True, 'context_school': True,
            'year_selected': '2026', 'total': 2, 'per_page': 30, 'pages': 1, 'failed_pages': [], 'failed_students': [],
            'rows': [{'href': first, 'name': 'ALUNA SINTETICA UM', 'class_label': '6A 2026 - MATUTINO', 'count': 2},
                     {'href': second, 'name': 'ALUNO SINTETICO DOIS', 'class_label': '7B 2026 - MATUTINO', 'count': 1}],
            'students': {
                # Two enrolments of the year: every record shows twice, with the same id.
                first: {'enrolments': [{'year': '2026', 'label': '6A 2026 - MATUTINO'},
                                       {'year': '2026', 'label': 'MULTIFUNCIONAL MATUTINO'},
                                       {'year': '2025', 'label': '5A 2025 - MATUTINO'}],
                        'records': [record('9001'), record('9001'), suspension, copy.deepcopy(suspension)]},
                second: {'enrolments': [{'year': '2026', 'label': '7B 2026 - MATUTINO'}],
                         'records': [record('9003', heading='(2026 - 7B 2026 - MATUTINO)')]},
            }}


class IncidentsTests(unittest.TestCase):
    def test_one_record_per_smecel_id_with_the_year_classes_and_the_leave(self):
        value = incidents_from_observation(observation(), YEAR)
        self.assertTrue(value['complete'])
        first, second = value['students']
        self.assertEqual((first['sourceStudentId'], first['name']), ('101', 'ALUNA SINTETICA UM'))
        self.assertEqual(first['classLabels'], ['6A 2026 - MATUTINO', 'MULTIFUNCIONAL MATUTINO'])
        self.assertEqual([i['sourceIncidentId'] for i in first['incidents']], ['9001', '9002'])
        self.assertEqual(first['incidents'][0], {'sourceIncidentId': '9001', 'kind': 'ADVERTÊNCIA', 'date': '2026-09-08',
                                                 'sourceClassLabel': '6A 2026 - MATUTINO', 'leave': None,
                                                 'description': 'Descrição sintética.'})
        self.assertEqual(first['incidents'][1]['leave'], {'from': '2026-10-22', 'to': '2026-10-28', 'days': 3})
        self.assertEqual(second['incidents'][0]['sourceClassLabel'], '7B 2026 - MATUTINO')

    def test_a_leave_with_blank_parts_keeps_only_what_the_smecel_shows(self):
        for period, days, expected in (
            ('até 24/11/2026', '02', {'from': None, 'to': '2026-11-24', 'days': 2}),
            ('14/09/2026 até', '01', {'from': '2026-09-14', 'to': None, 'days': 1}),
            ('até', '03', {'from': None, 'to': None, 'days': 3}),
            ('até', '', None),
        ):
            value = observation()
            value['students'][value['rows'][1]['href']]['records'][0].update(
                kind='SUSPENSÃO', type='SUSPENSÃO', leave=period, leave_days=days)
            reading = incidents_from_observation(value, YEAR)
            self.assertTrue(reading['complete'])
            self.assertEqual(reading['students'][1]['incidents'][0]['leave'], expected)

    def test_anything_short_of_the_list_counts_is_not_complete(self):
        for change in (
            lambda v: v['failed_pages'].append(2),
            lambda v: v['failed_students'].append(v['rows'][1]['href']),
            lambda v: v.update(total=3),
            lambda v: v['rows'][0].update(count=3),
            lambda v: v['students'][v['rows'][1]['href']]['records'][0].update(description=''),
        ):
            value = observation()
            change(value)
            self.assertFalse(incidents_from_observation(value, YEAR)['complete'])

    def test_another_year_school_or_structure_is_refused(self):
        for change in (
            lambda v: v.update(year_selected='2025'),
            lambda v: v.update(password_form=True),
            lambda v: v.update(context_school=False),
            lambda v: v.update(url=LIST.replace('2026', '2025')),
            lambda v: v['rows'][0].update(href='ocorrencias_aluno.php?aluno=101&ano_letivo=2025'),
            # The class in place of the student's name (the first real reading, 29/10/2026).
            lambda v: v['rows'][0].update(name='6A 2026 - MATUTINO'),
        ):
            value = observation()
            change(value)
            with self.assertRaises(ValueError):
                incidents_from_observation(value, YEAR)

    def test_a_leave_shown_as_31_12_1969_goes_blank_with_a_notice_naming_the_student(self):
        # 05/11/2026: "14/09/2026 até 31/12/1969" (the Smecel's empty date) stopped every incident.
        value = observation()
        value['students'][value['rows'][1]['href']]['records'][0].update(
            kind='SUSPENSÃO', type='SUSPENSÃO', leave='14/09/2026 até 31/12/1969', leave_days='01')
        reading = incidents_from_observation(value, YEAR)
        self.assertTrue(reading['complete'])
        self.assertEqual(reading['students'][1]['incidents'][0]['leave'], {'from': '2026-09-14', 'to': None, 'days': 1})
        self.assertEqual(len(reading['notices']), 1)
        notice = reading['notices'][0]
        self.assertEqual((notice['name'], notice['classLabel'], notice['incident'], notice['sent']),
                         ('ALUNO SINTETICO DOIS', '7B 2026 - MATUTINO', '9003', True))
        self.assertIn('31/12/1969', notice['reason'])

    def test_the_same_blank_leave_under_two_enrolments_is_noticed_once(self):
        value = observation()
        for record in value['students'][value['rows'][0]['href']]['records'][2:]:
            record.update(leave='31/12/1969 até 28/10/2026')
        reading = incidents_from_observation(value, YEAR)
        self.assertTrue(reading['complete'])
        self.assertEqual([(n['name'], n['incident']) for n in reading['notices']], [('ALUNA SINTETICA UM', '9002')])
        self.assertEqual(reading['students'][0]['incidents'][1]['leave'], {'from': None, 'to': '2026-10-28', 'days': 3})

    def test_one_incident_out_of_shape_is_left_out_and_the_rest_still_goes(self):
        first = lambda v: v['students'][v['rows'][0]['href']]['records']
        for change, number, reason in (
            (lambda v: [r.update(year='2025') for r in first(v)[:2]], '9001', 'tipo, ano letivo ou turma'),
            (lambda v: [r.update(date='2026-09-08') for r in first(v)[:2]], '9001', 'data da ocorrência'),
            (lambda v: [r.update(date='31/02/2026') for r in first(v)[:2]], '9001', 'data da ocorrência'),
            (lambda v: [r.update(leave='28/10/2026 até 22/10/2026') for r in first(v)[2:]], '9002', 'afastamento'),
            (lambda v: [r.update(leave='de 22/10 a 28/10') for r in first(v)[2:]], '9002', 'afastamento'),
            # The same id with two different contents is never merged silently: neither goes.
            (lambda v: first(v)[1].update(description='Outra.'), '9001', 'conteúdos diferentes'),
        ):
            value = observation()
            change(value)
            reading = incidents_from_observation(value, YEAR)
            self.assertFalse(reading['complete'])  # Nothing is taken as removed.
            sent = {i['sourceIncidentId'] for s in reading['students'] for i in s['incidents']}
            self.assertNotIn(number, sent)
            self.assertIn('9003', sent)
            self.assertEqual(len(reading['notices']), 1)
            notice = reading['notices'][0]
            self.assertEqual((notice['name'], notice['classLabel'], notice['incident'], notice['sent']),
                             ('ALUNA SINTETICA UM', '6A 2026 - MATUTINO', number, False))
            self.assertIn(reason, notice['reason'])
            self.assertIn('não enviada', notice['reason'])

    def test_a_student_with_every_incident_out_of_shape_goes_without_them(self):
        value = observation()
        value['students'][value['rows'][1]['href']]['records'][0].update(id='abc')
        reading = incidents_from_observation(value, YEAR)
        self.assertFalse(reading['complete'])
        self.assertEqual([s['sourceStudentId'] for s in reading['students']], ['101'])
        self.assertEqual([(n['name'], n['incident']) for n in reading['notices']], [('ALUNO SINTETICO DOIS', None)])


if __name__ == '__main__':
    unittest.main()
