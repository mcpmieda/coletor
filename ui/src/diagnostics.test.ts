import { expect, test } from 'vitest';
import { collectDiagnostics, groupDiagnostics } from './diagnostics';
import type { Issue } from './types';
test('identical errors on two cards survive; adapter copies do not double count', () => {
  const a: Issue = { code: 'GRID_COVERAGE_INVALID', severity: 'error', message: 'Grid invalid', source_student_ref: 'row:1', date: '2026-02-01', lesson: 2 };
  const b = { ...a, source_student_ref: 'row:2' };
  const issues = collectDiagnostics([a,b],[a,b]);
  expect(issues).toHaveLength(2);
  expect(groupDiagnostics(issues)[0].cards.size).toBe(2);
  expect(issues.map(i => i.source_student_ref)).toEqual(['row:1','row:2']);
  expect(JSON.stringify(issues)).not.toContain('display_name');
});
