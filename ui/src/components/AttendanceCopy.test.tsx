import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import AttendancePreview from './AttendancePreview';
import ValidationPanel from './ValidationPanel';
import { STATE_LABELS, type AttendanceState, type Issue, type Preview } from '../types';

function makePreview(issues: Issue[] = []): Preview {
  const states = Object.keys(STATE_LABELS) as AttendanceState[];
  return {
    snapshot: {
      schema_version: '1.0', snapshot_id: 'copy-test', class_id: 'EXEMPLO', year: 2026,
      source_format: 'synthetic-smecel-annual-v1', source_document_complete: true,
      source_student_refs_durable: false,
      students: [{ source_student_ref: 'row:1', display_name: 'Aluno fictício', mat: null }],
      records: states.map((state, index) => ({
        source_student_ref: 'row:1', date: `2026-02-${String(index + 1).padStart(2, '0')}`,
        lesson: 1, state, source_symbol: state === 'planned_unknown' ? '•' : '',
      })),
      issues,
      summary: { students: 1, records: states.length, states: {}, blocking_issues: 0 },
    },
    validation: { allowed: false, issues },
    mode: 'demo', processed_at: '2026-02-01T12:00:00Z',
  };
}

const withoutDetails = (html: string) => html.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g, '');

test('the short panel always preserves the safety warnings, even with no reported issues', () => {
  const preview = makePreview();
  preview.validation.allowed = true;
  const html = withoutDetails(renderToStaticMarkup(<ValidationPanel preview={preview} />));
  expect(html).toContain('Nenhum dado foi enviado');
  expect(html).toContain('Envio desativado');
  expect(html).toContain('Esta versão não está conectada ao Ecossistema.');
  expect(html).toContain('• não confirma presença');
  expect(html).toContain('Os alunos, as matrículas e o calendário ainda precisam de conferência.');
});

test('technical messages stay in closed details and the source data is unchanged', () => {
  const issues: Issue[] = [
    { code: 'API_MAPPING_REQUIRED', severity: 'error', message: 'O vínculo com studentUid precisa ser validado pela API.' },
    { code: 'EXCUSED_ABSENCE_API_MAPPING_REQUIRED', severity: 'error', message: 'O tratamento de falta justificada precisa ser confirmado pelo contrato da API.' },
    { code: 'SOURCE_SYMBOL_AMBIGUOUS', severity: 'warning', message: 'A marcação pode indicar aula prevista; não confirma presença.' },
  ];
  const preview = makePreview(issues);
  const original = JSON.stringify(preview);
  const html = renderToStaticMarkup(<ValidationPanel preview={preview} />);
  const visible = withoutDetails(html);
  expect(visible).not.toMatch(/studentUid|contrato|\bAPI\b|backend|slots|proveniência|idempotência/i);
  expect(visible).toContain('Ainda falta definir como o Ecossistema receberá as faltas justificadas.');
  expect(html).toContain('Ver detalhes (3 diagnósticos)');
  expect(html).not.toMatch(/<details\b[^>]*\bopen(?:\s|=|>)/);
  for (const issue of issues) expect(html).toContain(issue.message);
  expect(JSON.stringify(preview)).toBe(original);
});

test('important issues are not cut off after eight messages', () => {
  const codes = ['DOCUMENT_EMPTY', 'LOGIN_PAGE', 'ROSTER_EMPTY', 'CLASS_MISMATCH', 'YEAR_MISMATCH', 'INVALID_DATE_MARKED', 'STUDENT_NAME_MISSING', 'DUPLICATE_RECORD', 'SNAPSHOT_CHANGED'];
  const html = withoutDetails(renderToStaticMarkup(<ValidationPanel preview={makePreview(codes.map(code => ({ code, severity: 'error', message: code })))} />));
  expect(html.match(/class="validation-issue error"/g)).toHaveLength(9);
  expect(html).toContain('Os dados mudaram após a leitura. Abra o arquivo novamente.');
});

test('unrecognized diagnostics remain available for review without leaking jargon into the summary', () => {
  const html = renderToStaticMarkup(<ValidationPanel preview={makePreview([{ code: 'FUTURE_CHECK', severity: 'error', message: 'Novo diagnóstico técnico: backend.' }])} />);
  expect(withoutDetails(html)).toContain('Este aviso precisa de conferência. Veja os detalhes.');
  expect(withoutDetails(html)).not.toContain('backend');
  expect(html).toContain('Novo diagnóstico técnico: backend.');
});

test('the attendance table keeps uncertainty and every observed state distinct', () => {
  const html = renderToStaticMarkup(<AttendancePreview preview={makePreview()} />);
  expect(html).toContain('Alunos a conferir');
  expect(html).toContain('Aluno não conferido');
  expect(html).toContain('Registros do diário; os alunos e as matrículas ainda precisam de conferência');
  expect(STATE_LABELS.planned_unknown).toContain('sem confirmação');
  expect(STATE_LABELS.planned_unknown).toContain('prevista');
  expect(STATE_LABELS.outside_enrollment).toContain('período de matrícula');
  for (const label of Object.values(STATE_LABELS)) expect(html).toContain(label);
  expect(new Set(Object.values(STATE_LABELS)).size).toBe(Object.keys(STATE_LABELS).length);
  expect(html).not.toMatch(/studentUid|contrato|proveniência|slots|backend|idempotência/i);
});
