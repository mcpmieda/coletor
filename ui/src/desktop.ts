import { useEffect, useState } from 'react';
import { isDesktopSettings } from './localSettings';
export type DesktopActivity = 'idle' | 'reading' | 'error';
declare global { interface Window { __coletorWindowVisible?: boolean } }
export interface TrayBridge {
  get_desktop_status(): Promise<{ tray_available: boolean; automatic_collection: boolean }>;
  hide_window(): Promise<{ hidden: true } | { error: string }>;
  set_tray_context(activity: DesktopActivity, reducedMotion: boolean): Promise<{ ok: true } | { error: string }>;
}
let contextQueue: Promise<void> = Promise.resolve();
export function syncTrayContext(api: TrayBridge, activity: DesktopActivity, reduced: boolean) {
  const pending = contextQueue.then(() => api.set_tray_context(activity, reduced));
  contextQueue = pending.then(() => {}, () => {});
  return pending;
}
export function useDesktopTray(activity: DesktopActivity) {
  const [available, setAvailable] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!isDesktopSettings()) return;
    const api = window.pywebview?.api;
    if (!api?.get_desktop_status) return;
    let alive = true;
    const read = () => { void api.get_desktop_status!().then(s => { if (alive) { setAvailable(s.tray_available); setNotice(s.tray_available ? '' : 'Bandeja indisponível. Você pode fechar a janela normalmente.'); } }).catch(() => { if (alive) setNotice('Não foi possível verificar a bandeja.'); }); };
    window.addEventListener('coletortrayready', read); read();
    return () => { alive = false; window.removeEventListener('coletortrayready', read); };
  }, []);
  useEffect(() => {
    if (!isDesktopSettings()) return;
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
    if (!available || !api?.hide_window) return;
    try { const result = await api.hide_window(); if ('error' in result) setNotice(result.error); }
    catch { setNotice('Não foi possível ocultar a janela.'); }
  }
  return { available, notice, hide };
}
