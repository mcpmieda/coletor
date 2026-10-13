"""Two real processes using the same synthetic preference file."""
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from coletor.local_settings import LocalSettings, ScheduleConflict
from test_local_settings import schedule


def save_competing(directory, gate, output, time):
    candidate = schedule()
    candidate['rules'][0]['times'][0] = time
    gate.wait(10)
    try:
        LocalSettings(directory).update('schedule', candidate)
        output.put('saved')
    except ScheduleConflict:
        output.put('conflict')


class SettingsConcurrencyTests(unittest.TestCase):
    def test_two_processes_cannot_overwrite_the_same_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = multiprocessing.get_context('spawn')
            gate, output = ctx.Event(), ctx.Queue()
            processes = [ctx.Process(target=save_competing, args=(directory,gate,output,time)) for time in ('08:15','08:25')]
            try:
                for process in processes: process.start()
                gate.set()
                results = sorted(output.get(timeout=20) for _ in processes)
                self.assertEqual(results, ['conflict','saved'])
                for process in processes:
                    process.join(20)
                    self.assertEqual(process.exitcode,0)
                saved = LocalSettings(directory).read()['settings']['schedule']
                self.assertEqual(saved['localRevision'],1)
                self.assertIn(saved['rules'][0]['times'][0],('08:15','08:25'))
                next_value = schedule(); next_value['localRevision'] = 2
                LocalSettings(directory).update('schedule',next_value)
                self.assertEqual(LocalSettings(directory).read()['settings']['schedule']['localRevision'],2)
            finally:
                for process in processes:
                    if process.is_alive(): process.terminate(); process.join(5)
                output.close()
