import type { HistoryEntry, ReportSchedule, SharedSchedule } from '../collector';
import { DAY_NAMES, nextFrom } from './periods';

/** Ecossistema rule (frequencyReportScheduleV2): the report runs every 30 minutes or more. */
export const REPORT_MIN_EVERY = 30;
export const DEFAULT_REPORT: ReportSchedule = {
  timezone: 'America/Bahia', enabled: true, every: 60, from: '07:15', to: '17:15', weekdays: [1, 2, 3, 4, 5],
};
const toMinutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const toTime = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
const isTime = (t: string) => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t);
/** The editor's days are Monday first (0); the server's are Sunday first (0). */
const serverDay = (editor: number) => (editor + 1) % 7;

/** The report's times of a day ('HH:MM'), as the Coletor runs them. */
export function reportTimes(schedule: ReportSchedule | null | undefined): string[] {
  if (!schedule?.enabled || !isTime(schedule.from) || !isTime(schedule.to) || !(schedule.every >= REPORT_MIN_EVERY)) return [];
  const times: string[] = [];
  for (let m = toMinutes(schedule.from); m <= toMinutes(schedule.to); m += schedule.every) times.push(toTime(m));
  return times;
}

export function nextReportRun(schedule: ReportSchedule | null | undefined, now = new Date()): Date | null {
  const times = reportTimes(schedule).map(toMinutes);
  if (!schedule || !times.length) return null;
  return nextFrom(day => (schedule.weekdays.includes(serverDay(day)) ? [...times] : []), schedule.timezone, now);
}

export function reportText(schedule: ReportSchedule | null | undefined): string {
  if (!schedule) return 'Agenda ainda não configurada';
  if (!schedule.enabled || !schedule.weekdays.length) return 'Sem leituras automáticas';
  const days = [...schedule.weekdays].map(d => (d + 6) % 7).sort((a, b) => a - b).map(d => DAY_NAMES[d].slice(0, 3).toLowerCase());
  return `A cada ${schedule.every} min, das ${schedule.from} às ${schedule.to} · ${days.join(', ')}`;
}

/**
 * How long a run really takes here, in whole minutes (owner decision 29/10/2026: the margin comes
 * from the last runs, never a fixed number): the longest of the last ten finished runs that start
 * and end with these kinds. 0 while none was measured.
 */
export function runMinutes(history: readonly HistoryEntry[], start: string, ends: readonly string[]): number {
  const sorted = [...history].sort((a, b) => a.at - b.at);
  const durations: number[] = [];
  let open: number | null = null;
  for (const e of sorted) {
    if (e.kind === start) open = e.at;
    else if (open !== null && ends.includes(e.kind)) { durations.push(e.at - open); open = null; }
  }
  const recent = durations.slice(-10);
  return recent.length ? Math.ceil(Math.max(...recent) / 60) : 0;
}

export const frequencyMinutes = (history: readonly HistoryEntry[]) =>
  runMinutes(history, 'collection-started', ['collection-finished', 'collection-stopped', 'failure']);
export const reportMinutes = (history: readonly HistoryEntry[]) =>
  runMinutes(history, 'report-started', ['report-finished', 'report-failed']);

/**
 * The first report time that would run together with a frequency time, or null. A report at r and a
 * frequency at f overlap when [r, r + report) and [f, f + frequency) meet; the Coletor never runs
 * the two together, so the editors refuse such an agenda.
 */
export function reportClash(report: ReportSchedule | null | undefined, frequency: SharedSchedule | null | undefined,
  reportLength: number, frequencyLength: number): string | null {
  const times = reportTimes(report).map(toMinutes);
  if (!report || !frequency || !times.length) return null;
  for (const weekday of [1, 2, 3, 4, 5, 6, 0]) {
    if (!report.weekdays.includes(weekday)) continue;
    const slots = [...new Set(frequency.rules.filter(r => r.enabled && r.weekday === weekday)
      .flatMap(r => [...r.times, ...(r.recheck ? [r.recheck] : [])]))].filter(isTime).map(toMinutes);
    for (const r of times) {
      const f = slots.find(f => r < f + Math.max(frequencyLength, 1) && f < r + Math.max(reportLength, 1));
      if (f !== undefined)
        return `${DAY_NAMES[(weekday + 6) % 7]}: o relatório das ${toTime(r)} coincide com a frequência das ${toTime(f)}.`;
    }
  }
  return null;
}

export function reportProblem(schedule: ReportSchedule): string | null {
  if (!isTime(schedule.from) || !isTime(schedule.to)) return 'Preencha os horários.';
  if (schedule.from > schedule.to) return 'O horário final deve vir depois do inicial.';
  if (!(schedule.every >= REPORT_MIN_EVERY && schedule.every <= 720)) return `O intervalo vai de ${REPORT_MIN_EVERY} a 720 minutos.`;
  if (schedule.enabled && !schedule.weekdays.length) return 'Escolha pelo menos um dia.';
  return null;
}
