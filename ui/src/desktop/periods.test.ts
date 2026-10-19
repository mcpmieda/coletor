import { expect, test } from 'vitest';
import { DEFAULT_DRAFT, MAX_PER_DAY, dayTimes, draftProblem, fromShared, nextRun, nextSharedRun, parseTimesText, scheduleText, toShared, type PeriodDraft } from './periods';

const draft = (patch: Partial<PeriodDraft> = {}): PeriodDraft => ({ ...DEFAULT_DRAFT, ...patch });

test('an interval period becomes the same times on every chosen day and both shifts', () => {
  const shared = toShared(draft({ every: 60, from: '07:00', to: '10:00', weekdays: [0, 4], finalCheck: '18:00' }));
  expect(shared.rules).toHaveLength(14);
  const monday = shared.rules.filter(r => r.weekday === 1);
  expect(monday.map(r => r.shift)).toEqual(['matutino', 'vespertino']);
  expect(monday.every(r => r.enabled && r.times.join() === '07:00,08:00,09:00,10:00' && r.recheck === '18:00')).toBe(true);
  expect(shared.rules.filter(r => r.weekday === 5).every(r => r.enabled)).toBe(true); // Friday
  expect(shared.rules.filter(r => r.weekday === 0 || r.weekday === 2).every(r => !r.enabled && r.times.length === 0 && r.recheck === null)).toBe(true);
});

test('round trip: interval, fixed times and off', () => {
  for (const d of [draft({ every: 45, from: '07:15', to: '16:15' }), draft({ mode: 'times', times: ['08:00', '13:30'] }), draft({ mode: 'off' })]) {
    const back = fromShared(toShared(d));
    expect(back.mode).toBe(d.mode);
    expect(dayTimes(back)).toEqual(dayTimes(d));
    if (d.mode !== 'off') expect(back.weekdays).toEqual(d.weekdays);
  }
});

test('a schedule made per shift in the Ecossistema is shown as custom', () => {
  const shared = toShared(draft({ every: 60, from: '07:00', to: '09:00' }));
  shared.rules[2] = { ...shared.rules[2], times: ['13:00'] };
  expect(fromShared(shared).custom).toBe(true);
  expect(fromShared(null)).toEqual(DEFAULT_DRAFT);
});

test('problems are explained before saving', () => {
  expect(draftProblem(draft())).toBeNull();
  expect(draftProblem(draft({ weekdays: [] }))).toMatch(/dia/);
  expect(draftProblem(draft({ from: '18:00', to: '07:00' }))).toMatch(/depois do início/);
  expect(draftProblem(draft({ every: 5, from: '00:00', to: '23:55' }))).toMatch(new RegExp(`limite é ${MAX_PER_DAY}`));
  expect(draftProblem(draft({ finalCheck: '12:00' }))).toMatch(/conferência final/);
  expect(draftProblem(draft({ mode: 'times', times: [] }))).toMatch(/horário/);
});

test('plain sentence for the task card', () => {
  expect(scheduleText(draft())).toBe('A cada 30 min, das 07:00 às 17:30 · seg a sex');
  expect(scheduleText(draft({ mode: 'times', times: ['13:00', '08:00'], weekdays: [0, 2] }))).toBe('Às 08:00, 13:00 · seg, qua');
  expect(scheduleText(draft({ mode: 'off' }))).toBe('Sem coletas automáticas');
});

test('next collection in the school time zone', () => {
  // Monday 2026-10-19 10:10 in Bahia (UTC-3) = 13:10Z.
  const next = nextRun(draft({ every: 30, from: '07:00', to: '17:30' }), new Date('2026-10-19T13:10:00Z'));
  expect(next?.toISOString()).toBe('2026-10-19T13:30:00.000Z');
  // Friday after the last time goes to Monday 07:00.
  expect(nextRun(draft(), new Date('2026-10-23T21:00:00Z'))?.toISOString()).toBe('2026-10-26T10:00:00.000Z');
  expect(nextRun(draft({ mode: 'off' }))).toBeNull();
});

test('a day with only one shift enabled is not silently widened', () => {
  const rules = Array.from({ length: 14 }, (_, i) => ({
    weekday: Math.floor(i / 2), shift: (i % 2 ? 'vespertino' : 'matutino') as 'matutino' | 'vespertino',
    enabled: Math.floor(i / 2) === 1 && i % 2 === 0, times: Math.floor(i / 2) === 1 && i % 2 === 0 ? ['07:00'] : [], recheck: null,
  }));
  expect(fromShared({ timezone: 'America/Bahia', rules }).custom).toBe(true);
});

test('typed fixed times report invalid and repeated entries instead of dropping them', () => {
  expect(parseTimesText('08:00, 09:xx, 12:00, 8:00, 7:30')).toEqual({ times: ['07:30', '08:00', '12:00'], invalid: ['09:xx'], repeated: ['8:00'] });
});

test('an agenda read as intervals keeps its own times for the fixed-times mode', () => {
  const interval: PeriodDraft = { ...DEFAULT_DRAFT, every: 30, from: '07:00', to: '08:00' };
  const read = fromShared(toShared(interval));
  expect(read.mode).toBe('interval');
  expect(read.times).toEqual(dayTimes(interval));
  expect(dayTimes({ ...read, mode: 'times' })).toEqual(['07:00', '07:30', '08:00']);
});

test('the next run follows the saved agenda per day, not its summary', () => {
  // Monday to Friday 07:00 and 07:30; Saturday 08:00 only (made in the Ecossistema).
  const rules = Array.from({ length: 14 }, (_, i) => {
    const weekday = Math.floor(i / 2);
    const times = weekday >= 1 && weekday <= 5 ? ['07:00', '07:30'] : weekday === 6 && i % 2 === 0 ? ['08:00'] : [];
    return { weekday, shift: (i % 2 ? 'vespertino' : 'matutino') as 'matutino' | 'vespertino', enabled: times.length > 0, times, recheck: null };
  });
  const schedule = { timezone: 'America/Bahia', rules };
  // Saturday 2026-10-17 07:45 in Bahia (UTC-3) -> 08:00 the same day.
  const saturday = new Date('2026-10-17T10:45:00Z');
  expect(nextSharedRun(schedule, saturday)?.toISOString()).toBe('2026-10-17T11:00:00.000Z');
  // Saturday 09:00 -> Monday 07:00 (Sunday has nothing).
  expect(nextSharedRun(schedule, new Date('2026-10-17T12:00:00Z'))?.toISOString()).toBe('2026-10-19T10:00:00.000Z');
});

test('fixed times closer than 5 minutes are refused before reaching the Ecossistema', () => {
  expect(draftProblem({ ...DEFAULT_DRAFT, mode: 'times', times: ['08:00', '08:03'] })).toMatch(/5 minutos/);
  expect(draftProblem({ ...DEFAULT_DRAFT, mode: 'times', times: ['08:00', '08:05'] })).toBeNull();
  expect(draftProblem({ ...DEFAULT_DRAFT, mode: 'times', times: ['08:00'], finalCheck: '08:02' })).toMatch(/5 minutos/);
});
