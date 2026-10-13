import { useSyncExternalStore } from 'react';
import { defaultSchedule, readSchedule, saveSchedule, validateSchedule, type SchoolSchedule } from './schedule';
import { DEFAULT_FOX, FOX_KEY, readFoxPreferences, type FoxPreferences } from './mascot/preferences';
import type { ThemeMode } from './theme';

export interface LocalSettings { schemaVersion: 1; schedule: SchoolSchedule | null; theme: ThemeMode; fox: FoxPreferences }
type Reply = { settings: LocalSettings; notice?: string } | { error: string };
export interface SettingsBridge {
  get_local_settings(): Promise<Reply>;
  save_schedule(schedule: SchoolSchedule): Promise<Reply>;
  save_theme(theme: ThemeMode): Promise<Reply>;
  save_fox(fox: FoxPreferences): Promise<Reply>;
}
let nativeMode = false;
let bridge: SettingsBridge | undefined;
let cached: LocalSettings = { schemaVersion: 1, schedule: null, theme: 'system', fox: { ...DEFAULT_FOX } };
let notice = '';
let writeQueue: Promise<void> = Promise.resolve();
const listeners = new Set<() => void>();
export function useLocalSettingsNotice() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener); }; }, () => notice, () => '');
}
function nativeBridge(): SettingsBridge | undefined {
  const api = window.pywebview?.api;
  return api && typeof api.get_local_settings === 'function' ? api as SettingsBridge : undefined;
}
function accept(reply: Reply): LocalSettings {
  if ('error' in reply) throw new Error(reply.error);
  const s = reply.settings;
  if (s?.schemaVersion !== 1 || !['system', 'light', 'dark'].includes(s.theme) ||
      s.fox?.version !== 1 || typeof s.fox.show !== 'boolean' || typeof s.fox.animate !== 'boolean') {
    throw new Error('Não foi possível ler as configurações. Mostramos as sugestões.');
  }
  return { schemaVersion: 1, schedule: s.schedule === null ? null : validateSchedule(s.schedule), theme: s.theme,
    fox: { version: 1, show: s.fox.show, animate: s.fox.animate } };
}
export async function initializeLocalSettings(): Promise<void> {
  nativeMode = window.location.hash === '#coletor-desktop' || !!nativeBridge();
  if (!nativeMode) return;
  try {
    if (!nativeBridge()) await new Promise<void>((resolve, reject) => {
      const ready = () => { clearTimeout(timer); resolve(); };
      const timer = setTimeout(() => { window.removeEventListener('pywebviewready', ready); reject(new Error()); }, 8000);
      window.addEventListener('pywebviewready', ready, { once: true });
      if (nativeBridge()) { window.removeEventListener('pywebviewready', ready); ready(); }
    });
    bridge = nativeBridge();
    if (!bridge) throw new Error();
    const result = await bridge.get_local_settings();
    cached = accept(result);
    notice = 'notice' in result ? result.notice ?? '' : '';
  } catch {
    notice = 'Não foi possível carregar as configurações. Você pode ajustar nesta sessão.';
  }
}
export function isDesktopSettings() { return nativeMode; }
export function localSettingsNotice() { return notice; }
export function readLocalTheme(): ThemeMode {
  if (nativeMode) return cached.theme;
  try { const value = localStorage.getItem('smecel-collector:theme:v1'); return value === 'light' || value === 'dark' ? value : 'system'; }
  catch { return 'system'; }
}
export function readLocalFox(): FoxPreferences {
  if (nativeMode) return { ...cached.fox };
  try { return readFoxPreferences(window.localStorage); } catch { return { ...DEFAULT_FOX }; }
}
export function readLocalSchedule() {
  if (nativeMode) return { config: cached.schedule ?? defaultSchedule(), notice };
  return readSchedule(window.localStorage);
}
function persist(action: (api: SettingsBridge) => Promise<Reply>) {
  const task = writeQueue.then(async () => {
    if (!bridge) throw new Error('Não foi possível salvar neste computador. Suas alterações continuam na tela.');
    cached = accept(await action(bridge));
    if (notice) { notice = ''; listeners.forEach(listener => listener()); }
    return cached;
  });
  writeQueue = task.then(() => {}, () => {});
  return task;
}
export async function saveLocalSchedule(config: SchoolSchedule): Promise<SchoolSchedule> {
  if (!nativeMode) return saveSchedule(window.localStorage, config);
  const next = validateSchedule({ ...config, localRevision: config.localRevision + 1 });
  const saved = await persist(api => api.save_schedule(next));
  if (!saved.schedule) throw new Error('Não foi possível salvar os horários.');
  return saved.schedule;
}
export async function saveLocalTheme(theme: ThemeMode) {
  if (nativeMode) await persist(api => api.save_theme(theme));
  else localStorage.setItem('smecel-collector:theme:v1', theme);
}
export async function saveLocalFox(fox: FoxPreferences) {
  if (nativeMode) await persist(api => api.save_fox(fox));
  else localStorage.setItem(FOX_KEY, JSON.stringify(fox));
}


export async function reloadLocalSchedule() {
  if (!nativeMode) return readLocalSchedule();
  const task = writeQueue.then(async () => {
    if (!bridge) throw new Error('Não foi possível recarregar os horários.');
    const reply = await bridge.get_local_settings();
    cached = accept(reply);
    notice = 'notice' in reply ? reply.notice ?? '' : '';
    listeners.forEach(listener => listener());
    return readLocalSchedule();
  });
  writeQueue = task.then(() => {}, () => {});
  return task;
}
