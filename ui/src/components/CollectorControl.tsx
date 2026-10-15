import { useEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import { Play, Pause, RefreshCw } from 'lucide-react';
import { isDesktopSettings } from '../localSettings';
import { collectorBridge, checkedCollector, COLLECTOR_STATES, COLLECTOR_CODES, type CollectorStatus, type CollectorResult } from '../collector';
import { StatusChip } from '../ui';

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
    const timer = setInterval(() => { void read(); }, 30_000);
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
  return <section className="panel source-panel" aria-labelledby="collector-title">
    <div className="section-heading"><h2 id="collector-title">Coleta da escola</h2><StatusChip tone={status?.state === 'error' ? 'warning' : 'default'}>{status ? COLLECTOR_STATES[status.state] : 'Verificando'}</StatusChip></div>
    <div className="source-actions">
      {!status?.active && <Button isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).activate_collector()); }}><Play size={16} />Ativar coleta neste computador</Button>}
      <Button isDisabled={busy || !status?.active || status.localPaused || status.settings?.paused} onPress={() => { void run(async () => (await collectorBridge()).collect_now()); }}><RefreshCw size={16} />Coletar agora</Button>
      {status?.active && <Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).pause_collector(!status.localPaused)); }}><Pause size={16} />{status.localPaused ? 'Retomar neste computador' : 'Pausar neste computador'}</Button>}
    </div>
    {status?.active && <p>{status.persistent ? 'Sessão e fila protegidas pelo Windows.' : 'Sessão e fila somente na memória deste programa.'}</p>}
    {status?.state === 'collecting' && <p role="status">{status.progress.completed} de {status.progress.total} turmas · {status.progress.classLabel ?? 'Preparando'}</p>}
    {code && <p role="status">{COLLECTOR_CODES[code] ?? 'Confira a conexão e tente novamente.'}</p>}
    {(code === 'lease-fenced' || code === 'revision-conflict') && <Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => (await collectorBridge()).discard_pending_collection()); }}>Descartar lote pendente para coletar novamente</Button>}
    {status?.lastReceipt && <p role="status">Recebido no Ecossistema em {new Date(status.lastReceipt.receivedAt).toLocaleString('pt-BR')}. {status.lastReceipt.resolvedRecords} identificados, {status.lastReceipt.unresolvedRecords} para conferir e {status.lastReceipt.conflicts} conflitos.</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
  </section>;
}
