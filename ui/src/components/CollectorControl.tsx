import { useEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import { Play, Pause, RefreshCw } from 'lucide-react';
import { isDesktopSettings } from '../localSettings';
import { collectorBridge, checkedCollector, COLLECTOR_STATES, COLLECTOR_CODES, type CollectorStatus, type CollectorResult } from '../collector';
import { StatusChip } from '../ui';
import SmecelAccess from './SmecelAccess';

const when = (value: string) => new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
function tone(status: CollectorStatus | null) {
  if (status?.state === 'error' || status?.state === 'login-required') return 'warning';
  return status?.active ? 'success' : 'default';
}
function receiptText(receipt: NonNullable<CollectorStatus['lastReceipt']>) {
  const parts = [`${receipt.resolvedRecords} aluno(s) reconhecido(s)`];
  if (receipt.unresolvedRecords) parts.push(`${receipt.unresolvedRecords} não reconhecido(s)`);
  if (receipt.conflicts) parts.push(`${receipt.conflicts} conflito(s)`);
  return `Último envio: ${when(receipt.receivedAt)} · ${parts.join(' · ')}`;
}

export default function CollectorControl() {
  const [status, setStatus] = useState<CollectorStatus | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
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
  return <>
    <section className="panel source-panel" aria-labelledby="collector-title">
      <div className="section-heading"><h2 id="collector-title">Coleta da escola</h2><StatusChip tone={tone(status)}>{status ? COLLECTOR_STATES[status.state] : 'Verificando'}</StatusChip></div>
      <div className="source-actions">
        {!status?.active && <Button isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).activate_collector()); }}><Play size={16} />Ativar coleta neste computador</Button>}
        <Button variant={status?.active ? 'primary' : 'secondary'} isDisabled={busy || !status?.active || status.localPaused || schoolPaused} onPress={() => { void run(async () => (await collectorBridge()).collect_now()); }}><RefreshCw size={16} />Coletar agora</Button>
        {status?.active && <Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).pause_collector(!status.localPaused)); }}><Pause size={16} />{status.localPaused ? 'Retomar neste computador' : 'Pausar neste computador'}</Button>}
      </div>
      {status?.state === 'collecting' && <output>Coletando {status.progress.completed} de {status.progress.total} turma(s){status.progress.classLabel ? ` · ${status.progress.classLabel}` : ''}</output>}
      {code && <output className="collector-code">{COLLECTOR_CODES[code] ?? 'Confira a conexão e tente novamente.'}</output>}
      {(code === 'lease-fenced' || code === 'revision-conflict') && <Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).discard_pending_collection()); }}>Descartar lote pendente</Button>}
      {status?.lastReceipt && <p className="muted">{receiptText(status.lastReceipt)}</p>}
      {status?.active && !status.persistent && <p className="muted">Sem proteção do Windows: a fila fica só na memória enquanto o programa estiver aberto.</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
    </section>
    <SmecelAccess status={status} onStatus={setStatus} />
  </>;
}
