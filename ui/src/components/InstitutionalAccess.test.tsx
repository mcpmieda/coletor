import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import { COLLECTOR_CODES } from '../collector';
import InstitutionalAccess, { accessRetried } from './InstitutionalAccess';
import source from './InstitutionalAccess.tsx?raw';

test('a wrong Windows clock, like a lost connection, keeps the open panel instead of asking to sign in again', () => {
  expect(accessRetried('ACCESS_UNAVAILABLE')).toBe(true);
  expect(accessRetried('CLOCK_OUT_OF_SYNC')).toBe(true);
  // Anything else is a real loss of access.
  for (const code of [undefined, 'not-authorized', 'ACCESS_REQUIRED', 'SERVER_REVOCATION_PENDING', 'ACCESS_NOT_CONFIGURED']) expect(accessRetried(code), code).toBe(false);
  expect(source).toContain('accessRetried(result.code) && (optimistic.current || previouslyAuthorized.current)');
  // Over the panel and on the entry screen, the same words as the collector's own status.
  expect(COLLECTOR_CODES.CLOCK_OUT_OF_SYNC).toContain('relógio do Windows');
  expect(source).toContain('{clockWrong && <p role="alert" className="p-4">{COLLECTOR_CODES.CLOCK_OUT_OF_SYNC}</p>}');
  expect(source).toContain("result.code === 'CLOCK_OUT_OF_SYNC' ? COLLECTOR_CODES.CLOCK_OUT_OF_SYNC");
});

test('the entry screen never asks for a password in the program', () => {
  const html = renderToStaticMarkup(<InstitutionalAccess />);
  expect(html).toContain('Entrar no Ecossistema');
  expect(html).not.toContain('type="password"');
});
