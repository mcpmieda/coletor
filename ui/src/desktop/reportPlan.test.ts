import { describe, expect, it } from 'vitest';
import type { HistoryEntry, ReportSchedule, SharedSchedule } from '../collector';
import { frequencyMinutes, nextReportRun, reportClash, reportMinutes, reportProblem, reportTimes } from './reportPlan';
import { groupReportRuns, logEvents } from './runs';

const report: ReportSchedule = { timezone: 'America/Bahia', enabled: true, every: 60, from: '07:15', to: '09:15', weekdays: [1, 2] };
const frequency = (times: string[]): SharedSchedule => ({ timezone: 'America/Bahia', rules: [0, 1, 2, 3, 4, 5, 6].flatMap(weekday =>
  (['matutino', 'vespertino'] as const).map(shift => ({ weekday, shift, enabled: weekday === 1 && shift === 'matutino', times, recheck: null }))) });

describe('student report agenda', () => {
  it('times, next run and limits', () => {
    expect(reportTimes(report)).toEqual(['07:15', '08:15', '09:15']);
    expect(reportTimes({ ...report, enabled: false })).toEqual([]);
    // Monday 26/10/2026 08:00 in Bahia (11:00 UTC): the next one is 08:15 the same day.
    expect(nextReportRun(report, new Date('2026-10-26T11:00:00Z'))?.toISOString()).toBe('2026-10-26T11:15:00.000Z');
    expect(reportProblem({ ...report, every: 20 })).toMatch(/30 a 720/);
    expect(reportProblem({ ...report, from: '10:00' })).toMatch(/depois/);
    expect(reportProblem(report)).toBeNull();
  });

  it('never together with the frequency, by the measured run lengths', () => {
    // Without measurements only the same minute clashes.
    expect(reportClash(report, frequency(['08:15']), 0, 0)).toMatch(/Segunda: o relatório das 08:15 coincide com a frequência das 08:15/);
    expect(reportClash(report, frequency(['08:00']), 0, 0)).toBeNull();
    // A frequency run of 20 minutes at 08:00 still runs at 08:15.
    expect(reportClash(report, frequency(['08:00']), 2, 20)).toMatch(/08:15/);
    // A report of 5 minutes at 08:15 still runs at 08:18.
    expect(reportClash(report, frequency(['08:18']), 5, 1)).toMatch(/08:15/);
    expect(reportClash(report, frequency(['08:21']), 5, 1)).toBeNull();
    // Another weekday, or the report off: no clash.
    expect(reportClash({ ...report, weekdays: [3] }, frequency(['08:15']), 0, 0)).toBeNull();
    expect(reportClash({ ...report, enabled: false }, frequency(['08:15']), 0, 0)).toBeNull();
  });

  it('measures the runs from the history', () => {
    const history: HistoryEntry[] = [
      { at: 1000, kind: 'collection-started' }, { at: 1000 + 610, kind: 'collection-finished' },
      { at: 5000, kind: 'collection-started' }, { at: 5000 + 125, kind: 'collection-finished' },
      { at: 9000, kind: 'report-started' }, { at: 9000 + 70, kind: 'report-finished', sent: 391 },
    ];
    expect(frequencyMinutes(history)).toBe(11);
    expect(reportMinutes(history)).toBe(2);
    expect(reportMinutes([])).toBe(0);
  });

  it('its own history', () => {
    const history: HistoryEntry[] = [
      { at: 10, kind: 'report-started' }, { at: 50, kind: 'report-finished', sent: 391, unresolved: 2, conflicts: 1 },
      { at: 100, kind: 'report-started' }, { at: 120, kind: 'report-finished', sent: 391, unchanged: true },
      { at: 200, kind: 'report-started' }, { at: 230, kind: 'report-failed', code: 'SOURCE_READ_FAILED' },
      { at: 300, kind: 'collection-started' },
    ];
    const runs = groupReportRuns(history);
    expect(runs.map(r => r.status)).toEqual(['error', 'ok', 'review']);
    expect(runs[1]!.detail).toBe('391 linha(s) · sem alteração');
    expect(runs[2]!.detail).toContain('2 pendente(s) na Conciliação');
    const failed = logEvents(history).find(e => e.message.startsWith('Relatório de alunos não lido'));
    expect(failed?.level).toBe('error');
    expect(failed?.message).toContain('gerar o relatório');
  });
});
