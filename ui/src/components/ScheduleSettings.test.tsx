import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import ScheduleSettings from './ScheduleSettings';

test('schedule label includes day and shift for screen readers', () => {
  const html = renderToStaticMarkup(<ScheduleSettings />);
  expect(html).toMatch(/Buscar frequência<span class="sr-only"> Sexta-feira Manhã<\/span>/);
  expect(html).toMatch(/Conferir no fim<span class="sr-only"> Segunda-feira Manhã<\/span>/);
  expect(html).toContain('Incluir Sábado Manhã');
});

test('school sharing does not prescribe a number of users or computers', () => {
  const html = renderToStaticMarkup(<ScheduleSettings />);
  expect(html).toContain('usuários e computadores autorizados poderão usar os mesmos horários');
  expect(html).not.toMatch(/(?:três|three|\b3)\s+(?:usuários|computadores|PCs|dispositivos)/i);
  expect(html).toContain('O acesso e o compartilhamento ainda serão preparados');
});
