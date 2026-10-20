import { expect, test } from 'vitest';
import agendaFixture from '../../../fixtures/agenda-heterogeneous.json';
import type { SharedSchedule } from '../collector';
import { DEFAULT_DRAFT, MAX_PER_DAY, dayTimes, draftProblem, fromShared, nextRun, nextSharedRun, nextTimeField, sharedScheduleProblem, timezoneProblem, scheduleText, toShared, type PeriodDraft } from './periods';

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

test('next run is right across daylight saving changes', () => {
  const sunday8 = (from: string, zone: string) => nextFrom8(zone, new Date(from));
  function nextFrom8(timezone: string, now: Date) {
    const rules = Array.from({ length: 14 }, (_, i) => ({
      weekday: Math.floor(i / 2), shift: (i % 2 ? 'vespertino' : 'matutino') as 'matutino' | 'vespertino',
      enabled: Math.floor(i / 2) === 0 && i % 2 === 0, times: Math.floor(i / 2) === 0 && i % 2 === 0 ? ['08:00'] : [], recheck: null,
    }));
    return nextSharedRun({ timezone, rules }, now)?.toISOString();
  }
  // New York springs forward on 2026-03-08: Saturday 20:00 EST -> Sunday 08:00 EDT.
  expect(sunday8('2026-03-08T01:00:00Z', 'America/New_York')).toBe('2026-03-08T12:00:00.000Z');
  // Falls back on 2026-11-01: Saturday 20:00 EDT -> Sunday 08:00 EST.
  expect(sunday8('2026-11-01T00:00:00Z', 'America/New_York')).toBe('2026-11-01T13:00:00.000Z');
  // Bahia has no DST: control.
  expect(sunday8('2026-10-17T23:00:00Z', 'America/Bahia')).toBe('2026-10-18T11:00:00.000Z');
});

test('an agenda with only the final check is kept by the editor', () => {
  const rules = Array.from({ length: 14 }, (_, i) => {
    const on = Math.floor(i / 2) >= 1 && Math.floor(i / 2) <= 5;
    return { weekday: Math.floor(i / 2), shift: (i % 2 ? 'vespertino' : 'matutino') as 'matutino' | 'vespertino', enabled: on, times: [], recheck: on ? '18:30' : null };
  });
  const draft = fromShared({ timezone: 'America/Bahia', rules });
  expect(draftProblem(draft)).toBeNull();
  const back = toShared(draft);
  expect(back.rules.filter(r => r.enabled).every(r => r.times.length === 0 && r.recheck === '18:30')).toBe(true);
  expect(back.rules.filter(r => r.enabled)).toHaveLength(10);
});

test('different morning and afternoon times round-trip without widening either shift', () => {
  const morning = ['07:55', '08:40', '09:25'], afternoon = ['14:10', '14:55', '15:40'];
  const rules = Array.from({ length: 14 }, (_, i) => {
    const on = Math.floor(i / 2) >= 1 && Math.floor(i / 2) <= 5;
    const shift = (i % 2 ? 'vespertino' : 'matutino') as 'matutino' | 'vespertino';
    return { weekday: Math.floor(i / 2), shift, enabled: on, times: on ? (i % 2 ? afternoon : morning) : [], recheck: on ? (i % 2 ? '18:30' : '12:15') : null };
  });
  const draft = fromShared({ timezone: 'America/Bahia', rules });
  expect(draft.custom).toBe(true);
  expect(toShared(draft)).toEqual({ timezone: 'America/Bahia', rules });
  expect(scheduleText(draft)).toMatch(/dia e turno/);
  expect(sharedScheduleProblem(toShared(draft))).toBeNull();
});


test('heterogeneous days with close times remain valid without a cross-day union', () => {
  const schedule = toShared(draft({ mode: 'off' }));
  schedule.rules[2] = { ...schedule.rules[2], enabled: true, times: ['07:00'], recheck: '12:00' };
  schedule.rules[5] = { ...schedule.rules[5], enabled: true, times: ['07:03'], recheck: '18:00' };
  const loaded = fromShared(schedule);
  expect(loaded.custom).toBe(true);
  expect(sharedScheduleProblem(toShared(loaded))).toBeNull();
  expect(toShared(loaded)).toEqual(schedule);
  expect(nextSharedRun(toShared(loaded), new Date('2026-10-19T09:59:00Z'))).toEqual(nextSharedRun(schedule, new Date('2026-10-19T09:59:00Z')));
});

test('two valid days with thirty disjoint times each never become sixty per day', () => {
  const schedule = toShared(draft({ mode: 'off' }));
  const slots = (offset: number) => Array.from({ length: 30 }, (_, i) => {
    const m = offset + i * 10; return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  });
  schedule.rules[2] = { ...schedule.rules[2], enabled: true, times: slots(420) };
  schedule.rules[4] = { ...schedule.rules[4], enabled: true, times: slots(421) };
  expect(sharedScheduleProblem(schedule)).toBeNull();
  expect(toShared(fromShared(schedule))).toEqual(schedule);
});

test('disabled rules and both rechecks remain intact when nothing changed', () => {
  const schedule = toShared(draft({ mode: 'off' }));
  schedule.rules[2] = { ...schedule.rules[2], times: ['10:00'], recheck: '12:00' };
  expect(toShared(fromShared(schedule))).toEqual(schedule);
  schedule.rules[2].enabled = true;
  schedule.rules[3] = { ...schedule.rules[3], enabled: true, times: ['14:00'], recheck: '18:00' };
  expect(toShared(fromShared(schedule))).toEqual(schedule);
  expect(() => toShared({ ...fromShared(schedule), times: ['09:00'] })).toThrow(/dia e turno/);
});

test('inactive rules retaining times cannot be erased by editing a uniform agenda', () => {
  const schedule = toShared(draft({ mode: 'times', times: ['08:00', '09:00'] }));
  const sunday = schedule.rules.find(r => r.weekday === 0 && r.shift === 'matutino')!;
  sunday.times = ['10:00'];
  sunday.recheck = '12:00';
  expect(sunday.enabled).toBe(false);
  const loaded = fromShared(schedule);
  expect(loaded.custom).toBe(true);
  expect(toShared(loaded)).toEqual(schedule);
  expect(() => toShared({ ...loaded, times: ['08:15', '09:15'] })).toThrow(/dia e turno/);
});

test('manual-only schedule retains every inactive stored time when reactivated', () => {
  const schedule = toShared(draft({ mode: 'off' }));
  const saturday = schedule.rules.find(r => r.weekday === 6 && r.shift === 'matutino')!;
  saturday.times = ['07:45', '08:30'];
  saturday.recheck = '09:00';
  const loaded = fromShared(schedule);
  expect(loaded.mode).toBe('off');
  expect(loaded.custom).toBe(true);
  expect(toShared(loaded)).toEqual(schedule);
  expect(() => toShared({ ...loaded, mode: 'times', times: ['07:00'] })).toThrow(/dia e turno/);
});

test('fixed-time lines must be filled or explicitly removed, and must be distinct', () => {
  expect(draftProblem(draft({ mode: 'times', times: ['07:00', '', '08:00'] }))).toMatch(/Horário 2/);
  expect(draftProblem(draft({ mode: 'times', times: ['07:00', '07:00'] }))).toMatch(/repetido/);
  expect(draftProblem(draft({ mode: 'times', times: ['07:00', '07:03'] }))).toMatch(/5 minutos/);
  expect(draftProblem(draft({ mode: 'times', times: ['07:00', '08:00'] }))).toBeNull();
});

test('new fields never create repeated midnight slots or silently truncate thirty minutes', () => {
  for (const [latest, value] of [['23:20', '23:50'], ['23:29', '23:59'], ['23:30', ''], ['23:54', '']])
    expect(nextTimeField([latest])).toEqual({ allowed: true, value });
  expect(nextTimeField(['23:55']).allowed).toBe(false);
  expect(nextTimeField(['23:59']).allowed).toBe(false);
  expect(nextTimeField(['']).allowed).toBe(false);
  expect(nextTimeField(Array(48).fill('07:00')).allowed).toBe(false);
});

test('timezone correction preserves every rule and requires an exact canonical zone', () => {
  const schedule = toShared(draft({ mode: 'times', times: ['08:00'] }));
  schedule.rules[3].enabled = false;
  expect(toShared({ ...fromShared(schedule), timezone: 'America/Manaus' })).toEqual({ ...schedule, timezone: 'America/Manaus' });
  expect(timezoneProblem('America/Manaus')).toBeNull();
  expect(timezoneProblem('America/Invalid')).toMatch(/reconhecido/);
  expect(timezoneProblem('america/bahia')).toMatch(/IANA/);
});


test('the shared runtime fixture keeps every weekday, shift and recheck on round-trip', () => {
  const schedule = agendaFixture as SharedSchedule;
  expect(toShared(fromShared(schedule))).toEqual(schedule);
  expect(sharedScheduleProblem(schedule)).toBeNull();
});
