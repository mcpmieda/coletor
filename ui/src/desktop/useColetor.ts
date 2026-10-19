import { useCallback, useEffect, useRef, useState } from 'react';
import type { HistoryEntry } from '../collector';
import { call, native, type Preferences, type Status } from './bridge';

export interface ColetorState {
  status: Status | null;
  /** True while the shown status is the local summary and the live check is pending. */
  cached: boolean;
  history: HistoryEntry[];
  prefs: Preferences | null;
  error: string;
  refresh: () => Promise<void>;
  setStatus: (status: Status) => void;
  setPrefs: (prefs: Preferences) => void;
}

/** Opens from the local snapshot at once, then keeps the live status fresh. */
export function useColetor(): ColetorState {
  const [status, setStatus] = useState<Status | null>(null);
  const [cached, setCached] = useState(true);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [error, setError] = useState('');
  const busy = useRef(false), mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (busy.current || !native()) return;
    busy.current = true;
    try {
      const [live, recent] = await Promise.all([
        call(api => api.get_collector_status()),
        call(api => api.get_collector_history()).catch(() => null),
      ]);
      if (!mounted.current) return;
      setStatus(live); setCached(false); setError('');
      if (recent) setHistory(recent.entries);
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : 'Não foi possível verificar a coleta.');
    } finally { busy.current = false; }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const api = native();
    if (api) {
      void api.get_startup_snapshot().then(snapshot => {
        if (!mounted.current) return;
        if (snapshot.status) setStatus(current => current ?? (snapshot.status as Status));
        setHistory(current => (current.length ? current : snapshot.history));
        setPrefs(current => current ?? snapshot.settings);
      }).catch(() => undefined).finally(() => { void refresh(); });
    }
    return () => { mounted.current = false; };
  }, [refresh]);

  const collecting = status?.state === 'collecting';
  useEffect(() => {
    const timer = setInterval(() => { void refresh(); }, collecting ? 5_000 : 15_000);
    return () => clearInterval(timer);
  }, [refresh, collecting]);

  return { status, cached, history, prefs, error, refresh, setStatus, setPrefs };
}
