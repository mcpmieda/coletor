import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { paintTheme, readTheme } from './theme';
import { initializeLocalSettings } from './localSettings';
import './index.css';
async function start() {
  document.getElementById('root')!.textContent = 'Abrindo coletor…';
  await initializeLocalSettings();
  paintTheme(readTheme());
  ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
}
void start();

