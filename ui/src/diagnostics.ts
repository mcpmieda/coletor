import type { Issue } from './types';

// The parser aggregates repeated marks per code/card and retains the first
// location. Counts below describe diagnostics and cards, never all events.
export function collectDiagnostics(snapshot: Issue[], validation: Issue[]): Issue[] {
  const unique = new Map<string, Issue>();
  for (const issue of [...snapshot, ...validation]) {
    const key = JSON.stringify([issue.code, issue.severity, issue.message, issue.source_student_ref, issue.date, issue.lesson]);
    if (!unique.has(key)) unique.set(key, issue);
  }
  return [...unique.values()];
}
export function groupDiagnostics(issues: Issue[]) {
  const groups = new Map<string, { issue: Issue; diagnostics: number; cards: Set<string> }>();
  for (const issue of issues) {
    const key = `${issue.severity}:${issue.code}`;
    const group = groups.get(key) ?? { issue, diagnostics: 0, cards: new Set<string>() };
    group.diagnostics++;
    if (issue.source_student_ref) group.cards.add(issue.source_student_ref);
    groups.set(key, group);
  }
  return [...groups.values()];
}
