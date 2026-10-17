import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import { RunFigures } from './CollectorControl';
import { COLLECTOR_CODES, isConfigured, lastRun, type CollectorStatus, type HistoryEntry } from '../collector';

const base: CollectorStatus = { state: 'reserve', code: null, active: true, localPaused: false, persistent: true,
  progress: { completed: 0, total: 0, classLabel: null }, lastReceipt: null, settings: null };

test('setup folds away only with a saved access and at least one class', () => {
  expect(isConfigured(null)).toBe(false);
  expect(isConfigured({ ...base, credential: { saved: true }, selectedClasses: 15 })).toBe(true);
  expect(isConfigured({ ...base, credential: { saved: true }, selectedClasses: 0 })).toBe(false);
  expect(isConfigured({ ...base, credential: { saved: false }, selectedClasses: 15 })).toBe(false);
  expect(isConfigured({ ...base, credential: { saved: true } })).toBe(false);
});
const history: HistoryEntry[] = [
  { at: 100, kind: 'collection-started', sent: 15 }, { at: 120, kind: 'class-sent', label: '6A', sent: 32, unresolved: 0, conflicts: 0 },
  { at: 130, kind: 'failure', code: 'SOURCE_READ_FAILED' },
  { at: 200, kind: 'collection-started', sent: 15 },
  ...Array.from({ length: 15 }, (_, i) => ({ at: 210 + i, kind: 'class-sent', label: `T${i}`, sent: 25, unresolved: i < 2 ? 2 : 0, conflicts: 0 })),
  { at: 300, kind: 'collection-finished', sent: 15 },
];
test('the latest collection is summarised from the local history in any order', () => {
  expect(lastRun([])).toBeNull();
  const run = lastRun([...history].reverse());
  expect(run).toEqual({ at: 300, classes: 15, total: 15, resolved: 375, unresolved: 4, conflicts: 0, finished: true });
  expect(lastRun(history.slice(0, 3))).toMatchObject({ classes: 1, total: 15, finished: false });
});
test('figures highlight a partial run and what needs attention', () => {
  const html = renderToStaticMarkup(<RunFigures run={{ at: 300, classes: 1, total: 15, resolved: 32, unresolved: 5, conflicts: 0, finished: false }} />);
  expect(html).toContain('class="attention">1 de 15<');
  expect(html).toContain('class="attention">5<');
  expect(html).not.toContain('class="attention">0<');
});
test('a failed diary read is not reported as a missing Smecel login', () => {
  expect(COLLECTOR_CODES.SOURCE_READ_FAILED).toContain('ler o diário');
  expect(COLLECTOR_CODES.SOURCE_READ_FAILED).not.toContain('Entre no Smecel');
});
