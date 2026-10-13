import { expect, test, vi } from 'vitest';
import { SCHEDULE_KEY, defaultSchedule, fromDraft, parseTimes, readSchedule, saveSchedule, toDraft, validateSchedule } from './schedule';

test('defaults are school-scoped, local only and use confirmed Bahia timezone', () => {
  const c = validateSchedule(defaultSchedule());
  expect(c.scope).toBe('school'); expect(c.storageMode).toBe('local-preview');
  expect(c.timezone).toBe('America/Bahia'); expect(c.sharedRevision).toBeNull();
  expect(c.rules).toHaveLength(14);
  expect(c.rules.filter(r => r.selected)).toHaveLength(10);
  expect(c.rules.filter(r => r.weekday >= 6).every(r => !r.selected && !r.times.length)).toBe(true);
  expect(c.rules.reduce((n, r) => n + r.times.length, 0)).toBe(54);
});
test.each([
  ['matutino',1,'08:05,09:00,09:55,11:05,11:55','12:15'],
  ['matutino',2,'07:55,08:40,09:25,10:10,11:10,11:55','12:15'],
  ['matutino',3,'08:05,09:00,09:55,11:05,11:55','12:15'],
  ['matutino',4,'07:55,08:40,09:25,10:10,11:10,11:55','12:15'],
  ['matutino',5,'08:40,09:25,10:10,11:10,11:55','12:15'],
  ['vespertino',1,'14:20,15:15,16:25,17:20,18:10','18:30'],
  ['vespertino',2,'14:10,14:55,15:40,16:40,17:25,18:10','18:30'],
  ['vespertino',3,'14:20,15:15,16:25,17:20,18:10','18:30'],
  ['vespertino',4,'14:10,14:55,15:40,16:40,17:25,18:10','18:30'],
  ['vespertino',5,'14:10,14:55,15:40,16:40,17:25','18:30'],
])('v75 preset %s day %s matches reviewed source', (shift, weekday, times, reconciliation) => {
  const rule = defaultSchedule().rules.find(r => r.shift === shift && r.weekday === weekday);
  expect(rule?.times.join(',')).toBe(times); expect(rule?.reconciliation).toBe(reconciliation);
});
test('defaults are copied and editing one preview never mutates the next', () => {
  const c = defaultSchedule(); c.rules[0].times[0] = '00:00';
  expect(defaultSchedule().rules[0].times[0]).toBe('08:05');
});
test('schedule edits validate times, weekdays, timezone and reconciliation', () => {
  const d = toDraft(defaultSchedule()); d.rules[0].timesText = '09:00, 08:15';
  expect(fromDraft(d, 2).rules[0].times).toEqual(['08:15','09:00']);
  d.timezone = 'Somewhere/Invalid'; expect(() => fromDraft(d, 2)).toThrow('Fuso');
  d.timezone = 'America/Bahia'; d.rules[0].timesText = '23:99'; expect(() => fromDraft(d, 2)).toThrow('horários');
  d.rules[0].timesText = '12:30'; expect(() => fromDraft(d, 2)).toThrow('depois');
  d.rules[0].timesText = '12:15'; expect(() => fromDraft(d, 2)).toThrow('repetir');
});
test.each(['24:00','8:00','08:60','09:00,09:00','09:00,', 'x'.repeat(151)])('invalid time list %s is rejected', value => {
  expect(() => parseTimes(value)).toThrow();
});
test('weekends may be included only with explicit times and without calendar claims', () => {
  const d = toDraft(defaultSchedule()); d.rules[5].selected = true;
  expect(() => fromDraft(d,0)).toThrow('inclua ao menos');
  d.rules[5].timesText = '10:10';
  expect(fromDraft(d,0).rules[5].times).toEqual(['10:10']);
});
test('schema, volume, missing rules and duplicated days fail closed', () => {
  expect(() => validateSchedule({ ...defaultSchedule(), schemaVersion:2 })).toThrow();
  expect(() => validateSchedule({ ...defaultSchedule(), rules:[] })).toThrow();
  expect(() => validateSchedule({ ...defaultSchedule(), localRevision:Number.MAX_SAFE_INTEGER+1 })).toThrow();
  const c = defaultSchedule(); c.rules[1] = c.rules[0]; expect(() => validateSchedule(c)).toThrow('duplicados');
});
test('local storage contains only whitelisted config and increments local revision', () => {
  const storage = { setItem:vi.fn() };
  const c = { ...defaultSchedule(), credential:'never retain', schoolId:'unverified' };
  const saved = saveSchedule(storage,c);
  expect(saved.localRevision).toBe(1);
  expect(storage.setItem).toHaveBeenCalledWith(SCHEDULE_KEY, JSON.stringify(saved));
  expect(JSON.stringify(saved)).not.toContain('credential');
  expect(JSON.stringify(saved)).not.toContain('schoolId');
  expect(readSchedule({ getItem:() => JSON.stringify(saved) }).config).toEqual(saved);
});
test.each(['{broken', '{}',' '.repeat(16001)])('corrupted local draft falls back visibly: %s', raw => {
  const result = readSchedule({ getItem: () => raw });
  expect(result.notice).toContain('Não foi possível'); expect(result.config.localRevision).toBe(0);
});
test('blocked local storage is reported instead of claiming persistence', () => {
  expect(readSchedule({ getItem: () => { throw Error('blocked'); } }).notice).not.toBe('');
  expect(() => saveSchedule({ setItem: () => { throw Error('quota'); } },defaultSchedule())).toThrow('quota');
});

test('malformed JSON cannot coerce a shift array into a valid key', () => {
  const raw = JSON.parse(JSON.stringify(defaultSchedule())); raw.rules[0].shift = ['matutino'];
  expect(() => validateSchedule(raw)).toThrow('Dia ou turno');
  expect(readSchedule({ getItem: () => JSON.stringify(raw) }).notice).not.toBe('');
});
