import { expect, test } from 'vitest';
import type { HistoryEntry } from '../collector';
import { groupRuns } from './runs';
import { inProgressOf } from './useColetor';
import useColetor from './useColetor.ts?raw';

test('a run going on when the window opens is read as going on, by the summary as by a poll', () => {
  expect(inProgressOf({ state: 'collecting' })).toEqual({ run: true, report: false });
  expect(inProgressOf({ state: 'ready', preparing: true })).toEqual({ run: true, report: false });
  expect(inProgressOf({ state: 'ready', report: { running: true, preparing: true, code: null } })).toEqual({ run: false, report: true });
  expect(inProgressOf({ state: 'ready' })).toEqual({ run: false, report: false });
  expect(inProgressOf(null)).toEqual({ run: false, report: false });
  // What it changes on screen: the same unfinished history is "Coletando", not "Interrompida".
  const entries: HistoryEntry[] = [{ at: 100, kind: 'collection-started', sent: 3 }, { at: 110, kind: 'class-sent', label: '6A', sent: 30 }];
  expect(groupRuns(entries, inProgressOf({ state: 'collecting' }).run)[0].status).toBe('running');
  expect(groupRuns(entries, inProgressOf({ state: 'ready' }).run)[0].problem).toBe('Interrompida antes de terminar.');
  // The summary seeds it only until a poll has brought a history of its own.
  expect(useColetor).toContain('if (newest.current === null) setInProgress(inProgressOf(snapshot.status));');
});
