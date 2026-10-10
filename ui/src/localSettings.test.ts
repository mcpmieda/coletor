import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { defaultSchedule } from './schedule';

beforeEach(() => vi.resetModules());
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const defaults = () => ({ schemaVersion: 1, schedule: null, theme: 'system', fox: { version: 1, show: true, animate: true } });

test('native startup reads preferences before UI initial state, without HTTP or localStorage', async () => {
  const schedule = defaultSchedule(); schedule.rules[0].times[0] = '08:15';
  const get = vi.fn().mockResolvedValue({ settings: { ...defaults(), schedule, theme: 'dark', fox: { version: 1, show: false, animate: false } } });
  vi.stubGlobal('window', { location: { hash: '#coletor-desktop' }, pywebview: { api: { get_local_settings: get } } });
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  const local = await import('./localSettings'); await local.initializeLocalSettings();
  expect(local.readLocalTheme()).toBe('dark');
  expect(local.readLocalFox().show).toBe(false);
  expect(local.readLocalSchedule().config.rules[0].times[0]).toBe('08:15');
  expect(fetcher).not.toHaveBeenCalled();
});

test('native save awaits successful disk acknowledgement and preserves draft on failure', async () => {
  let resolve!: (value: unknown) => void;
  const save = vi.fn().mockImplementation(() => new Promise(r => { resolve = r; }));
  vi.stubGlobal('window', { location: { hash: '#coletor-desktop' }, pywebview: { api: {
    get_local_settings: async () => ({ settings: defaults() }), save_schedule: save
  } } });
  const local = await import('./localSettings'); await local.initializeLocalSettings();
  const draft = defaultSchedule(); draft.rules[0].times[0] = '08:15';
  const pending = local.saveLocalSchedule(draft);
  await Promise.resolve();
  expect(local.readLocalSchedule().config.rules[0].times[0]).toBe('08:05');
  const sent = save.mock.calls[0][0];
  resolve({ settings: { ...defaults(), schedule: sent } });
  expect((await pending).rules[0].times[0]).toBe('08:15');
  expect(sent.localRevision).toBe(1);
  save.mockResolvedValue({ error: 'Não foi possível salvar.' });
  const changed = defaultSchedule(); changed.rules[0].times[0] = '08:30';
  await expect(local.saveLocalSchedule(changed)).rejects.toThrow('Não foi possível salvar.');
  expect(local.readLocalSchedule().config.rules[0].times[0]).toBe('08:15');
  expect(changed.rules[0].times[0]).toBe('08:30');
});

test('invalid saved IANA timezone falls back visibly without overwriting disk', async () => {
  const bad = defaultSchedule(); bad.timezone = 'Unknown/Nowhere';
  const save = vi.fn();
  vi.stubGlobal('window', { location: { hash: '#coletor-desktop' }, pywebview: { api: {
    get_local_settings: async () => ({ settings: { ...defaults(), schedule: bad } }), save_schedule: save
  } } });
  const local = await import('./localSettings'); await local.initializeLocalSettings();
  expect(local.localSettingsNotice()).toContain('Não foi possível');
  expect(local.readLocalSchedule().config.timezone).toBe('America/Bahia');
  expect(save).not.toHaveBeenCalled();
});

test('native theme and fox use explicit preference methods, never a generic file API', async () => {
  const saveTheme = vi.fn().mockResolvedValue({ settings: { ...defaults(), theme: 'dark' } });
  const saveFox = vi.fn().mockResolvedValue({ settings: { ...defaults(), theme: 'dark', fox: { version:1, show:false, animate:false } } });
  vi.stubGlobal('window', { location: { hash: '#coletor-desktop' }, pywebview: { api: {
    get_local_settings: async () => ({ settings: defaults() }), save_theme: saveTheme, save_fox: saveFox
  } } });
  const local = await import('./localSettings'); await local.initializeLocalSettings();
  await local.saveLocalTheme('dark'); await local.saveLocalFox({ version:1, show:false, animate:false });
  expect(saveTheme).toHaveBeenCalledWith('dark');
  expect(saveFox).toHaveBeenCalledWith({ version:1, show:false, animate:false });
});

test('rapid native preference writes remain ordered and a failed write does not block later saves', async () => {
  let finishFirst!: (value: unknown) => void;
  const saveTheme = vi.fn().mockImplementationOnce(() => new Promise(r => { finishFirst = r; }))
    .mockResolvedValueOnce({ error: 'Não foi possível salvar.' })
    .mockResolvedValueOnce({ settings: { ...defaults(), theme: 'light' } });
  vi.stubGlobal('window', { location: { hash: '#coletor-desktop' }, pywebview: { api: {
    get_local_settings: async () => ({ settings: defaults() }), save_theme: saveTheme
  } } });
  const local = await import('./localSettings'); await local.initializeLocalSettings();
  const first = local.saveLocalTheme('dark');
  const second = local.saveLocalTheme('system');
  const failed = expect(second).rejects.toThrow('Não foi possível salvar.');
  await Promise.resolve();
  expect(saveTheme).toHaveBeenCalledTimes(1);
  finishFirst({ settings: { ...defaults(), theme: 'dark' } });
  await first; await failed;
  await local.saveLocalTheme('light');
  expect(saveTheme.mock.calls.map(c => c[0])).toEqual(['dark', 'system', 'light']);
  expect(local.readLocalTheme()).toBe('light');
});

test('browser preview keeps its own browser storage and never creates a disk endpoint', async () => {
  const data = new Map<string,string>();
  const storage = { getItem: (key:string) => data.get(key) ?? null, setItem: (key:string,value:string) => data.set(key,value) };
  vi.stubGlobal('localStorage', storage);
  vi.stubGlobal('window', { location: { hash: '' }, localStorage: storage });
  const local = await import('./localSettings'); await local.initializeLocalSettings();
  expect(local.isDesktopSettings()).toBe(false);
  await local.saveLocalSchedule(defaultSchedule()); await local.saveLocalTheme('dark');
  expect(local.readLocalTheme()).toBe('dark');
  expect(local.readLocalSchedule().config.localRevision).toBe(1);
});

