import React from 'react';
import ReactDOM from 'react-dom/client';
import { I18nProvider } from '@heroui/react';
import InstitutionalAccess from './components/InstitutionalAccess';
import { paintTheme, readTheme } from './theme';
import { initializeLocalSettings } from './localSettings';
import './index.css';
async function start() {
  document.getElementById('root')!.textContent = 'Abrindo coletor…';
  const desktop = window.location.hash === '#coletor-desktop' || !!window.pywebview?.api;
  if (!desktop) await initializeLocalSettings();
  paintTheme(readTheme());
  // The browser preview (--preview-server) is fetched only there: the window never shows it.
  const Root = desktop ? InstitutionalAccess : (await import('./App')).default;
  // Every text is pt-BR, React Aria's own included, whatever the language of Windows.
  ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><I18nProvider locale="pt-BR"><Root /></I18nProvider></React.StrictMode>);
}
void start();
