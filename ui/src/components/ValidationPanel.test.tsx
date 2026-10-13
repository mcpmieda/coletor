import { test, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import ValidationPanel from './ValidationPanel';
import type { Preview } from '../types';
test('details retain both cards, first location, pagination and private header exclusion', () => {
  const issues = Array.from({ length: 25 },(_,i) => ({ code:'GRID_COVERAGE_INVALID',severity:'error' as const,message:'Grade incompleta.',source_student_ref:`row:${i+1}`,date:'2026-02-01',lesson:2 }));
  const preview = { snapshot:{ issues },validation:{issues} } as Preview;
  const html = renderToStaticMarkup(<ValidationPanel preview={preview} />);
  expect(html).toContain('25 fichas identificadas');
  expect(html).toContain('row:1'); expect(html).toContain('row:2');
  expect(html).toContain('2026-02-01'); expect(html).toContain('posição 2');
  expect(html).toContain('Página 1 de 2'); expect(html).not.toContain('row:21');
  expect(html).not.toContain('display_name');
});
