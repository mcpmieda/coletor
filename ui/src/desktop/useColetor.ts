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
  const [status, setLiveStatus] = useState<Status | null>(null);
  const [cached, setCached] = useState(true);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [error, setError] = useState('');
  const busy = useRef(false), again = useRef(false), mounted = useRef(true);
  // Bumped by every status an action sets: a poll that started before it must
  // not put the older status back on screen.
  const stamp = useRef(0);
  const newest = useRef<number | null>(null);
  const setStatus = useCallback((next: Status) => { stamp.current++; setLiveStatus(next); }, []);

  const refresh = useCallback(async () => {
    if (!native()) return;
    if (busy.current) { again.current = true; return; }  // Run once more when this one ends.
    busy.current = true;
    const started = stamp.current, after = newest.current;
    try {
      const [live, recent] = await Promise.all([
        call(api => api.get_collector_status()),
        call(api => api.get_collector_history(after ?? undefined)).catch(() => null),
      ]);
      if (!mounted.current) return;
      if (stamp.current === started) setLiveStatus(live);
      setCached(false); setError('');
      if (recent) {
        // Only what is new since the last poll; the same array when nothing is.
        const fresh = after === null ? recent.entries : recent.entries.filter(e => e.at > after);
        if (fresh.length || after === null) {
          newest.current = Math.max(after ?? 0, ...fresh.map(e => e.at));
          setHistory(current => (after === null ? fresh : [...fresh, ...current].slice(0, 2000)));
        }
      }
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : 'Não foi possível verificar a coleta.');
    } finally {
      busy.current = false;
      if (again.current && mounted.current) { again.current = false; void refresh(); }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const api = native();
    if (api) {
      void api.get_startup_snapshot().then(snapshot => {
        if (!mounted.current) return;
        if (snapshot.status) setLiveStatus(current => current ?? (snapshot.status as Status));
        setHistory(current => (current.length ? current : snapshot.history));
        setPrefs(current => current ?? snapshot.settings);
      }).catch(() => undefined).finally(() => { void refresh(); });
    }
    return () => { mounted.current = false; };
  }, [refresh]);

  const collecting = status?.state === 'collecting' || status?.preparing === true;
  useEffect(() => {
    const timer = setInterval(() => { void refresh(); }, collecting ? 5_000 : 15_000);
    return () => clearInterval(timer);
  }, [refresh, collecting]);

  return { status, cached, history, prefs, error, refresh, setStatus, setPrefs };
}
