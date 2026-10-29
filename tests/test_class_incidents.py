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
            'rows': [{'href': first, 'name': 'ALUNA SINTETICA UM', 'count': 2},
                     {'href': second, 'name': 'ALUNO SINTETICO DOIS', 'count': 1}],
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
        self.assertEqual(first['sourceStudentId'], '101')
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
            lambda v: v['students'][v['rows'][0]['href']]['records'][0].update(year='2025'),
            lambda v: v['students'][v['rows'][0]['href']]['records'][0].update(date='2026-09-08'),
            lambda v: v['students'][v['rows'][0]['href']]['records'][2].update(leave='28/10/2026 até 22/10/2026'),
            # The same id with two different contents is never merged silently.
            lambda v: v['students'][v['rows'][0]['href']]['records'][1].update(description='Outra.'),
        ):
            value = observation()
            change(value)
            with self.assertRaises(ValueError):
                incidents_from_observation(value, YEAR)


if __name__ == '__main__':
    unittest.main()
