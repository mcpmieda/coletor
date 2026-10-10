import { useEffect, useState } from 'react';
export type ThemeMode = 'system' | 'light' | 'dark';
const key = 'smecel-collector:theme:v1';
export function readTheme(): ThemeMode {
  try { const v = localStorage.getItem(key); return v === 'light' || v === 'dark' ? v : 'system'; }
  catch { return 'system'; }
}
export function paintTheme(mode: ThemeMode) {
  const dark = mode === 'dark' || (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(readTheme);
  useEffect(() => {
    paintTheme(mode);
    try { localStorage.setItem(key, mode); } catch { /* Preference only; no student data. */ }
    const media = matchMedia('(prefers-color-scheme: dark)');
    const listener = () => paintTheme(mode);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, [mode]);
  return [mode, setMode] as const;
}
