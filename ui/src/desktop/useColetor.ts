import { useCallback, useEffect, useRef, useState } from 'react';
import { HISTORY_LIMIT, type HistoryEntry } from '../collector';
import { onWindowVisibility, windowVisible } from '../desktop';
import { call, native, type Preferences, type Status } from './bridge';

export interface ColetorState {
  status: Status | null;
  /** True while the shown status is the local summary and the live check is pending. */
  cached: boolean;
  history: HistoryEntry[];
  /** Whether a collection and a report reading were going on at the poll that brought `history`:
   *  only then is a run with no closing fact in it still going (not cut by a shutdown). */
  inProgress: { run: boolean; report: boolean };
  prefs: Preferences | null;
  error: string;
  /** The running program's version (as in the window title); null outside the desktop window. */
  version: string | null;
  refresh: () => Promise<void>;
  setStatus: (status: Status) => void;
  setPrefs: (prefs: Preferences) => void;
}

/** Whether a collection and a report reading are going on, by a status: the live one or the opening summary. */
export const inProgressOf = (status: Partial<Status> | null) =>
  ({ run: status?.state === 'collecting' || status?.preparing === true, report: status?.report?.running === true });

/** Opens from the local snapshot at once, then keeps the live status fresh. */
export function useColetor(): ColetorState {
  const [status, setLiveStatus] = useState<Status | null>(null);
  const [cached, setCached] = useState(true);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [inProgress, setInProgress] = useState({ run: false, report: false });
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [error, setError] = useState('');
  // The running program's version (startup snapshot); unknown outside the desktop window.
  const [version, setVersion] = useState<string | null>(null);
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
        const { run, report } = inProgressOf(live);
        setInProgress(current => (current.run === run && current.report === report ? current : { run, report }));
        // Only what is new since the last poll; the same array when nothing is.
        const fresh = after === null ? recent.entries : recent.entries.filter(e => e.at > after);
        if (fresh.length || after === null) {
          newest.current = Math.max(after ?? 0, ...fresh.map(e => e.at));
          setHistory(current => (after === null ? fresh : [...fresh, ...current].slice(0, HISTORY_LIMIT)));
        }
      }
    } catch (e) {
      // The check ended, without an answer: the panel says "não confirmado", not "verificando" forever.
      if (mounted.current) { setCached(false); setError(e instanceof Error ? e.message : 'Não foi possível verificar a coleta.'); }
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
        // A history that comes with the summary is read by the summary's own status, until a poll
        // brings both: a run going on at opening is not shown as cut before its end.
        if (newest.current === null) setInProgress(inProgressOf(snapshot.status));
        setHistory(current => (current.length ? current : snapshot.history));
        setPrefs(current => current ?? snapshot.settings);
        setVersion(snapshot.version);
      }).catch(() => undefined).finally(() => { void refresh(); });
    }
    return () => { mounted.current = false; };
  }, [refresh]);

  const collecting = status?.state === 'collecting' || status?.preparing === true;
  // Each refresh asks the Ecossistema: while nothing is being collected the window asks once a minute,
  // and not at all while it is hidden in the tray (ecossistema#1450, finding 7). The tray has its
  // own signal: WebView2 keeps the document "visible" there.
  useEffect(() => {
    const visible = () => { if (windowVisible()) void refresh(); };
    const timer = setInterval(visible, collecting ? 5_000 : 60_000);
    const stop = onWindowVisibility(visible);
    return () => { clearInterval(timer); stop(); };
  }, [refresh, collecting]);

  return { status, cached, history, inProgress, prefs, error, version, refresh, setStatus, setPrefs };
}
