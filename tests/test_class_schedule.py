"""The weekly-grid adapter with synthetic classes (owner decision 22/10/2026); no real page."""
import copy
import unittest

from coletor.class_schedule import grade_url, matches_grade, schedule_from_observation

DAYS = ['SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA']


def cell(name=None): return {'free': name is None, 'names': [] if name is None else [name]}
def row(slot, *cells): return [{'position': str(slot)}, *cells]


def page():
    return {'url': grade_url(), 'password_form': False, 'context_organization': True, 'context_school': True,
            'years': [2026], 'blocks': [
        {'title': 'TURMA  SINTÉTICA A - MATUTINO', 'tables': 1,
         'links': ['anotacoes_turma.php?turma=13331', 'horariosEditar.php?c=13331',
                   'horario_gerar.php?escopo=turma&turma=13331&ano=2026'],
         'days': list(DAYS), 'rows': [
            row(1, cell('DISCIPLINA UM'), cell('DISCIPLINA DOIS'), cell('DISCIPLINA UM'), cell('DISCIPLINA TRES'), cell('DISCIPLINA UM')),
            row(2, cell(), cell('DISCIPLINA DOIS'), cell('PRÁTICA SINTÉTICA'), cell(), cell('DISCIPLINA TRES'))]},
        {'title': 'TURMA SINTÉTICA B - VESPERTINO', 'tables': 1,
         'links': ['anotacoes_turma.php?turma=13332', 'horariosEditar.php?c=13332'],
         'days': list(DAYS), 'rows': [row(1, *[cell('DISCIPLINA UM')] * 5)]}]}


class ClassScheduleTests(unittest.TestCase):
    def test_every_class_keeps_its_smecel_id_and_the_subject_exactly_as_stored(self):
        grids = schedule_from_observation(page())
        self.assertEqual(set(grids), {'13331', '13332'})
        self.assertEqual(grids['13331']['title'], 'TURMA SINTÉTICA A - MATUTINO')
        lessons = grids['13331']['lessons']
        # A free position ("VAGA") is left out: 10 positions, 2 free.
        self.assertEqual(len(lessons), 8)
        self.assertEqual(lessons[0], {'weekday': 1, 'slot': 1, 'subject': 'DISCIPLINA UM'})
        self.assertNotIn((1, 2), {(l['weekday'], l['slot']) for l in lessons})
        # The accent is the Smecel's own; nothing is added or taken away.
        self.assertIn({'weekday': 3, 'slot': 2, 'subject': 'PRÁTICA SINTÉTICA'}, lessons)
        self.assertEqual(len(grids['13332']['lessons']), 5)

    def test_only_the_grid_page_itself_is_recognized(self):
        self.assertTrue(matches_grade(grade_url()))
        for url in (grade_url() + '?turma=1', grade_url() + '#x', 'https://example.com/sistema/escola/grade.php',
                    grade_url().replace('grade.php', 'turmaListar.php'), None):
            self.assertFalse(matches_grade(url), url)

    def test_anything_outside_the_recognized_structure_rejects_the_whole_page(self):
        def broken(change):
            value = page()
            change(value)
            return value
        block = lambda v: v['blocks'][0]
        cases = {
            'another page': lambda v: v.update(url=grade_url() + '?ano=2025'),
            'login form': lambda v: v.update(password_form=True),
            'another school': lambda v: v.update(context_school=False),
            'another organization': lambda v: v.update(context_organization=False),
            'another year': lambda v: v.update(years=[2025]),
            'two years': lambda v: v.update(years=[2026, 2026]),
            'no class': lambda v: v.update(blocks=[]),
            'too many classes': lambda v: v.update(blocks=[copy.deepcopy(block(v))] * 65),
            'repeated class': lambda v: v['blocks'].append(copy.deepcopy(block(v))),
            'two tables': lambda v: block(v).update(tables=2),
            'no title': lambda v: block(v).update(title=None),
            'two class ids': lambda v: block(v)['links'].append('anotacoes_turma.php?turma=99'),
            'no class id': lambda v: block(v).update(links=['grade.php']),
            'odd class id': lambda v: block(v).update(links=['anotacoes_turma.php?turma=013331']),
            'weekend': lambda v: block(v).update(days=DAYS + ['SÁBADO']),
            'days out of order': lambda v: block(v).update(days=list(reversed(DAYS))),
            'no lessons': lambda v: block(v).update(rows=[]),
            'seventh lesson': lambda v: block(v).update(rows=[row(n, *[cell('X')] * 5) for n in range(1, 8)]),
            'position out of order': lambda v: block(v)['rows'][1][0].update(position='3'),
            'short row': lambda v: block(v)['rows'][0].pop(),
            'two subjects in one lesson': lambda v: block(v)['rows'][0][1].update(names=['A', 'B']),
            'free with a subject': lambda v: block(v)['rows'][0][1].update(free=True),
            'empty subject': lambda v: block(v)['rows'][0][1].update(names=['']),
            'subject too long': lambda v: block(v)['rows'][0][1].update(names=['A' * 121]),
            'not free and empty': lambda v: block(v)['rows'][1][1].update(free=False),
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                schedule_from_observation(broken(change))
        for value in (None, [], 'grade', {'error': 'page_changed'}):
            with self.subTest(value), self.assertRaises(ValueError):
                schedule_from_observation(value)


if __name__ == '__main__':
    unittest.main()
