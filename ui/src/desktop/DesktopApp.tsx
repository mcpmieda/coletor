import { useMemo, useState } from 'react';
import { Button, Chip, Spinner, Toast } from '@heroui/react';
import { History, LayoutList, Minimize2, ScrollText, Settings } from 'lucide-react';
import { version } from '../../package.json';
import { useDesktopTray } from '../desktop';
import FoxPet from './FoxPet';
import type { FoxMood } from './foxPhrases';
import { HistoryPage, LogsPage } from './HistoryPages';
import { failures24h, groupRuns, type Run } from './runs';
import SettingsPage from './SettingsPage';
import TasksPage from './TasksPage';
import { useColetor, type ColetorState } from './useColetor';

type Page = 'tasks' | 'history' | 'logs' | 'settings';
const NAV: { id: Page; label: string; icon: typeof LayoutList }[] = [
  { id: 'tasks', label: 'Tarefas', icon: LayoutList },
  { id: 'history', label: 'Histórico', icon: History },
  { id: 'logs', label: 'Registros', icon: ScrollText },
  { id: 'settings', label: 'Ajustes', icon: Settings },
];

function foxMood(state: ColetorState, runs: Run[]): FoxMood {
  const s = state.status;
  if (s?.state === 'collecting') return 'running';
  if (s?.localPaused || s?.settings?.paused) return 'paused';
  const last = runs.find(r => r.status !== 'running');
  // Only a clean run is celebrated; partial or failed runs are a problem, a run
  // with students to reconcile or a stopped one just leaves the fox calm.
  if (last && Date.now() / 1000 - (last.finished ?? last.started) < 90)
    return last.status === 'ok' ? 'ok' : last.status === 'error' || last.status === 'partial' ? 'error' : 'idle';
  if (s?.state === 'error' || s?.state === 'login-required') return 'error';
  return 'idle';
}

function ServiceLine({ state }: Readonly<{ state: ColetorState }>) {
  const s = state.status;
  const [color, text] = !s ? ['bg-default', 'Abrindo…']
    : !s.active ? ['bg-danger', 'Coleta desligada']
    : s.localPaused || s.settings?.paused ? ['bg-warning', 'Pausada']
    : s.state === 'collecting' ? ['bg-accent', 'Coletando agora']
    : s.code === 'ACCESS_UNAVAILABLE' ? ['bg-warning', 'Sem conexão, tentando de novo']
    : ['bg-success', 'Coleta automática ativa'];
  return (
    <div className="mt-2 flex items-center gap-2 px-2 text-xs text-muted">
      <span className={`size-2 rounded-full ${color}`} />
      {text}
      {state.cached && s && <span className="ml-auto flex items-center gap-1"><Spinner size="sm" /> verificando</span>}
    </div>
  );
}

export default function DesktopApp() {
  const state = useColetor();
  const [page, setPage] = useState<Page>('tasks');
  const tray = useDesktopTray(state.status?.state === 'collecting' ? 'reading' : 'idle');
  const errors24h = useMemo(() => failures24h(state.history), [state.history]);
  const runs = useMemo(() => groupRuns(state.history), [state.history]);
  const title = NAV.find(n => n.id === page)!.label;

  return (
    <div className="flex h-screen">
      <aside className="flex w-64 shrink-0 flex-col border-r border-separator bg-background-secondary px-3 py-4">
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent">
            <img src="./mascot/head.png" alt="" width={28} height={28} style={{ imageRendering: 'pixelated' }} />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold">Coletor de Frequência</span>
            <span className="text-xs text-muted">Ecossistema Escolar</span>
          </div>
        </div>
        <nav className="flex flex-col gap-1" aria-label="Navegação principal">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setPage(id)} aria-current={page === id ? 'page' : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${page === id ? 'bg-accent-soft font-medium text-accent-soft-foreground' : 'text-muted hover:bg-default hover:text-foreground'}`}>
              <Icon size={17} />
              {label}
              {id === 'logs' && errors24h > 0 && <Chip size="sm" color="danger" variant="soft" className="ml-auto">{errors24h}</Chip>}
            </button>
          ))}
        </nav>
        <div className="mt-auto shrink-0"><FoxPet mood={foxMood(state, runs)} /></div>
        <ServiceLine state={state} />
        <div className="mt-3 px-2 text-[11px] leading-snug text-muted">Versão {version}</div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between px-8 pb-4 pt-6">
          <h1 className="text-2xl font-semibold">{title}</h1>
          {tray.available && <Button size="sm" variant="secondary" onPress={() => { void tray.hide(); }}><Minimize2 size={14} /> Ocultar na bandeja</Button>}
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-8">
          {page === 'tasks' && <TasksPage state={state} onOpenSettings={() => setPage('settings')} />}
          {page === 'history' && <HistoryPage history={state.history} />}
          {page === 'logs' && <LogsPage history={state.history} />}
          {page === 'settings' && <SettingsPage state={state} version={version} />}
        </div>
      </main>
      <Toast.Provider placement="bottom end" />
    </div>
  );
}
