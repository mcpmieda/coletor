"""Synthetic choices; no authenticated browser, students or credentials."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from coletor.class_selection import ClassSelectionStore, SelectionConflict, revalidate_choices
from coletor.local_settings import LocalSettings

SCOPE = {'origin': 'https://www.smecel.com.br', 'list_path': '/sistema/escola/turmaListar.php',
         'year': 2026, 'context_key': 'synthetic-school:1'}


class ClassSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ClassSelectionStore(self.root)

    def test_saved_choices_survive_reopen_but_always_require_new_listing(self):
        selection = self.store.save(SCOPE, ['22', '11'], 0)
        reopened = ClassSelectionStore(self.root).read()
        self.assertEqual(reopened['selection']['selected_class_ids'], ['11', '22'])
        self.assertTrue(reopened['revalidation_required'])
        current = revalidate_choices(selection, SCOPE, ['11', '33'])
        self.assertEqual(current['selected_class_ids'], ['11'])
        self.assertEqual(current['unavailable_class_ids'], ['22'])

    def test_changed_year_or_context_never_silently_restores_choices(self):
        selection = self.store.save(SCOPE, ['11'], 0)
        for scope in ({**SCOPE, 'year': 2027}, {**SCOPE, 'context_key': 'synthetic-school:2'}):
            current = revalidate_choices(selection, scope, ['11'])
            self.assertEqual(current['selected_class_ids'], [])
            self.assertFalse(current['context_matches'])

    def test_conflicting_window_cannot_overwrite_newer_choice(self):
        other = ClassSelectionStore(self.root)
        self.store.save(SCOPE, ['11'], 0)
        with self.assertRaises(SelectionConflict):
            other.save(SCOPE, ['22'], 0)
        self.assertEqual(other.read()['selection']['selected_class_ids'], ['11'])

    def test_fields_cannot_include_credentials_students_urls_or_arbitrary_state(self):
        for scope in ({**SCOPE, 'password': 'SYNTHETIC_ONLY'}, {**SCOPE, 'cookies': []},
                      {**SCOPE, 'origin': 'https://unapproved.invalid'},
                      {**SCOPE, 'context_key': 'https://secret.invalid/?token=fixture'}):
            with self.assertRaises(ValueError):
                self.store.save(scope, ['11'], 0)
        for ids in (['11', '11'], ['001'], ['studentUid:11'], [True], ['11?token=fixture']):
            with self.assertRaises(ValueError):
                self.store.save(SCOPE, ids, 0)
        self.assertFalse((self.root/'class-selection.json').exists())

    def test_atomic_failure_preserves_previous_selection_and_cleans_staging(self):
        self.store.save(SCOPE, ['11'], 0)
        before = (self.root/'class-selection.json').read_bytes()
        with patch('coletor.class_selection.os.replace', side_effect=OSError('SYNTHETIC_ONLY')):
            with self.assertRaises(OSError):
                self.store.save(SCOPE, ['22'], 1)
        self.assertEqual((self.root/'class-selection.json').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['class-selection.json', 'settings.lock'])

    def test_previous_program_preferences_are_not_migrated_or_changed(self):
        prefs = LocalSettings(self.root)
        prefs.update('theme', 'dark')
        before = (self.root/'settings.json').read_bytes()
        self.store.save(SCOPE, ['11'], 0)
        self.assertEqual((self.root/'settings.json').read_bytes(), before)
        self.assertEqual(prefs.read()['settings']['theme'], 'dark')

    def test_other_years_and_contexts_are_preserved_in_separate_profiles(self):
        self.store.save(SCOPE, ['11'], 0)
        other={**SCOPE,'year':2025}
        self.store.save(other,['22'],1)
        self.assertEqual(self.store.read(SCOPE)['selection']['selected_class_ids'],['11'])
        self.assertEqual(self.store.read(other)['selection']['selected_class_ids'],['22'])
        self.store.save(SCOPE,[],2)
        self.assertEqual(self.store.read(other)['selection']['selected_class_ids'],['22'])

    def test_corruption_recovers_without_backing_up_or_echoing_private_content(self):
        (self.root/'class-selection.json').write_text('SYNTHETIC_PRIVATE_DO_NOT_ECHO', encoding='utf-8')
        result = self.store.read()
        self.assertIsNone(result['selection'])
        self.assertNotIn('SYNTHETIC_PRIVATE', result['notice'])
        self.store.save(SCOPE, ['11'], 0)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['class-selection.json', 'settings.lock'])


if __name__ == '__main__':
    unittest.main()
