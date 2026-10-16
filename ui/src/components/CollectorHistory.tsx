import { useCallback, useEffect, useState } from 'react';
import { Button } from '@heroui/react';
import { RefreshCw } from 'lucide-react';
import { collectorBridge, historyText, type HistoryEntry } from '../collector';

const time = (seconds: number) => new Date(seconds * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });

/** What this computer did in the last 30 days, newest first. */
export default function CollectorHistory() {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setError('');
    try {
      const reply = await (await collectorBridge()).get_collector_history();
      if ('error' in reply) throw new Error(reply.error);
      setEntries(reply.entries);
    } catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível ler o histórico.'); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return <section className="panel source-panel" aria-labelledby="history-title">
    <div className="section-heading"><h2 id="history-title">Registros</h2><Button size="sm" variant="ghost" onPress={() => { void load(); }}><RefreshCw size={14} />Atualizar</Button></div>
    {entries?.length === 0 && <p className="muted">Nenhum registro nos últimos 30 dias.</p>}
    {entries && entries.length > 0 && <ol className="history-list">{entries.map(entry => <li key={`${entry.at}:${entry.kind}:${entry.label ?? ''}`} data-kind={entry.kind}>
      <time dateTime={new Date(entry.at * 1000).toISOString()}>{time(entry.at)}</time><span>{historyText(entry)}</span>
    </li>)}</ol>}
    {error && <p className="error-message" role="alert">{error}</p>}
  </section>;
}
