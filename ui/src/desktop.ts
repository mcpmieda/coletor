import { useEffect, useState } from 'react';
type DesktopActivity = 'idle' | 'reading' | 'error';
declare global { interface Window { __coletorWindowVisible?: boolean } }
/** WebView2 keeps document.hidden false when the window goes to the tray: the tray sends its own signal. */
export const windowVisible = () => !document.hidden && window.__coletorWindowVisible !== false;
/** Calls the listener whenever the window is shown or hidden; returns how to stop. */
export function onWindowVisibility(listener: () => void): () => void {
  document.addEventListener('visibilitychange', listener);
  window.addEventListener('coletorwindowvisibility', listener);
  return () => { document.removeEventListener('visibilitychange', listener); window.removeEventListener('coletorwindowvisibility', listener); };
}
/** The current time, refreshed every `ms` while the window is shown (and as soon as it is shown again). */
export function useNow(ms: number): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const tick = () => { if (windowVisible()) setNow(Date.now()); };
    const timer = setInterval(tick, ms);
    const stop = onWindowVisibility(tick);
    return () => { clearInterval(timer); stop(); };
  }, [ms]);
  return now;
}
export interface TrayBridge {
  get_desktop_status(): Promise<{ tray_available: boolean; automatic_collection: boolean; autostart?: boolean } | { error: string }>;
  hide_window(): Promise<{ hidden: true } | { error: string }>;
  set_tray_context(activity: DesktopActivity, reducedMotion: boolean): Promise<{ ok: true } | { error: string }>;
}
let contextQueue: Promise<void> = Promise.resolve();
export function syncTrayContext(api: TrayBridge, activity: DesktopActivity, reduced: boolean) {
  const pending = contextQueue.then(() => api.set_tray_context(activity, reduced));
  contextQueue = pending.then(() => {}, () => {});
  return pending;
}
/** Asks the tray to hide the window; resolves to what went wrong, when it did not. */
export async function hideInTray(api: Pick<TrayBridge, 'hide_window'>): Promise<string | undefined> {
  try { const result = await api.hide_window(); return 'error' in result ? result.error : undefined; }
  catch { return 'Não foi possível ocultar a janela.'; }
}
export function useDesktopTray(activity: DesktopActivity) {
  const [available, setAvailable] = useState(false);
  // Whether the Coletor opens with Windows (the installer's logon task): the same answer brings it.
  const [autostart, setAutostart] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const api = window.pywebview?.api;
    if (!api?.get_desktop_status) return;
    let alive = true, retry = 0;
    // A protected call: refused while the access is not confirmed (offline at opening), so asked
    // again later, though never from a window hidden in the tray.
    const again = () => { retry = window.setTimeout(() => (windowVisible() ? read() : again()), 30_000); };
    const read = () => {
      window.clearTimeout(retry);
      void api.get_desktop_status!().then(s => {
        if (!alive) return;
        if ('error' in s) { again(); return; }
        setAvailable(s.tray_available); setAutostart(s.autostart === true); setNotice(s.tray_available ? '' : 'Bandeja indisponível. Você pode fechar a janela normalmente.');
      }).catch(() => { if (alive) setNotice('Não foi possível verificar a bandeja.'); });
    };
    window.addEventListener('coletortrayready', read); read();
    return () => { alive = false; window.clearTimeout(retry); window.removeEventListener('coletortrayready', read); };
  }, []);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    // The bridge may arrive after this mounts (busy sign-in): report again when it does.
    const update = () => {
      const api = window.pywebview?.api;
      if (!api?.set_tray_context) return;
      void syncTrayContext(api as TrayBridge, activity, media.matches).catch(() => setNotice('Não foi possível atualizar o estado da bandeja.'));
    };
    update(); media.addEventListener('change', update);
    window.addEventListener('pywebviewready', update);
    window.addEventListener('coletortrayready', update);
    return () => {
      media.removeEventListener('change', update);
      window.removeEventListener('pywebviewready', update);
      window.removeEventListener('coletortrayready', update);
    };
  }, [activity]);
  async function hide() {
    const api = window.pywebview?.api;
    if (!available || !api?.hide_window) return undefined;
    const problem = await hideInTray(api as TrayBridge);
    if (problem) setNotice(problem);
    return problem;
  }
  return { available, autostart, notice, hide };
}
