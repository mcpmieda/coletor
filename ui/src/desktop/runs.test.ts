import { expect, test } from 'vitest';
import { failures24h, fmtCountdown, fmtDuration, groupRuns, logEvents, runSummary } from './runs';
import type { HistoryEntry } from '../collector';

const history: HistoryEntry[] = [
  { at: 100, kind: 'collection-started', sent: 3 },
  { at: 110, kind: 'class-sent', label: '6A', sent: 30, unresolved: 0, conflicts: 0 },
  { at: 120, kind: 'failure', code: 'lease-fenced' },
  { at: 200, kind: 'collection-started', sent: 2 },
  { at: 210, kind: 'class-sent', label: '6A', sent: 30, unresolved: 1, conflicts: 0 },
  { at: 220, kind: 'class-sent', label: '6B', sent: 25, unresolved: 0, conflicts: 2 },
  { at: 230, kind: 'collection-finished', sent: 2 },
  { at: 300, kind: 'collection-started', sent: 15 },
  { at: 305, kind: 'class-sent', label: '6A', sent: 30, unresolved: 0, conflicts: 0 },
];

test('history becomes runs, newest first, with partial and running states', () => {
  const runs = groupRuns([...history].reverse());
  expect(runs.map(r => r.status)).toEqual(['running', 'review', 'partial']);
  expect(runs[1]).toMatchObject({ resolved: 55, unresolved: 1, conflicts: 2, finished: 230 });
  expect(runSummary(runs[1])).toBe('2 de 2 turma(s) · 55 aluno(s) · 1 não reconhecido(s) · 2 conflito(s)');
  expect(runSummary(runs[2])).toContain('1 de 3 turma(s)');
  expect(runSummary(runs[0])).toBe('Coletando · 1 de 15 turma(s)');
});

test('log lines are plain and leveled', () => {
  const events = logEvents(history);
  expect(events[0].message).toBe('6A enviada · 30 aluno(s)');
  const fenced = events.find(e => e.detail?.includes('Outro computador assumiu'));
  expect(fenced?.level).toBe('error');
  expect(fenced?.detail).not.toContain('lease-fenced');
  expect(events.find(e => e.message.startsWith('6B'))?.level).toBe('warn');
});

test('durations and countdowns', () => {
  expect(fmtDuration(0, 314)).toBe('5 min 14 s');
  expect(fmtDuration(0, null)).toBe('—');
  expect(fmtCountdown(new Date(90_000), 0)).toBe('1:30');
  expect(fmtCountdown(new Date(3_900_000), 0)).toBe('1 h 05 min');
  expect(fmtCountdown(null)).toBe('—');
});

test('a paused run is closed as stopped and is not a failure', () => {
  const entries: HistoryEntry[] = [
    { at: 100, kind: 'collection-started', sent: 3 },
    { at: 110, kind: 'class-sent', label: '6A', sent: 30, unresolved: 0, conflicts: 0 },
    { at: 120, kind: 'collection-stopped', code: 'paused' },
    { at: 130, kind: 'late-cancelled', label: '07:15' },
  ];
  expect(groupRuns(entries)[0].status).toBe('stopped');
  expect(failures24h(entries, 200_000)).toBe(0);
  expect(logEvents(entries).find(e => e.message.includes('cancelado'))).toBeTruthy();
});

test('one 24 h failure count for the badge and the tile, including failures outside a run', () => {
  const entries: HistoryEntry[] = [
    { at: 1000, kind: 'failure', code: 'SOURCE_LOGIN_FAILED' },
    { at: 1100, kind: 'failure', code: 'ACCESS_UNAVAILABLE' },
    { at: 1200, kind: 'failure', code: 'lease-busy' },
  ];
  expect(failures24h(entries, 2_000_000)).toBe(1);
});

test('an unknown Smecel mark is one warning that names it and is not a failure', () => {
  const entries: HistoryEntry[] = [{ at: 200, kind: 'unknown-mark', code: 'X [ls-color-info]', label: '6A 2026 - MATUTINO' }];
  const [event] = logEvents(entries);
  expect(event).toMatchObject({ level: 'warn', message: 'Marcação desconhecida no Smecel: X [ls-color-info]' });
  expect(event!.detail).toContain('Vista primeiro em 6A 2026 - MATUTINO');
  expect(failures24h(entries, 201_000)).toBe(0);
});

test('a diary that went as the short message reads "sem alteração" (owner request 28/10/2026)', () => {
  const entries: HistoryEntry[] = [
    { at: 100, kind: 'class-sent', label: '7C', sent: 22, unresolved: 0, conflicts: 0 },
    { at: 200, kind: 'class-sent', label: '7C', sent: 22, unresolved: 0, conflicts: 0, unchanged: true },
  ];
  expect(logEvents(entries).map(e => e.message)).toEqual(['7C sem alteração · 22 aluno(s)', '7C enviada · 22 aluno(s)']);
});

test('an unread diary is one failure of its class, and the run goes on as partial', () => {
  const entries: HistoryEntry[] = [
    { at: 100, kind: 'collection-started', sent: 3 },
    { at: 110, kind: 'class-sent', label: '7C', sent: 22, unresolved: 0, conflicts: 0 },
    { at: 120, kind: 'class-failed', code: 'SOURCE_READ_FAILED', label: '7D' },
    { at: 130, kind: 'class-sent', label: '8A', sent: 32, unresolved: 0, conflicts: 0 },
    { at: 140, kind: 'collection-finished', sent: 3, code: 'SOURCE_READ_FAILED' },
  ];
  const [run] = groupRuns(entries);
  expect(run).toMatchObject({ status: 'partial', resolved: 54, finished: 140 });
  expect(runSummary(run!)).toContain('2 de 3 turma(s)');
  const failed = logEvents(entries).find(e => e.message.startsWith('7D'));
  expect(failed).toMatchObject({ level: 'error', detail: 'O Smecel demorou ou falhou ao abrir um diário.' });
  expect(failed!.message).toContain('As outras turmas seguiram');
  expect(failures24h(entries, 200_000)).toBe(1);
});

test('the weekly grid line says whether anything changed', () => {
  const entries: HistoryEntry[] = [
    { at: 100, kind: 'schedule-sent', sent: 0 },
    { at: 200, kind: 'schedule-sent', sent: 2 },
  ];
  expect(logEvents(entries).map(e => e.message)).toEqual(['Grade de horários enviada · 2 turma(s) com mudança', 'Grade de horários conferida · sem alteração']);
});
