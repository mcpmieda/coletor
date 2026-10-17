import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button } from '@heroui/react';
import { Play, Pause, RefreshCw } from 'lucide-react';
import { isDesktopSettings } from '../localSettings';
import { collectorBridge, checkedCollector, isConfigured, lastRun, COLLECTOR_STATES, COLLECTOR_CODES, type CollectorStatus, type CollectorResult, type RunSummary } from '../collector';
import { StatusChip } from '../ui';
import SmecelAccess from './SmecelAccess';

const when = (value: string) => new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
function tone(status: CollectorStatus | null) {
  if (status?.state === 'error' || status?.state === 'login-required') return 'warning';
  return status?.active ? 'success' : 'default';
}
export function RunFigures({ run }: Readonly<{ run: RunSummary }>) {
  return <dl className="receipt-grid" aria-label="Última coleta">
    <div><dt>Última coleta</dt><dd>{when(new Date(run.at * 1000).toISOString())}</dd></div>
    <div><dt>Turmas enviadas</dt><dd className={run.classes < run.total ? 'attention' : undefined}>{run.classes} de {run.total}</dd></div>
    <div><dt>Alunos reconhecidos</dt><dd>{run.resolved}</dd></div>
    <div><dt>Não reconhecidos</dt><dd className={run.unresolved ? 'attention' : undefined}>{run.unresolved}</dd></div>
    <div><dt>Conflitos</dt><dd className={run.conflicts ? 'attention' : undefined}>{run.conflicts}</dd></div>
  </dl>;
}

/** Collection status first; the Smecel access and class choices fold away once configured. */
export default function CollectorControl({ children }: Readonly<{ children?: ReactNode }>) {
  const [status, setStatus] = useState<CollectorStatus | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [setupOpen, setSetupOpen] = useState(false);
  const [lastCollection, setLastCollection] = useState<RunSummary | null>(null);
  const active = useRef(false), mounted = useRef(false), commandVersion = useRef(0);
  useEffect(() => {
    mounted.current = true;
    if (!isDesktopSettings()) return () => { mounted.current = false; };
    let reading = false;
    async function read() {
      if (reading || active.current) return;
      reading = true;
      const version = commandVersion.current;
      try {
        const value = checkedCollector(await (await collectorBridge()).get_collector_status());
        if (mounted.current && version === commandVersion.current && !active.current) { setStatus(value); setError(''); }
        const history = await (await collectorBridge()).get_collector_history();
        if (mounted.current && !('error' in history)) setLastCollection(lastRun(history.entries));
      } catch (e) { if (mounted.current && version === commandVersion.current && !active.current) setError(e instanceof Error ? e.message : 'Não foi possível verificar a coleta.'); }
      finally { reading = false; }
    }
    void read();
    const timer = setInterval(() => { void read(); }, 15_000);
    return () => { mounted.current = false; clearInterval(timer); };
  }, []);
  if (!isDesktopSettings()) return null;
  async function run(work: () => Promise<CollectorResult>) {
    if (active.current) return;
    active.current = true; commandVersion.current++; setBusy(true); setError('');
    try { const result = checkedCollector(await work()); if (mounted.current) setStatus(result); }
    catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'Não foi possível concluir.'); }
    finally { active.current = false; if (mounted.current) setBusy(false); }
  }
  const code = status?.code;
  const schoolPaused = status?.settings?.paused === true;
  const progress = status?.progress;
  const configured = isConfigured(status);
  const setup = <><SmecelAccess status={status} onStatus={setStatus} />{children}</>;
  return <>
    <section className="panel source-panel collector-hero" aria-labelledby="collector-title">
      <div className="section-heading"><h2 id="collector-title">Coleta da escola</h2><StatusChip tone={tone(status)}>{status ? COLLECTOR_STATES[status.state] : 'Verificando'}</StatusChip></div>
      {status?.state === 'collecting' && progress && <div className="collect-progress">
        <progress max={Math.max(progress.total, 1)} value={progress.completed} aria-label="Turmas enviadas" />
        <output>Enviando {progress.completed} de {progress.total} turma(s){progress.classLabel ? ` · ${progress.classLabel}` : ''}</output></div>}
      {lastCollection && status?.state !== 'collecting' && <RunFigures run={lastCollection} />}
      <div className="source-actions">
        {!status?.active && <Button isDisabled={busy || !configured} onPress={() => { void run(async () => (await collectorBridge()).activate_collector()); }}><Play size={16} />Ativar coleta automática</Button>}
        {status?.active && <Button isDisabled={busy || status.localPaused || schoolPaused || status.state === 'collecting'} onPress={() => { void run(async () => (await collectorBridge()).collect_now()); }}><RefreshCw size={16} />Coletar agora</Button>}
        {status?.active && <Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).pause_collector(!status.localPaused)); }}><Pause size={16} />{status.localPaused ? 'Retomar neste computador' : 'Pausar neste computador'}</Button>}
      </div>
      {!status?.active && !configured && status && <p className="muted">Salve o acesso ao Smecel e escolha as turmas abaixo para ativar a coleta automática.</p>}
      {code && <output className="collector-code">{COLLECTOR_CODES[code] ?? 'Confira a conexão e tente novamente.'}</output>}
      {(code === 'lease-fenced' || code === 'revision-conflict') && <Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).discard_pending_collection()); }}>Descartar lote pendente</Button>}
      {status?.active && !status.persistent && <p className="muted">Sem proteção do Windows: a fila fica só na memória enquanto o programa estiver aberto.</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
    </section>
    {configured ? <details className="panel tools-panel setup-panel" open={setupOpen} onToggle={event => setSetupOpen(event.currentTarget.open)}>
      <summary><span>Configuração deste computador</span><span className="muted">Acesso {status?.credential?.account} · {status?.selectedClasses} turma(s) escolhida(s)</span><span className="setup-edit">Alterar</span></summary>
      <div className="setup-stack">{setup}</div>
    </details> : setup}
  </>;
}
