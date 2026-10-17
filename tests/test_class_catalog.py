"""Synthetic table observations following the verified class-only DOM contract."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from coletor.class_catalog import catalog_from_observation, list_url, CONTEXT_KEY


def observed(year=2026):
    return {'url': list_url(year), 'password_form': False, 'recognized_table': True,
            'search_present': True, 'columns_recognized': True, 'context_organization': True, 'context_school': True,
            'title_years': [year], 'year_controls': [f'ANO LETIVO: {year}'], 'filtered': False,
            'rows': [{'visible': True, 'ordinal': str(i), 'name': f'Turma sintética {i} -VESPERTINO',
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

    def test_link_with_the_list_year_is_recognized(self):
        # Shape observed on 17/10/2026: vinculoAlunoExibirTurma.php?ct=...&ano=<list year>.
        data=observed()
        for row in data['rows']: row['links']=[row['links'][0]+'&ano=2026']
        self.assertEqual([c['class_id'] for c in catalog_from_observation(data,2026)['classes']],['11','12'])
        for href in ('vinculoAlunoExibirTurma.php?ct=11&ano=2025','vinculoAlunoExibirTurma.php?ano=2026&ct=11',
                     'vinculoAlunoExibirTurma.php?ct=11&ano=2026&x=1'):
            data=observed();data['rows'][0]['links']=[href]
            with self.assertRaises(ValueError):catalog_from_observation(data,2026)

    def test_columns_must_be_found_by_header_title(self):
        # Column count/order is free; a missing or duplicated title fails closed.
        with self.assertRaises(ValueError):catalog_from_observation({**observed(),'columns_recognized':False},2026)
        data=observed();del data['columns_recognized']
        with self.assertRaises(ValueError):catalog_from_observation(data,2026)


class VendoredScriptTests(unittest.TestCase):
    def test_only_the_pinned_jquery_is_served_locally(self):
        from coletor.manual_worker import vendored_script
        body=vendored_script('https://code.jquery.com/jquery-2.1.4.min.js')
        self.assertTrue(body.startswith(b'/*! jQuery v2.1.4'))
        for url in ('https://code.jquery.com/jquery-3.7.1.min.js','https://cdn.jsdelivr.net/npm/sweetalert2@11',
                    'https://www.googletagmanager.com/gtag/js','http://code.jquery.com/jquery-2.1.4.min.js'):
            self.assertIsNone(vendored_script(url))

    def test_a_tampered_bundled_file_is_refused(self):
        import coletor.manual_worker as worker
        from unittest import mock
        original=worker.VENDORED_SCRIPTS
        with mock.patch.object(worker,'VENDORED_SCRIPTS',{k:(v[0],'0'*64) for k,v in original.items()}):
            self.assertIsNone(worker.vendored_script('https://code.jquery.com/jquery-2.1.4.min.js'))


class ReadingAssetTests(unittest.TestCase):
    def test_reading_pages_refuse_pictures_fonts_and_media_only(self):
        from types import SimpleNamespace
        from coletor.manual_worker import reading_page_asset
        origin = 'https://www.smecel.com.br'
        def request(kind, page):
            return SimpleNamespace(resource_type=kind, frame=SimpleNamespace(url=origin + page))
        diary = '/sistema/escola/diario_frequencia.php?ct=13331&ano=2026'
        listing = '/sistema/escola/turmaListar.php?ano=2026'
        for kind in ('image', 'font', 'media'):
            self.assertTrue(reading_page_asset(request(kind, diary)))
            self.assertTrue(reading_page_asset(request(kind, listing)))
            # The login page keeps its pictures for the person who signs in.
            self.assertFalse(reading_page_asset(request(kind, '/index.php')))
        for kind in ('document', 'script', 'stylesheet', 'xhr', 'fetch'):
            self.assertFalse(reading_page_asset(request(kind, listing)))
        lookalike = SimpleNamespace(resource_type='image', frame=SimpleNamespace(url='https://smecel.example' + diary))
        self.assertFalse(reading_page_asset(lookalike))
        class Detached:
            resource_type = 'image'
            @property
            def frame(self): raise RuntimeError('service worker')
        self.assertFalse(reading_page_asset(Detached()))

    def test_list_wait_ends_on_rows_or_a_login_form(self):
        from coletor.manual_worker import LIST_SETTLED_JS
        self.assertIn('input[type="password"]', LIST_SETTLED_JS)
        self.assertIn('vinculoAlunoExibirTurma.php', LIST_SETTLED_JS)


class NoPrintTests(unittest.TestCase):
    def test_isolated_edge_disables_the_diary_print_dialog(self):
        import asyncio
        from coletor.manual_worker import NO_PRINT_JS, configure_context
        class Context:
            def __init__(self): self.scripts=[]
            async def route(self,*_): pass
            async def route_web_socket(self,*_): pass
            async def add_init_script(self,script): self.scripts.append(script)
        context=Context();asyncio.run(configure_context(context))
        self.assertIn(NO_PRINT_JS,context.scripts)
        self.assertIn("'print'",NO_PRINT_JS);self.assertIn('writable: false',NO_PRINT_JS)


if __name__=='__main__':unittest.main()
