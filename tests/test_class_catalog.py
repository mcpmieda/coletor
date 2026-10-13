"""Synthetic table observations following the verified class-only DOM contract."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from coletor.class_catalog import catalog_from_observation, list_url, CONTEXT_KEY


def observed(year=2026):
    return {'url': list_url(year), 'password_form': False, 'recognized_table': True,
            'search_present': True, 'context_organization': True, 'context_school': True,
            'title_years': [year], 'year_controls': [f'ANO LETIVO: {year}'], 'filtered': False,
            'rows': [{'cells': 7, 'visible': True, 'ordinal': str(i), 'name': f'Turma sintética {i} -VESPERTINO',
                      'stage': 'Etapa sintética', 'matrix': 'Matriz sintética', 'shift': 'VESPERTINO',
                      'links': [f'vinculoAlunoExibirTurma.php?ct={10+i}']} for i in (1,2)]}


class ClassCatalogTests(unittest.TestCase):
    def test_names_and_ids_are_dynamic_from_same_row_not_hardcoded(self):
        result = catalog_from_observation(observed(), 2026)
        self.assertEqual([c['class_id'] for c in result['classes']], ['11','12'])
        self.assertEqual(result['classes'][1]['name'], 'Turma sintética 2 -VESPERTINO')
        self.assertFalse(result['identity_verified'])
        self.assertFalse(result['list_complete_verified'])
        self.assertEqual(result['scope']['context_key'], CONTEXT_KEY)
        self.assertNotIn('links', result['classes'][0])

    def test_year_is_explicit_and_never_inferred_from_class_id(self):
        data=observed(2025)
        self.assertEqual(catalog_from_observation(data,2025)['classes'][0]['year'],2025)
        with self.assertRaises(ValueError): catalog_from_observation(data,2026)
        for changes in ({'year_controls':['ANO LETIVO: 2024']},{'title_years':[2024]},{'url':list_url(2024)}):
            with self.assertRaises(ValueError):catalog_from_observation({**data,**changes},2025)

    def test_filtered_hidden_and_gapped_rows_are_partial_and_not_revocation(self):
        data=observed();data['rows'][1]['visible']=False
        result=catalog_from_observation(data,2026)
        self.assertTrue(result['filtered']);self.assertEqual(len(result['classes']),1)
        data=observed();data['rows'][1]['ordinal']='5'
        self.assertTrue(catalog_from_observation(data,2026)['filtered'])
        self.assertTrue(catalog_from_observation({**observed(),'filtered':True},2026)['filtered'])

    def test_unknown_context_login_duplicates_and_foreign_links_fail_closed(self):
        for changes in ({'context_school':False},{'password_form':True},{'recognized_table':False},{'search_present':False}):
            with self.assertRaises(ValueError):catalog_from_observation({**observed(),**changes},2026)
        for href in ('https://unapproved.invalid/vinculoAlunoExibirTurma.php?ct=11',
                     'vinculoAlunoExibirTurma.php?ct=11&token=SYNTHETIC_ONLY','aluno.php?id=11'):
            data=observed();data['rows'][0]['links']=[href]
            with self.assertRaises(ValueError):catalog_from_observation(data,2026)
        data=observed();data['rows'][1]['links']=data['rows'][0]['links']
        with self.assertRaises(ValueError):catalog_from_observation(data,2026)


if __name__=='__main__':unittest.main()
