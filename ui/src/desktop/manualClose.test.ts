import { expect, test } from 'vitest';
import { closeProblem } from './manualClose';

test('the class choice stays open until the Smecel session is really closed', () => {
  expect(closeProblem({ state: 'closed' })).toBeNull();
  expect(closeProblem({ error: 'A limpeza não terminou.' })).toBe('A limpeza não terminou.');
  expect(closeProblem({ state: 'closed', cleanup_pending: true })).toBe('O Smecel ainda está sendo fechado.');
  expect(closeProblem({ state: 'list_ready' })).toBe('O Smecel ainda está sendo fechado.');
  expect(closeProblem(undefined)).not.toBeNull();
});
