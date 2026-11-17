import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import { HISTORY_LIMIT } from '../collector';
import { LogsPage } from './HistoryPages';
import useColetor from './useColetor.ts?raw';

test('Registros states the limit the window really keeps, with its lines and filters', () => {
  const html = renderToStaticMarkup(<LogsPage history={[{ at: 1_800_000_000, kind: 'collection-started', sent: 2 }]} />);
  expect(HISTORY_LIMIT).toBe(2000);
  expect(html).toContain('Até 2.000 eventos recentes deste computador');
  expect(useColetor).toContain('.slice(0, HISTORY_LIMIT)');
  expect(html).toContain('Coleta iniciada.');
  expect(html).toContain('Erros');
});
