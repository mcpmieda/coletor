"""Discovery/selection/capture authorization with synthetic classes only."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from test_class_catalog import observed
from coletor.class_catalog import catalog_from_observation, list_url
from coletor.manual_session import ManualSession, SessionError, source_url
from coletor.demo import build_fixture


class Driver:
    def __init__(self):self.opened=[];self.captures=[];self.ids=['11','12'];self.revoked=False
    def open(self,url):self.opened.append(url)
    def close(self):pass
    def discover(self,year):
        data=observed(year)
        data['rows']=[r for r in data['rows'] if str(int(r['links'][0].split('=')[1])) in self.ids]
        return catalog_from_observation(data,year)
    def capture_selected(self,key,year,context):
        if self.revoked or key not in self.ids:raise ValueError('synthetic class unavailable')
        self.captures.append(key)
        html=re.sub(r' data-(?:report|class-id|year|student-count|student-row|report-end)="[^"]*"','',build_fixture(year=year,include_edge_cases=False))
        return {'url':source_url(key,year),'html':html,'password_form':False}


class ClassFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        # These scenarios cover hand-picked classes ('Escolher turmas').
        from coletor.local_settings import LocalSettings
        LocalSettings(self.temp.name).update('classes',{'mode':'chosen'})
        self.driver=Driver();self.session=ManualSession(lambda:self.driver,self.temp.name)
    def enter(self,year=2026):
        prepared=self.session.prepare_login(year)
        self.assertNotIn('class_id',prepared['scope'])
        self.session.open(prepared['generation'],True)
        return prepared['generation']
    def test_unselected_school_context_is_not_eligible_for_leadership(self):
        self.assertFalse(self.session.has_saved_class_selection())
        self.assertEqual(self.driver.opened, [])
        gen = self.enter(2025)
        listed = self.session.discover(gen, True)
        self.session.save_choices(gen, ['11'], listed['selection_revision'])
        self.assertFalse(self.session.has_saved_class_selection())  # Not the 2026 context.
        gen = self.enter(2026)
        listed = self.session.discover(gen, True)
        self.assertFalse(self.session.has_saved_class_selection())
        saved = self.session.save_choices(gen, ['12'], listed['selection_revision'])
        self.assertTrue(self.session.has_saved_class_selection())
        self.session.save_choices(gen, [], saved['selection_revision'], clear=True)
        self.assertFalse(self.session.has_saved_class_selection())

    def test_a_run_finishes_the_cleanup_the_last_one_could_not(self):
        class Storage:
            def load_credential(self): return None
            def load_session(self): return {'cookies': [], 'origins': []}
            def save_session(self, state): pass
        self.driver.export_state = lambda: {'cookies': [], 'origins': []}
        storage = Storage()
        self.session.operational_catalog(storage)
        # The run ends; Windows still holds the browser's temporary files.
        held = [True]
        def close():
            if held[0]: raise OSError('SYNTHETIC_PRIVATE_PATH_DO_NOT_ECHO')
        self.driver.close = close
        with self.assertRaises(SessionError): self.session.preserve_and_close(storage)
        self.assertTrue(self.session.status()['cleanup_pending'])
        # Still held at the next run: that run does not open a second browser, and fails as a read
        # (tried again), not as an expired login (which waits for a person when none is saved).
        with self.assertRaises(SessionError) as held_again: self.session.operational_catalog(storage)
        self.assertEqual((str(held_again.exception), held_again.exception.reason), ('SOURCE_READ_FAILED', 'browser-closing'))
        self.assertEqual(len(self.driver.opened), 1)
        # Released: the next run finishes the cleanup and reads the list as usual.
        held[0] = False
        listed = self.session.operational_catalog(storage)
        self.assertEqual(len(listed['catalog']['classes']), 2)
        self.assertEqual(len(self.driver.opened), 2)
        self.assertFalse(self.session.status()['cleanup_pending'])

    def test_login_first_does_not_open_diary_or_student_links(self):
        gen=self.enter()
        self.assertEqual(self.driver.opened,[list_url(2026)])
        self.assertEqual(self.driver.captures,[])
        listed=self.session.discover(gen,True)
        self.assertEqual([c['name'] for c in listed['catalog']['classes']],['Turma sintética 1 -VESPERTINO','Turma sintética 2 -VESPERTINO'])
        with self.assertRaises(SessionError):self.session.capture_selected(gen,'11',True)
        chosen=self.session.save_choices(gen,['11'],listed['selection_revision'])
        self.assertEqual(chosen['selected_class_ids'],['11'])
        self.assertFalse(self.session.capture_selected(gen,'11',True)['preview']['validation']['allowed'])
    def test_relogin_and_partial_list_revalidate_without_erasing_absent_choice(self):
        gen=self.enter();listed=self.session.discover(gen,True)
        self.session.save_choices(gen,['11','12'],listed['selection_revision'])
        self.session.close();self.driver.ids=['11']
        gen=self.enter();partial=self.session.discover(gen,True)
        self.assertEqual(partial['selected_class_ids'],['11'])
        self.assertEqual(partial['unavailable_class_ids'],['12'])
        self.session.save_choices(gen,[],partial['selection_revision'])
        self.session.close();self.driver.ids=['11','12']
        gen=self.enter();restored=self.session.discover(gen,True)
        self.assertEqual(restored['selected_class_ids'],['12'])
    def test_revocation_before_capture_and_old_generation_cannot_read(self):
        gen=self.enter();listed=self.session.discover(gen,True)
        self.session.save_choices(gen,['11'],listed['selection_revision'])
        self.driver.revoked=True
        with self.assertRaises(SessionError):self.session.capture_selected(gen,'11',True)
        self.assertEqual(self.driver.captures,[])
        self.session.close()
        with self.assertRaises(SessionError):self.session.discover(gen,True)
    def test_year_change_does_not_delete_previous_year_choice(self):
        gen=self.enter();listed=self.session.discover(gen,True);self.session.save_choices(gen,['11'],listed['selection_revision'])
        gen=self.enter(2025);listed=self.session.discover(gen,True)
        self.assertEqual(listed['selected_class_ids'],[])
        self.session.save_choices(gen,['12'],listed['selection_revision'])
        gen=self.enter(2026);self.assertEqual(self.session.discover(gen,True)['selected_class_ids'],['11'])




class AllClassesTests(unittest.TestCase):
    """Default 'Todas as turmas': no one has to choose, and new classes join."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.driver=Driver();self.session=ManualSession(lambda:self.driver,self.temp.name)
    def test_every_listed_class_is_selected_and_new_ones_join(self):
        self.assertTrue(self.session.has_saved_class_selection())
        self.assertIsNone(self.session.saved_class_count())
        self.driver.ids=['11']
        prepared=self.session.prepare_login(2026);self.session.open(prepared['generation'],True)
        listed=self.session.discover(prepared['generation'],True)
        self.assertEqual(listed['selected_class_ids'],['11'])
        self.driver.ids=['11','12']  # A class created later in Smecel.
        listed=self.session.discover(prepared['generation'],True)
        self.assertEqual(listed['selected_class_ids'],['11','12'])
        self.assertEqual(self.session.capture_selected(prepared['generation'],'12',True)['session']['state'],'preview_ready')
        self.assertEqual(self.driver.captures,['12'])

if __name__=='__main__':unittest.main()
