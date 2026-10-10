import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import ScheduleSettings from './ScheduleSettings';

test('schedule label includes day and shift for screen readers', () => {
  const html = renderToStaticMarkup(<ScheduleSettings />);
  expect(html).toMatch(/Coletas<span class="sr-only"> Sexta-feira Matutino<\/span>/);
  expect(html).toMatch(/Rechecagem<span class="sr-only"> Segunda-feira Matutino<\/span>/);
  expect(html).toContain('Incluir Sábado Matutino');
});
