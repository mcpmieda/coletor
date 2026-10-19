import type { SharedSchedule } from '../collector';

/** Server limit of collections per day (each shift rule holds the same times). */
export const MAX_PER_DAY = 48;
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
  /** The saved schedule had different times per day/shift (made in the Ecossistema). */
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
  if (!times.length) return 'Informe pelo menos um horário.';
  const total = times.length + (draft.finalCheck ? 1 : 0);
  if (total > MAX_PER_DAY) return `São ${total} coletas por dia; o limite é ${MAX_PER_DAY}. Aumente o intervalo ou encurte o período.`;
  if (draft.finalCheck && (!isTime(draft.finalCheck) || draft.finalCheck <= times[times.length - 1]))
    return 'A conferência final deve ser depois da última coleta do dia.';
  return null;
}

export function toShared(draft: PeriodDraft): SharedSchedule {
  const times = dayTimes(draft);
  const rules: SharedSchedule['rules'] = [];
  for (let day = 0; day < 7; day++) {
    const enabled = draft.mode !== 'off' && draft.weekdays.includes(editorDay(day)) && times.length > 0;
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
  const custom = new Set(enabled.map(signature)).size > 1;
  const sample = enabled.reduce((a, b) => (b.times.length > a.times.length ? b : a));
  const times = [...sample.times].sort();
  const weekdays = [...new Set(enabled.map(r => editorDay(r.weekday)))].sort();
  const base = { ...DEFAULT_DRAFT, weekdays, finalCheck: sample.recheck ?? '', timezone: schedule.timezone, custom };
  const steps = times.slice(1).map((t, i) => toMinutes(t) - toMinutes(times[i]));
  if (times.length >= 3 && steps.every(s => s === steps[0]) && steps[0] >= 5)
    return { ...base, mode: 'interval', every: steps[0], from: times[0], to: times[times.length - 1] };
  return { ...base, mode: 'times', times };
}

/** Next collection time from now, in the school's time zone; null when none. */
export function nextRun(draft: PeriodDraft, now = new Date()): Date | null {
  const times = [...dayTimes(draft), ...(draft.finalCheck ? [draft.finalCheck] : [])];
  if (!times.length || !draft.weekdays.length) return null;
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: draft.timezone, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(now);
  const get = (type: string) => parts.find(p => p.type === type)?.value ?? '';
  const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(get('weekday'));
  const minute = Number(get('hour')) * 60 + Number(get('minute'));
  for (let offset = 0; offset < 8; offset++) {
    const day = (weekday + offset) % 7;
    if (!draft.weekdays.includes(day)) continue;
    const next = times.map(toMinutes).sort((a, b) => a - b).find(m => offset > 0 || m > minute);
    if (next !== undefined) return new Date(now.getTime() + ((offset * 1440 + next - minute) * 60 - now.getSeconds()) * 1000);
  }
  return null;
}
