import limits from '../../app/coletor/preview-limits.json';
import { version } from '../package.json';
import { useRef, useState, type ReactNode } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { FileUp, FlaskConical, LayoutDashboard, ShieldCheck, Clock3, History, Minimize2, X } from 'lucide-react';
import { loadDemo, previewHtml } from './api';
import { SelectField, StatusChip } from './ui';
import { useTheme, type ThemeMode } from './theme';
import type { Preview } from './types';
import AttendancePreview from './components/AttendancePreview';
import ValidationPanel from './components/ValidationPanel';
import ScheduleSettings from './components/ScheduleSettings';
import SharedScheduleSettings from './components/SharedScheduleSettings';
import CollectorHistory from './components/CollectorHistory';
import FoxCompanion from './components/FoxCompanion';
import { useLocalSettingsNotice, isDesktopSettings } from './localSettings';
import { useDesktopTray } from './desktop';

type View = 'preview' | 'schedule' | 'history';
const HEADERS: Record<'desktop' | 'local', Record<View, [string, string]>> = {
  desktop: {
    preview: ['Coleta da frequência', 'Envio automático da frequência do Smecel para o Ecossistema.'],
    schedule: ['Horários de coleta', 'Os mesmos horários valem para todos os computadores da escola.'],
    history: ['Histórico', 'O que este computador fez nos últimos 30 dias.'],
  },
  local: {
    preview: ['Conferir frequência', 'Veja o diário e o que precisa conferir.'],
    schedule: ['Horários de coleta', 'Escolha os dias e horários.'],
    history: ['Histórico', ''],
  },
};
function previewOrigin(mode: Preview['mode']) {
  if (mode === 'demo') return 'Dados de exemplo';
  if (mode === 'manual') return 'Leitura manual do Smecel · só para conferir';
  return 'Arquivo deste computador';
}
function NavItem({ view, current, onSelect, icon, children }: Readonly<{ view: View; current: View; onSelect: (view: View) => void; icon: ReactNode; children: ReactNode }>) {
  const active = view === current;
  return <button className={active ? 'nav-item active' : 'nav-item'} aria-current={active ? 'page' : undefined} onClick={() => onSelect(view)}>{icon}{children}</button>;
}
/** File and example tools: open in the browser preview, folded away in the Windows program. */
function ToolsPanel({ desktop, open, onToggle, children }: Readonly<{ desktop: boolean; open: boolean; onToggle: (open: boolean) => void; children: ReactNode }>) {
  if (!desktop) return <>{children}</>;
  return <details className="panel tools-panel" open={open} onToggle={event => onToggle(event.currentTarget.open)}>
    <summary>Conferir um arquivo do diário</summary>{children}
  </details>;
}

export default function App() {
  const [theme, setTheme, themeNotice] = useTheme();
  const settingsNotice = useLocalSettingsNotice();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const tray = useDesktopTray(busy ? 'reading' : error ? 'error' : 'idle');
  const [classId, setClassId] = useState('TESTE-A');
  const [year, setYear] = useState('2026');
  const [view, setView] = useState<View>('preview');
  const [toolsOpen, setToolsOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const operation = useRef(0);
  const running = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const desktop = isDesktopSettings();
  async function run(work: (signal: AbortSignal) => Promise<Preview>) {
    if (running.current) return;
    running.current = true;
    const id = ++operation.current;
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError(''); setPreview(null);
    try { const result = await work(controller.signal); if (operation.current === id) setPreview(result); }
    catch (e) { if (operation.current === id && !controller.signal.aborted) setError(e instanceof Error ? e.message : 'Não foi possível abrir o arquivo.'); }
    finally { running.current = false; setBusy(false); }
  }
  function clear() { operation.current++; setPreview(null); setError(''); if (fileRef.current) fileRef.current.value = ''; }
  function importFile(file?: File) {
    if (!file || running.current) return;
    if (file.size > limits.htmlBytes) { clear(); setError(`Arquivo com ${(file.size / 1048576).toFixed(1)} MiB; escolha um arquivo de até 24 MiB.`); return; }
    if (!classId.trim() || !/^\d{4}$/.test(year)) { setError('Preencha o código da turma e o ano com quatro números.'); return; }
    void run(async signal => previewHtml(await file.text(), classId, Number(year), signal));
  }
  const states = preview?.snapshot.summary.states;
  const [title, subtitle] = HEADERS[desktop ? 'desktop' : 'local'][view];
  let activity: 'reading' | 'error' | 'review' | 'idle' = 'idle';
  if (busy) activity = 'reading';
  else if (error) activity = 'error';
  else if (preview) activity = 'review';
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-icon brand-fox"><img src="./mascot/head.png" alt="" width="32" height="32" /></span><div><strong>Coletor de Frequência</strong><span>Ecossistema Escolar</span></div></div>
      <nav aria-label="Navegação principal">
        <NavItem view="preview" current={view} onSelect={setView} icon={<LayoutDashboard size={18} />}>{desktop ? 'Coleta' : 'Conferir frequência'}</NavItem>
        <NavItem view="schedule" current={view} onSelect={setView} icon={<Clock3 size={18} />}>Horários de coleta</NavItem>
        {desktop && <NavItem view="history" current={view} onSelect={setView} icon={<History size={18} />}>Histórico</NavItem>}
      </nav>
      <div className="sidebar-bottom"><FoxCompanion activity={activity} /><div className="sidebar-footer"><StatusChip>Versão {version}</StatusChip><SelectField label="Tema" value={theme} onChange={v => setTheme(v as ThemeMode)} options={[{ id: 'system', label: 'Automático' }, { id: 'light', label: 'Claro' }, { id: 'dark', label: 'Escuro' }]} /></div></div>
    </aside>
    <main><header className="page-header"><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{!desktop && <StatusChip tone="warning">Prévia local</StatusChip>}{tray.available && <Button size="sm" variant="secondary" onPress={() => { void tray.hide(); }}><Minimize2 size={14} />Ocultar na bandeja</Button>}</header>
      {settingsNotice && <output className="local-settings-notice">{settingsNotice}</output>}
      {themeNotice && <output>{themeNotice}</output>}
      {tray.notice && <output>{tray.notice}</output>}
      <div hidden={view !== 'schedule'}>{desktop ? <SharedScheduleSettings /> : <ScheduleSettings />}</div>
      {view === 'history' && <CollectorHistory />}
      <div className="page-stack" hidden={view !== 'preview'}>
        {view === 'preview' && <>
        <ToolsPanel desktop={desktop} open={toolsOpen || busy || !!error} onToggle={setToolsOpen}>
          <section className="panel source-panel" aria-labelledby="source-title"><div className="section-heading"><div><h2 id="source-title">Arquivo HTML ou exemplo</h2><p>Abra um diário salvo do Smecel ou use os dados de exemplo. Nada é enviado.</p></div><FileUp size={22} className="muted" /></div>
            <div className="source-controls"><TextField value={classId} onChange={setClassId} isDisabled={busy}><Label>Código da turma</Label><Input /></TextField><TextField value={year} onChange={setYear} isDisabled={busy}><Label>Ano</Label><Input inputMode="numeric" maxLength={4} /></TextField><div className="source-actions"><Button variant="secondary" isDisabled={busy} onPress={() => { void run(loadDemo); }}><FlaskConical size={16} />Usar dados de exemplo</Button><Button isDisabled={busy} onPress={() => fileRef.current?.click()}><FileUp size={16} />Abrir diário</Button></div></div>
            <input className="sr-only" ref={fileRef} type="file" accept=".html,.htm,text/html" aria-label="Selecionar arquivo do diário" onChange={e => { importFile(e.target.files?.[0]); e.target.value = ''; }} />
            {busy && <div className="status-line"><output>Lendo o diário. Descartar oculta o resultado; aguarde a leitura terminar.</output><Button size="sm" variant="ghost" onPress={clear}>Descartar resultado</Button></div>}
            {error && <div className="error-message" role="alert">{error}</div>}
          </section>
        </ToolsPanel>
        {preview && <><div className="preview-context"><span>{previewOrigin(preview.mode)} · Lido às {new Date(preview.processed_at).toLocaleTimeString('pt-BR')}</span><Button size="sm" variant="ghost" onPress={clear}><X size={14} />Fechar diário</Button></div><div className="summary-grid"><div><span>Alunos no diário</span><strong>{preview.snapshot.students.length}</strong></div><div><span>Faltas</span><strong>{states?.absent ?? 0}</strong></div><div><span>Marcações sem confirmação</span><strong>{states?.planned_unknown ?? 0}</strong></div><div><span>Dados enviados</span><strong>0</strong></div></div><div className="content-grid"><AttendancePreview key={preview.snapshot.snapshot_id} preview={preview} /><ValidationPanel preview={preview} /></div></>}
        {!preview && !busy && !desktop && <section className="empty-state"><span className="empty-icon"><ShieldCheck size={30} /></span><h2>Vamos conferir a frequência?</h2><p>Abra um diário ou use os dados de exemplo.</p><div className="empty-footnote">Seus dados não são enviados.</div></section>}
        </>}
      </div>
    </main>
  </div>;
}
