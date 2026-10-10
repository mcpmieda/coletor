import { afterEach, expect, test, vi } from 'vitest';
import { loadDemo, previewHtml } from './api';
import { STATE_LABELS } from './types';
afterEach(() => vi.unstubAllGlobals());

test('every observed state has an honest label', () => {
  expect(Object.keys(STATE_LABELS).sort()).toEqual(['present','absent','planned_unknown','unmarked','unknown','excused_absent','non_school_day','outside_enrollment'].sort());
  expect(STATE_LABELS.planned_unknown).toContain('sem confirmação');
});
test('browser adapter submits only local preview, without credentials or caching', async () => {
  vi.stubGlobal('window', { location: { protocol: 'http:' } });
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ snapshot: { class_id: 'TESTE-A' } }) });
  vi.stubGlobal('fetch', fetcher);
  await previewHtml('<html></html>', ' TESTE-A ', 2026);
  const [path, options] = fetcher.mock.calls[0];
  expect(path).toBe('/api/preview');
  expect(options.credentials).toBe('omit');
  expect(options.cache).toBe('no-store');
  expect(JSON.parse(options.body)).toEqual({html:'<html></html>',class_id:'TESTE-A',year:2026});
});
test('native errors become readable UI errors', async () => {
  vi.stubGlobal('window', { pywebview: { api: { load_demo: async () => ({ error: 'Arquivo inválido.' }) } } });
  await expect(loadDemo()).rejects.toThrow('Arquivo inválido.');
});
test('native bridge does not fall back to network when present', async () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  vi.stubGlobal('window', { pywebview: { api: { load_demo: async () => ({ snapshot: { year: 2026 } }) } } });
  expect((await loadDemo()).snapshot.year).toBe(2026);
  expect(fetcher).not.toHaveBeenCalled();
});
test('network errors never claim success', async () => {
  vi.stubGlobal('window', { location: { protocol: 'http:' } });
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('internal-secret-detail')));
  await expect(loadDemo()).rejects.toThrow('O serviço local não respondeu.');
});
