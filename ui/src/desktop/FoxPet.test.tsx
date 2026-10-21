import desktopApp from './DesktopApp.tsx?raw';
import foxPet from './FoxPet.tsx?raw';
import scheduleEditor from './ScheduleEditor.tsx?raw';
import settingsPage from './SettingsPage.tsx?raw';
import tasksPage from './TasksPage.tsx?raw';
import { expect, test } from 'vitest';
import { notify, onNotice, type Notice } from './foxSay';

// Every notice of the window is said by the fox (owner request 21/10/2026).
test('notices reach the fox with their kind, and stop after unsubscribing', () => {
  const heard: Notice[] = [];
  const stop = onNotice(n => heard.push(n));
  notify('Coleta iniciada');
  notify.success('Agenda salva para todos os computadores da escola');
  notify.danger('A coleta não terminou.');
  stop();
  notify('ninguém ouve');
  expect(heard).toEqual([
    { text: 'Coleta iniciada', kind: 'info' },
    { text: 'Agenda salva para todos os computadores da escola', kind: 'success' },
    { text: 'A coleta não terminou.', kind: 'danger' },
  ]);
});

test('no toast is left in the window: every page speaks through the fox', () => {
  const pages = { desktopApp, tasksPage, settingsPage, scheduleEditor };
  for (const [name, source] of Object.entries(pages)) expect(source, name).not.toMatch(/\btoast\b|Toast\./);
  expect(foxPet).toContain('onNotice(');
  expect(foxPet).toContain('role="status"');
});
