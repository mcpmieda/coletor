import limits from '../../app/coletor/preview-limits.json';
import { version } from '../package.json';
import { useRef, useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { FileUp, FlaskConical, LayoutDashboard, ShieldCheck, Monitor, Clock3, X } from 'lucide-react';
import { loadDemo, previewHtml } from './api';
import { SelectField, StatusChip } from './ui';
import { useTheme, type ThemeMode } from './theme';
import type { Preview } from './types';
import AttendancePreview from './components/AttendancePreview';
import ValidationPanel from './components/ValidationPanel';
import ScheduleSettings from './components/ScheduleSettings';
import SharedScheduleSettings from './components/SharedScheduleSettings';
import CollectorControl from './components/CollectorControl';
import FoxCompanion from './components/FoxCompanion';
import ManualSource from './components/ManualSource';
import { useLocalSettingsNotice, isDesktopSettings } from './localSettings';
import { useDesktopTray } from './desktop';
export default function App() {
  const [theme, setTheme, themeNotice] = useTheme();
  const settingsNotice = useLocalSettingsNotice();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const tray = useDesktopTray(busy ? 'reading' : error ? 'error' : 'idle');
  const [classId, setClassId] = useState('TESTE-A');
  const [year, setYear] = useState('2026');
  const [view, setView] = useState<'preview' | 'roadmap' | 'schedule'>('preview');
  const fileRef = useRef<HTMLInputElement>(null);
  const operation = useRef(0);
  const running = useRef(false);
  const abort = useRef<AbortController | null>(null);
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
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-icon brand-fox"><img src="./mascot/head.png" alt="" width="32" height="32" /></span><div><strong>Coletor de Frequência</strong><span>Ecossistema Escolar</span></div></div>
      <nav aria-label="Navegação principal"><button className={view === 'preview' ? 'nav-item active' : 'nav-item'} aria-current={view === 'preview' ? 'page' : undefined} onClick={() => setView('preview')}><LayoutDashboard size={18} />Conferir frequência</button><button className={view === 'schedule' ? 'nav-item active' : 'nav-item'} aria-current={view === 'schedule' ? 'page' : undefined} onClick={() => setView('schedule')}><Clock3 size={18} />Horários de coleta</button><button className={view === 'roadmap' ? 'nav-item active' : 'nav-item'} aria-current={view === 'roadmap' ? 'page' : undefined} onClick={() => setView('roadmap')}><Monitor size={18} />Próximos passos</button></nav>
      <div className="sidebar-bottom"><FoxCompanion activity={busy ? 'reading' : error ? 'error' : preview ? 'review' : 'idle'} /><div className="sidebar-footer"><StatusChip>Versão de teste · {version}</StatusChip><p>{isDesktopSettings() ? 'Frequência da escola' : 'Prévia neste computador'}</p><SelectField label="Tema" value={theme} onChange={v => setTheme(v as ThemeMode)} options={[{ id: 'system', label: 'Automático' }, { id: 'light', label: 'Claro' }, { id: 'dark', label: 'Escuro' }]} /></div></div>
    </aside>
    <main><header className="page-header"><div><h1>{view === 'preview' ? 'Conferir frequência' : view === 'schedule' ? 'Horários de coleta' : 'Próximos passos'}</h1><p>{view === 'preview' ? 'Veja o diário e o que precisa conferir.' : view === 'schedule' ? 'Escolha os dias e horários.' : 'Como usar a coleta da escola.'}</p></div><StatusChip tone="warning">{isDesktopSettings() ? 'Coleta autorizada' : 'Prévia local'}</StatusChip></header>
      {settingsNotice && <p className="local-settings-notice" role="status">{settingsNotice}</p>}
      {themeNotice && <p role="status">{themeNotice}</p>}
      {tray.available && <div className="status-line"><Button size="sm" variant="ghost" onPress={() => { void tray.hide(); }}>Ocultar na bandeja</Button><span>Para sair, feche a janela ou use Sair na bandeja.</span></div>}
      {tray.notice && <p role="status">{tray.notice}</p>}
      <div hidden={view !== 'schedule'}>{isDesktopSettings() ? <SharedScheduleSettings /> : <ScheduleSettings />}</div>
      {view === 'schedule' ? null : view === 'roadmap' ? <section className="panel roadmap"><h2>Antes de começar</h2><ol>
        <li><strong>Conferir o diário</strong><p>Checar os alunos, as faltas e os dias de aula.</p></li>
        <li><strong>Entrar nas contas</strong><p>Entre no Ecossistema e depois no Smecel, nas janelas de cada site.</p></li>
        <li><strong>Organizar os computadores</strong><p>Um computador coleta por vez. Os demais computadores autorizados ficam de reserva.</p></li>
        <li><strong>Compartilhar os horários</strong><p>Usuários e computadores autorizados usarão os mesmos horários da escola.</p></li>
        <li><strong>Definir a tela das famílias</strong><p>O Portal mostra as marcações recebidas e indica quando a cobertura ainda está incompleta.</p></li>
      </ol><p className="muted">No programa Windows, entre nas contas, selecione as turmas e ative a coleta. Acompanhe os computadores na aba Frequência da Importação, no Ecossistema.</p></section> : <>
        <CollectorControl /><ManualSource busy={busy} onBusy={value => { running.current = value; setBusy(value); }} onRead={work => run(() => work())} onClear={clear} />
        <section className="panel source-panel" aria-labelledby="source-title"><div className="section-heading"><div><h2 id="source-title">Arquivo HTML ou exemplo</h2><p>Abra um diário do Smecel ou use os dados de exemplo.</p></div><FileUp size={22} className="muted" /></div>
          <div className="source-controls"><TextField value={classId} onChange={setClassId} isDisabled={busy}><Label>Código da turma</Label><Input /></TextField><TextField value={year} onChange={setYear} isDisabled={busy}><Label>Ano</Label><Input inputMode="numeric" maxLength={4} /></TextField><div className="source-actions"><Button variant="secondary" isDisabled={busy} onPress={() => { void run(loadDemo); }}><FlaskConical size={16} />Usar dados de exemplo</Button><Button isDisabled={busy} onPress={() => fileRef.current?.click()}><FileUp size={16} />Abrir diário</Button></div></div>
          <input className="sr-only" ref={fileRef} type="file" accept=".html,.htm,text/html" aria-label="Selecionar arquivo do diário" onChange={e => { importFile(e.target.files?.[0]); e.target.value = ''; }} />
          {busy && <div className="status-line" role="status">Lendo o diário. Descartar oculta o resultado; aguarde a leitura terminar.<Button size="sm" variant="ghost" onPress={clear}>Descartar resultado</Button></div>}
          {error && <div className="error-message" role="alert">{error}</div>}
        </section>
        {preview ? <><div className="preview-context"><span>{preview.mode === 'demo' ? 'Dados de exemplo' : preview.mode === 'manual' ? 'Leitura manual do Smecel · identidade e lista completa não verificadas' : 'Arquivo deste computador'} · Lido às {new Date(preview.processed_at).toLocaleTimeString('pt-BR')}</span><Button size="sm" variant="ghost" onPress={clear}><X size={14} />Fechar diário</Button></div><div className="summary-grid"><div><span>Alunos no diário</span><strong>{preview.snapshot.students.length}</strong></div><div><span>Faltas</span><strong>{states?.absent ?? 0}</strong></div><div><span>Marcações sem confirmação</span><strong>{states?.planned_unknown ?? 0}</strong></div><div><span>Dados enviados</span><strong>0</strong></div></div><div className="content-grid"><AttendancePreview key={preview.snapshot.snapshot_id} preview={preview} /><ValidationPanel preview={preview} /></div></> : !busy && <section className="empty-state"><span className="empty-icon"><ShieldCheck size={30} /></span><h2>Vamos conferir a frequência?</h2><p>Abra um diário ou use os dados de exemplo.</p><div className="empty-footnote">Seus dados não são enviados.</div></section>}
      </>}
    </main>
  </div>;
}

