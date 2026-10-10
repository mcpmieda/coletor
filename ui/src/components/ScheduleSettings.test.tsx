import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import ScheduleSettings from './ScheduleSettings';

test('schedule label includes day and shift for screen readers', () => {
  const html = renderToStaticMarkup(<ScheduleSettings />);
  expect(html).toMatch(/Coletas<span class="sr-only"> Sexta-feira Matutino<\/span>/);
  expect(html).toMatch(/Rechecagem<span class="sr-only"> Segunda-feira Matutino<\/span>/);
  expect(html).toContain('Incluir Sábado Matutino');
});

test('school sharing does not prescribe a number of users or computers', () => {
  const html = renderToStaticMarkup(<ScheduleSettings />);
  expect(html).toContain('Usuários e computadores autorizados usarão a mesma configuração');
  expect(html).not.toMatch(/(?:três|three|\b3)\s+(?:usuários|computadores|PCs|dispositivos)/i);
  expect(html).toContain('quando o login e a sincronização forem implementados');
});
