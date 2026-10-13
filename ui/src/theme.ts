import { useEffect, useState } from 'react';
import { readLocalTheme, saveLocalTheme } from './localSettings';
export type ThemeMode = 'system' | 'light' | 'dark';
export function readTheme(): ThemeMode { return readLocalTheme(); }
export function paintTheme(mode: ThemeMode) {
  const dark = mode === 'dark' || (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(readTheme);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    paintTheme(mode);
    const media = matchMedia('(prefers-color-scheme: dark)');
    const listener = () => paintTheme(mode);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, [mode]);
  function change(next: ThemeMode) {
    setMode(next); setNotice('');
    void saveLocalTheme(next).catch(() => setNotice('Tema aplicado só nesta sessão. Não foi possível salvar.'));
  }
  return [mode, change, notice] as const;
}

