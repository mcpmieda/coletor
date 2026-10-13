import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import FoxCompanion from './FoxCompanion';

test('fox is optional, keyboard reachable, and has explicit animation controls', () => {
  const html = renderToStaticMarkup(<FoxCompanion activity="idle" />);
  expect(html).toContain('Fazer carinho na raposa');
  expect(html).toContain('Mostrar raposa');expect(html).toContain('Animar raposa');
  expect(html).toContain('alt="Raposa vermelha, mascote do coletor"');
});
test('captions never report a remote collection or synchronization', () => {
  const reading = renderToStaticMarkup(<FoxCompanion activity="reading" />);
  const review = renderToStaticMarkup(<FoxCompanion activity="review" />);
  const error = renderToStaticMarkup(<FoxCompanion activity="error" />);
  expect(reading).toContain('Lendo o diário');
  expect(review).toContain('pontos para conferir');expect(error).toContain('arquivo precisa de atenção');
  expect(reading+review+error).not.toMatch(/sincronizado|conectado|coleta concluída/i);
});
