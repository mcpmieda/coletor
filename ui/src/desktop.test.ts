import { afterEach, expect, test, vi } from 'vitest';
import { hideInTray, syncTrayContext, type TrayBridge } from './desktop';
afterEach(() => vi.restoreAllMocks());
test('tray context is ordered and only forwards activity plus a boolean, never diary contents', async () => {
  let release!: (value: unknown) => void;
  const set = vi.fn().mockImplementationOnce(() => new Promise(r => { release = r; }))
    .mockRejectedValueOnce(new Error('unavailable')).mockResolvedValue({ ok:true });
  const api = { set_tray_context: set } as unknown as TrayBridge;
  const first = syncTrayContext(api, 'reading', false);
  const failed = syncTrayContext(api, 'error', true);
  const check = expect(failed).rejects.toThrow('unavailable');
  await Promise.resolve(); expect(set).toHaveBeenCalledTimes(1);
  release({ok:true}); await first; await check;
  await syncTrayContext(api, 'idle', true);
  expect(set.mock.calls).toEqual([['reading',false],['error',true],['idle',true]]);
});
test('a window the tray did not hide says why, in the tray\'s own words or a plain one', async () => {
  expect(await hideInTray({ hide_window: async () => ({ hidden: true }) })).toBeUndefined();
  expect(await hideInTray({ hide_window: async () => ({ error: 'A bandeja não está disponível. A janela continua aberta.' }) }))
    .toBe('A bandeja não está disponível. A janela continua aberta.');
  expect(await hideInTray({ hide_window: () => Promise.reject(new Error('native detail')) })).toBe('Não foi possível ocultar a janela.');
});
