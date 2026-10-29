import type { CollectorStatus, HistoryEntry, SharedSchedule } from '../collector';
import type { ThemeMode } from '../theme';

export interface Preferences {
  theme: ThemeMode;
  fox: { version: 1; show: boolean; animate: boolean };
  browser: { visible: boolean };
  classes: { mode: 'all' | 'chosen' };
  notifications: { show: boolean };
}
export interface StartupSnapshot {
  paired: boolean;
  status: Partial<CollectorStatus> | null;
  history: HistoryEntry[];
  settings: Preferences;
  /** The running program's version, as in its window title. */
  version: string;
}
type Failure = { error: string; code?: string };
export type Status = CollectorStatus & { classesMode?: 'all' | 'chosen' };

interface Native {
  get_startup_snapshot(): Promise<StartupSnapshot>;
  get_collector_status(): Promise<Status | Failure>;
  get_collector_history(after?: number): Promise<{ entries: HistoryEntry[] } | Failure>;
  get_local_settings(): Promise<{ settings: Preferences } | Failure>;
  activate_collector(): Promise<Status | Failure>;
  collect_now(): Promise<Status | Failure>;
  pause_collector(paused: boolean): Promise<Status | Failure>;
  save_shared_schedule(revision: number, schedule: SharedSchedule): Promise<Status | Failure>;
  save_source_credential(email: string, password: string): Promise<Status | Failure>;
  forget_source_credential(): Promise<Status | Failure>;
  save_browser_preference(visible: boolean): Promise<{ settings: Preferences } | Failure>;
  save_classes_mode(mode: 'all' | 'chosen'): Promise<{ settings: Preferences } | Failure>;
  save_notifications(show: boolean): Promise<{ settings: Preferences } | Failure>;
  save_theme(theme: ThemeMode): Promise<{ settings: Preferences } | Failure>;
  save_fox_preference?(show: boolean): Promise<{ settings: Preferences } | Failure>;
  get_desktop_status(): Promise<{ tray_available: boolean; automatic_collection: boolean; autostart?: boolean }>;
  hide_window(): Promise<{ hidden: true } | Failure>;
  logout_institutional_access(): Promise<{ ok: true } | Failure>;
  discard_pending_collection(): Promise<Status | Failure>;
}

export function native(): Native | null {
  const api = window.pywebview?.api as unknown as Partial<Native> | undefined;
  return api && typeof api.get_collector_status === 'function' ? (api as Native) : null;
}

/** Throws the bridge's own Portuguese message on failure. */
export async function call<T>(work: (api: Native) => Promise<T | Failure>): Promise<T> {
  const api = native();
  if (!api) throw new Error('O Coletor não está disponível nesta janela.');
  const result = await work(api);
  if (result && typeof result === 'object' && 'error' in (result as object)) {
    const failure = result as Failure;
    const error = new Error(failure.error) as Error & { code?: string };
    error.code = failure.code;
    throw error;
  }
  return result as T;
}
