import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import SmecelAccess from './SmecelAccess';
import { historyText, type CollectorStatus } from '../collector';

const base: CollectorStatus = { state: 'ready', code: null, active: true, localPaused: false, persistent: true,
  progress: { completed: 0, total: 0, classLabel: null }, lastReceipt: null, settings: null };

test('a saved Smecel login shows only the masked account and never a password field', () => {
  const html = renderToStaticMarkup(<SmecelAccess status={{ ...base, credential: { saved: true, account: 'op•••@escola.invalid' } }} onStatus={() => {}} />);
  expect(html).toContain('op•••@escola.invalid');
  expect(html).toContain('Remover acesso salvo');
  expect(html).not.toContain('type="password"');
});
test('without a saved login the form asks for e-mail and password', () => {
  const html = renderToStaticMarkup(<SmecelAccess status={{ ...base, credential: { saved: false } }} onStatus={() => {}} />);
  expect(html).toContain('E-mail do Smecel');
  expect(html).toContain('type="password"');
});
test('history entries are plain operational sentences without student data', () => {
  expect(historyText({ at: 1, kind: 'class-sent', label: '6A 2026 - MATUTINO', sent: 30, unresolved: 1, conflicts: 0 }))
    .toBe('6A 2026 - MATUTINO enviada · 30 aluno(s) reconhecido(s) · 1 não reconhecido(s)');
  expect(historyText({ at: 1, kind: 'failure', code: 'CLASS_RECONCILIATION_REQUIRED', label: '8D 2026 -VESPERTINO' }))
    .toContain('(8D 2026 -VESPERTINO)');
  expect(historyText({ at: 1, kind: 'failure', code: 'SOURCE_LOGIN_FAILED' })).toContain('recusou');
});
