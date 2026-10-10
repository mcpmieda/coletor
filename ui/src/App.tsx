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
import FoxCompanion from './components/FoxCompanion';
export default function App() {
  const [theme, setTheme] = useTheme();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [classId, setClassId] = useState('TESTE-A');
  const [year, setYear] = useState('2026');
  const [view, setView] = useState<'preview' | 'roadmap' | 'schedule'>('preview');
  const fileRef = useRef<HTMLInputElement>(null);
  const operation = useRef(0);
  const abort = useRef<AbortController | null>(null);
  async function run(work: (signal: AbortSignal) => Promise<Preview>) {
    const id = ++operation.current;
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError(''); setPreview(null);
    try { const result = await work(controller.signal); if (operation.current === id) setPreview(result); }
    catch (e) { if (operation.current === id && !controller.signal.aborted) setError(e instanceof Error ? e.message : 'Falha ao processar o arquivo.'); }
    finally { if (operation.current === id) setBusy(false); }
  }
  function clear() { operation.current++; abort.current?.abort(); setPreview(null); setBusy(false); setError(''); if (fileRef.current) fileRef.current.value = ''; }
  function importFile(file?: File) {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { clear(); setError('O limite deste protótipo é 8 MB por arquivo.'); return; }
    if (!classId.trim() || !/^\d{4}$/.test(year)) { setError('Informe a turma e um ano com quatro dígitos.'); return; }
    void run(async signal => previewHtml(await file.text(), classId, Number(year), signal));
  }
  const states = preview?.snapshot.summary.states;
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-icon brand-fox"><img src="./mascot/head.png" alt="" width="32" height="32" /></span><div><strong>Coletor de Frequência</strong><span>Ecossistema Escolar</span></div></div>
      <nav aria-label="Navegação principal"><button className={view === 'preview' ? 'nav-item active' : 'nav-item'} aria-current={view === 'preview' ? 'page' : undefined} onClick={() => setView('preview')}><LayoutDashboard size={18} />Prévia e validação</button><button className={view === 'schedule' ? 'nav-item active' : 'nav-item'} aria-current={view === 'schedule' ? 'page' : undefined} onClick={() => setView('schedule')}><Clock3 size={18} />Agenda de coleta</button><button className={view === 'roadmap' ? 'nav-item active' : 'nav-item'} aria-current={view === 'roadmap' ? 'page' : undefined} onClick={() => setView('roadmap')}><Monitor size={18} />Próximas etapas</button></nav>
      <div className="sidebar-bottom"><FoxCompanion activity={busy ? 'reading' : error ? 'error' : preview ? 'review' : 'idle'} /><div className="sidebar-footer"><StatusChip>Protótipo local · 0.1.0</StatusChip><p>Sem conexão com a produção</p><SelectField label="Aparência" value={theme} onChange={v => setTheme(v as ThemeMode)} options={[{ id: 'system', label: 'Automática' }, { id: 'light', label: 'Clara' }, { id: 'dark', label: 'Escura' }]} /></div></div>
    </aside>
    <main><header className="page-header"><div><h1>{view === 'preview' ? 'Prévia e validação' : view === 'schedule' ? 'Agenda de coleta' : 'Próximas etapas'}</h1><p>{view === 'preview' ? 'Confira a leitura do diário antes de qualquer sincronização.' : view === 'schedule' ? 'Horários pré-configurados, com liberdade para ajustar.' : 'O que falta para uma sincronização segura nos três computadores.'}</p></div><StatusChip tone="warning">Envio desativado</StatusChip></header>
      <div hidden={view !== 'schedule'}><ScheduleSettings /></div>
      {view === 'schedule' ? null : view === 'roadmap' ? <section className="panel roadmap"><h2>Da prévia ao envio seguro</h2><ol><li><strong>Validar o diário e a identidade</strong><p>Conferir o parser com amostra autorizada e vincular cada ficha à matrícula / studentUid pela API.</p></li><li><strong>Autenticar cada serviço</strong><p>Registrar o dispositivo no Ecossistema; autenticar o Smecel em perfil Chromium exclusivo. Credenciais e acesso persistente dependem de aprovação.</p></li><li><strong>Coordenar os três computadores</strong><p>Um líder com lease e fencing na API, expiração e failover. Envios idempotentes, validados antes do PostgreSQL.</p></li><li><strong>Configurar horários e dias de coleta</strong><p>A prévia local da agenda já permite ajustar horários e dias. O compartilhamento escolar entre os três usuários será implementado após o login. O PC líder abre o navegador exclusivo, verifica a sessão, coleta e fecha. Também haverá Coletar agora, Pausar e novas tentativas espaçadas, sem coletas simultâneas. A automação ainda não está ativa.</p></li><li><strong>Mostrar a atualização no portal</strong><p>Dados limitados ao aluno autorizado, com horário da última sincronização e estado de atualização.</p></li></ol></section> : <>
        <section className="panel source-panel" aria-labelledby="source-title"><div className="section-heading"><div><h2 id="source-title">Diário anual HTML</h2><p>Importação em memória. Use a demonstração para conhecer a leitura.</p></div><FileUp size={22} className="muted" /></div>
          <div className="source-controls"><TextField value={classId} onChange={setClassId} isDisabled={busy}><Label>Identificador da turma</Label><Input /></TextField><TextField value={year} onChange={setYear} isDisabled={busy}><Label>Ano letivo</Label><Input inputMode="numeric" maxLength={4} /></TextField><div className="source-actions"><Button variant="secondary" isDisabled={busy} onPress={() => { void run(loadDemo); }}><FlaskConical size={16} />Carregar demonstração</Button><Button isDisabled={busy} onPress={() => fileRef.current?.click()}><FileUp size={16} />Abrir HTML</Button></div></div>
          <input className="sr-only" ref={fileRef} type="file" accept=".html,.htm,text/html" aria-label="Selecionar diário HTML" onChange={e => { importFile(e.target.files?.[0]); e.target.value = ''; }} />
          {busy && <div className="status-line" role="status">Validando o diário…<Button size="sm" variant="ghost" onPress={clear}>Cancelar</Button></div>}
          {error && <div className="error-message" role="alert">{error}</div>}
        </section>
        {preview ? <><div className="preview-context"><span>{preview.mode === 'demo' ? 'Demonstração com dados inteiramente sintéticos' : 'Prévia de arquivo local'} · Processado às {new Date(preview.processed_at).toLocaleTimeString('pt-BR')}</span><Button size="sm" variant="ghost" onPress={clear}><X size={14} />Limpar prévia</Button></div><div className="summary-grid"><div><span>Fichas lidas</span><strong>{preview.snapshot.students.length}</strong></div><div><span>Faltas não justificadas</span><strong>{states?.absent ?? 0}</strong></div><div><span>Previstas / sem confirmação</span><strong>{states?.planned_unknown ?? 0}</strong></div><div><span>Enviados ao Ecossistema</span><strong>0</strong></div></div><div className="content-grid"><AttendancePreview key={preview.snapshot.snapshot_id} preview={preview} /><ValidationPanel preview={preview} /></div></> : !busy && <section className="empty-state"><span className="empty-icon"><ShieldCheck size={30} /></span><h2>Primeiro, conferir. Depois, sincronizar.</h2><p>Abra um diário anual ou carregue a demonstração.<br />A prévia preserva dúvidas e aponta o que precisa de validação.</p><div className="empty-footnote">Sem coleta automática · Sem diário gravado · Sem envio</div></section>}
      </>}
    </main>
  </div>;
}
