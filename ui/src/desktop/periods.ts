import type { SharedSchedule } from '../collector';

/** Server limit of collections per day (each shift rule holds the same times). */
export const MAX_PER_DAY = 48;
/** Ecossistema rule (frequencyScheduleWriteV2): moments of a day 5+ minutes apart. */
export const MIN_GAP_MINUTES = 5;
export const DAY_LETTERS = ['S', 'T', 'Q', 'Q', 'S', 'S', 'D'];
export const DAY_NAMES = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
const SHIFTS = ['matutino', 'vespertino'] as const;

/** The editor's model, like the Atualizador's "Repetição": index 0 = Monday. */
export interface PeriodDraft {
  mode: 'interval' | 'times' | 'off';
  every: number;
  from: string;
  to: string;
  times: string[];
  weekdays: number[];
  finalCheck: string;
  timezone: string;
  /** The saved schedule had different times per day or shift, or a day with only one
   *  shift enabled (made in the Ecossistema): saving here makes them all equal. */
  custom: boolean;
}

export const DEFAULT_DRAFT: PeriodDraft = {
  mode: 'interval', every: 30, from: '07:00', to: '17:30', times: ['08:00', '12:00', '17:00'],
  weekdays: [0, 1, 2, 3, 4], finalCheck: '', timezone: 'America/Bahia', custom: false,
};

const toMinutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const toTime = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
export const isTime = (t: string) => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t);
/** Index 0 = Monday in the editor; the server uses 0 = Sunday. */
const serverDay = (i: number) => (i + 1) % 7;
const editorDay = (d: number) => (d + 6) % 7;

/** Collection times of one day, in order. */
export function dayTimes(draft: PeriodDraft): string[] {
  if (draft.mode === 'off') return [];
  if (draft.mode === 'times') return [...new Set(draft.times.filter(isTime))].sort();
  if (!isTime(draft.from) || !isTime(draft.to) || !(draft.every >= 5)) return [];
  const times: string[] = [];
  for (let m = toMinutes(draft.from); m <= toMinutes(draft.to) && times.length <= MAX_PER_DAY; m += draft.every) times.push(toTime(m));
  return times;
}

/** A sentence for the task card ("A cada 30 min, das 07:00 às 17:30 · seg a sex"). */
export function scheduleText(draft: PeriodDraft): string {
  if (draft.mode === 'off' || !draft.weekdays.length) return 'Sem coletas automáticas';
  const days = daysText(draft.weekdays);
  const when = draft.mode === 'interval'
    ? `A cada ${draft.every} min, das ${draft.from} às ${draft.to}`
    : `Às ${dayTimes(draft).join(', ')}`;
  return `${when} · ${days}${draft.finalCheck ? ` · conferência às ${draft.finalCheck}` : ''}`;
}

function daysText(days: number[]): string {
  const sorted = [...days].sort();
  const short = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
  if (sorted.length === 7) return 'todos os dias';
  const consecutive = sorted.every((d, i) => i === 0 || d === sorted[i - 1] + 1);
  if (consecutive && sorted.length > 2) return `${short[sorted[0]]} a ${short[sorted[sorted.length - 1]]}`;
  return sorted.map(d => short[d]).join(', ');
}

/** Problems that block saving, in plain words. */
export function draftProblem(draft: PeriodDraft): string | null {
  if (draft.mode === 'off') return null;
  if (!draft.weekdays.length) return 'Escolha pelo menos um dia.';
  if (draft.mode === 'interval') {
    if (!isTime(draft.from) || !isTime(draft.to)) return 'Informe o início e o fim do período.';
    if (toMinutes(draft.to) < toMinutes(draft.from)) return 'O fim do período deve ser depois do início.';
    if (!(draft.every >= 5 && draft.every <= 720)) return 'O intervalo deve ficar entre 5 e 720 minutos.';
  }
  const times = dayTimes(draft);
  const finalOnly = !times.length && isTime(draft.finalCheck);
  if (!times.length && !finalOnly) return 'Informe pelo menos um horário.';
  const total = times.length + (draft.finalCheck ? 1 : 0);
  if (total > MAX_PER_DAY) return `São ${total} coletas por dia; o limite é ${MAX_PER_DAY}. Aumente o intervalo ou encurte o período.`;
  if (draft.finalCheck && (!isTime(draft.finalCheck) || (times.length > 0 && draft.finalCheck <= times[times.length - 1])))
    return 'A conferência final deve ser depois da última coleta do dia.';
  // Same rule as the Ecossistema's agenda: two moments of a day 5+ minutes apart.
  const moments = [...times, ...(draft.finalCheck ? [draft.finalCheck] : [])].map(toMinutes);
  if (moments.some((m, i) => i > 0 && m - moments[i - 1] < MIN_GAP_MINUTES))
    return `Deixe pelo menos ${MIN_GAP_MINUTES} minutos entre as coletas.`;
  return null;
}

export function toShared(draft: PeriodDraft): SharedSchedule {
  const times = dayTimes(draft);
  const rules: SharedSchedule['rules'] = [];
  for (let day = 0; day < 7; day++) {
    // A day with only the final check stays enabled with that single moment.
    const enabled = draft.mode !== 'off' && draft.weekdays.includes(editorDay(day)) && (times.length > 0 || isTime(draft.finalCheck));
    for (const shift of SHIFTS)
      rules.push({ weekday: day, shift, enabled, times: enabled ? times : [], recheck: enabled && draft.finalCheck ? draft.finalCheck : null });
  }
  return { timezone: draft.timezone, rules };
}

export function fromShared(schedule: SharedSchedule | null): PeriodDraft {
  if (!schedule) return { ...DEFAULT_DRAFT };
  const enabled = schedule.rules.filter(r => r.enabled && (r.times.length || r.recheck));
  if (!enabled.length) return { ...DEFAULT_DRAFT, mode: 'off', timezone: schedule.timezone };
  const signature = (r: SharedSchedule['rules'][number]) => `${[...r.times].sort().join(',')}|${r.recheck ?? ''}`;
  const days = new Set(enabled.map(r => r.weekday));
  const oneShiftOnly = [...days].some(d => enabled.filter(r => r.weekday === d).length !== SHIFTS.length);
  const custom = new Set(enabled.map(signature)).size > 1 || oneShiftOnly;
  // The whole day in one list (both shifts): every time of the enabled rules;
  // the last recheck of the day, when after every time, is the final check.
  const rechecks = [...new Set(enabled.map(r => r.recheck).filter((t): t is string => !!t))].sort();
  const regular = [...new Set(enabled.flatMap(r => r.times))].sort();
  const last = rechecks.at(-1);
  const finalCheck = last && (!regular.length || last > regular[regular.length - 1]) ? last : '';
  const times = [...new Set([...regular, ...rechecks.filter(t => t !== finalCheck)])].sort();
  const weekdays = [...new Set(enabled.map(r => editorDay(r.weekday)))].sort();
  // The saved times travel in every mode, so switching to fixed times never
  // shows (and saves) the defaults instead of the school's agenda.
  const base = { ...DEFAULT_DRAFT, times, weekdays, finalCheck, timezone: schedule.timezone, custom };
  const steps = times.slice(1).map((t, i) => toMinutes(t) - toMinutes(times[i]));
  if (times.length >= 3 && steps.every(s => s === steps[0]) && steps[0] >= 5)
    return { ...base, mode: 'interval', every: steps[0], from: times[0], to: times[times.length - 1] };
  return { ...base, mode: 'times', times };
}

/** Reads the typed list of fixed times; anything unreadable or repeated is reported, never dropped. */
export function parseTimesText(text: string): { times: string[]; invalid: string[]; repeated: string[] } {
  const tokens = text.split(/[,;\s]+/).map(t => t.trim()).filter(Boolean);
  const times: string[] = [], invalid: string[] = [], repeated: string[] = [];
  for (const token of tokens) {
    const value = /^\d:\d{2}$/.test(token) ? `0${token}` : token;
    if (!isTime(value)) invalid.push(token);
    else if (times.includes(value)) repeated.push(token);
    else times.push(value);
  }
  return { times: times.sort(), invalid, repeated };
}

/** Next moment from `now` among per-day minutes (index 0 = Monday), in a time zone. */
/** Civil date and time of an instant in a time zone. */
function civil(at: Date, timezone: string) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, weekday: 'short', year: 'numeric', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(at);
  const get = (type: string) => Number(parts.find(p => p.type === type)?.value ?? NaN);
  const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(parts.find(p => p.type === 'weekday')?.value ?? '');
  return { year: get('year'), month: get('month'), day: get('day'), minute: get('hour') * 60 + get('minute'), weekday };
}

/** The instant of a civil date + minute of day in a zone, across DST changes
 *  (two passes over the zone offset; a skipped hour lands just after the jump). */
function instant(year: number, month: number, day: number, minute: number, timezone: string): Date {
  const wanted = Date.UTC(year, month - 1, day, 0, minute);
  let guess = wanted;
  for (let pass = 0; pass < 2; pass++) {
    const seen = civil(new Date(guess), timezone);
    const shown = Date.UTC(seen.year, seen.month - 1, seen.day, 0, seen.minute);
    guess += wanted - shown;
  }
  return new Date(guess);
}

function nextFrom(dayMinutes: (day: number) => number[], timezone: string, now: Date): Date | null {
  const today = civil(now, timezone);
  for (let offset = 0; offset < 8; offset++) {
    const next = dayMinutes((today.weekday + offset) % 7).sort((a, b) => a - b).find(m => offset > 0 || m > today.minute);
    if (next === undefined) continue;
    // Civil day arithmetic on the calendar, never as 1440 real minutes per day.
    const date = new Date(Date.UTC(today.year, today.month - 1, today.day + offset));
    return instant(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate(), next, timezone);
  }
  return null;
}

/** Next collection time from now, in the school's time zone; null when none. */
export function nextRun(draft: PeriodDraft, now = new Date()): Date | null {
  const times = [...dayTimes(draft), ...(draft.finalCheck ? [draft.finalCheck] : [])].map(toMinutes);
  if (!times.length || !draft.weekdays.length) return null;
  return nextFrom(day => (draft.weekdays.includes(day) ? [...times] : []), draft.timezone, now);
}

/** Next collection of the agenda exactly as saved (any per-day or per-shift
 *  difference made in the Ecossistema included), not of its editor summary. */
export function nextSharedRun(schedule: SharedSchedule | null, now = new Date()): Date | null {
  if (!schedule) return null;
  return nextFrom(day => [...new Set(schedule.rules
    .filter(r => r.enabled && r.weekday === serverDay(day))
    .flatMap(r => [...r.times, ...(r.recheck ? [r.recheck] : [])]))].filter(isTime).map(toMinutes), schedule.timezone, now);
}
