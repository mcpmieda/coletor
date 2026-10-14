import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import InstitutionalAccess from './components/InstitutionalAccess';
import { paintTheme, readTheme } from './theme';
import { initializeLocalSettings } from './localSettings';
import './index.css';
async function start() {
  document.getElementById('root')!.textContent = 'Abrindo coletor…';
  const desktop = window.location.hash === '#coletor-desktop' || !!window.pywebview?.api;
  if (!desktop) await initializeLocalSettings();
  paintTheme(readTheme());
  ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode>{desktop ? <InstitutionalAccess /> : <App />}</React.StrictMode>);
}
void start();

