import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Chip, ProgressBar, toast } from '@heroui/react';
import { Activity, CalendarClock, CalendarDays, KeyRound, LayoutList, Pause, Pencil, Play, RefreshCw, School, Settings, ShieldCheck } from 'lucide-react';
import { COLLECTOR_CODES } from '../collector';
import { call, type Status } from './bridge';
import { fromShared, nextSharedRun, scheduleText } from './periods';
import { failures24h, fmtCountdown, fmtDate, groupRuns, runSummary } from './runs';
import ScheduleEditor from './ScheduleEditor';
import { IconButton, Stat, StatusChip } from './ui';
import type { ColetorState } from './useColetor';

// Routine waits, never shown as a problem on this page.
const QUIET_CODES = new Set(['lease-busy', 'CANCELLED', 'NO_CLASSES_IN_SHIFT']);

export default function TasksPage({ state, onOpenSettings }: Readonly<{ state: ColetorState; onOpenSettings: () => void }>) {
  const { status, history, setStatus, refresh } = state;
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false), [starting, setStarting] = useState(false);
  const [nowMs, setNowMs] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNowMs(Date.now()), 1000); return () => clearInterval(t); }, []);

  const runs = useMemo(() => groupRuns(history), [history]);
  const last = runs.find(r => r.status !== 'running') ?? null;
  const schedule = status?.settings?.schedule ?? null;
  const draft = useMemo(() => fromShared(schedule), [schedule]);
  // From the agenda exactly as saved: per-day or per-shift times made in the
  // Ecossistema are not collapsed into the editor's summary.
  const next = status?.active && !status.localPaused && !status.settings?.paused ? nextSharedRun(schedule, new Date(nowMs)) : null;
  const errors24h = useMemo(() => failures24h(history), [history]);
  const collecting = status?.state === 'collecting';
  const credential = status?.credential?.saved === true;
  const classes = status?.classesMode === 'all' ? 'Todas' : (status?.selectedClasses ?? 0);
  const code = status?.code ?? null;

  // The collection runs for minutes inside Python: start it without holding the
  // page busy, so Pause stays available, and show what really happened at the end.
  function collectNow() {
    setStarting(true);
    toast('Coleta iniciada');
    window.setTimeout(() => { setStarting(false); void refresh(); }, 1500);
    void call(api => api.collect_now()).then(final => {
      setStatus(final);
      if (final.code && !QUIET_CODES.has(final.code)) toast.danger(COLLECTOR_CODES[final.code] ?? 'A coleta não terminou.');
    }).catch(e => { toast.danger(e instanceof Error ? e.message : 'Não foi possível coletar.'); }).finally(() => { void refresh(); });
  }

  async function act(work: Parameters<typeof call<Status>>[0], message?: string) {
    if (busy) return;
    setBusy(true);
    try { setStatus(await call(work)); if (message) toast(message); }
    catch (e) { toast.danger(e instanceof Error ? e.message : 'Não foi possível concluir.'); }
    finally { setBusy(false); void refresh(); }
  }

  return (
    <div className="flex flex-col gap-5">
      {status && !credential && (
        <Alert status="warning">
          <Alert.Indicator><KeyRound size={18} /></Alert.Indicator>
          <Alert.Content>
            <Alert.Title>Falta o acesso ao Smecel</Alert.Title>
            <Alert.Description>Salve o e-mail e a senha do Smecel para o Coletor entrar sozinho nos horários.</Alert.Description>
          </Alert.Content>
          <Button size="sm" variant="primary" className="shrink-0 self-center" onPress={onOpenSettings}><Settings size={14} /> Abrir Ajustes</Button>
        </Alert>
      )}
      {code && !collecting && !QUIET_CODES.has(code) && (
        <Alert status={code === 'paused' ? 'default' : code === 'ACCESS_UNAVAILABLE' ? 'warning' : 'danger'}>
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{COLLECTOR_CODES[code] ?? 'A última coleta não terminou. Confira a conexão.'}</Alert.Title>
            <Alert.Description>Os detalhes ficam em Registros. A próxima coleta tenta de novo sozinha.</Alert.Description>
          </Alert.Content>
          {(code === 'SOURCE_LOGIN_FAILED' || code === 'SOURCE_LOGIN_REQUIRED') && (
            <Button size="sm" variant="secondary" className="shrink-0 self-center" onPress={onOpenSettings}>Conferir acesso</Button>
          )}
        </Alert>
      )}

      <div className="grid grid-cols-4 gap-3">
        <Stat label="Turmas coletadas" value={classes} icon={<School size={20} />} />
        <Stat label="Coletando agora" value={collecting ? `${status!.progress?.completed ?? 0}/${status!.progress?.total ?? 0}` : '—'} icon={<Activity size={20} />} />
        <Stat label="Próxima coleta" value={fmtCountdown(next, nowMs)} icon={<CalendarClock size={20} />} />
        <Stat label="Falhas nas últimas 24 h" value={errors24h} icon={<ShieldCheck size={20} />} />
      </div>

      <Card className={status?.active && !status.localPaused ? '' : 'opacity-80'}>
        <Card.Content className="flex flex-col gap-3">
          <div className="flex items-start gap-4">
            <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl bg-default text-muted"><LayoutList size={20} /></div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-base font-semibold">Frequência do Smecel</span>
                {!status?.active && <Chip size="sm" variant="soft">Desligada</Chip>}
                {status?.localPaused && <Chip size="sm" variant="soft">Pausada neste computador</Chip>}
                {status?.settings?.paused && <Chip size="sm" variant="soft" color="warning">Pausada na escola</Chip>}
                {status?.state === 'reserve' && status.active && <Chip size="sm" variant="soft" color="default">Reserva</Chip>}
              </div>
              <div className="truncate text-xs text-muted">Smecel → Ecossistema · {status?.classesMode === 'chosen' ? `${classes} turma(s) escolhida(s)` : 'todas as turmas da escola'}</div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {!status?.active ? (
                <Button size="sm" variant="primary" isDisabled={busy || !credential} onPress={() => { void act(api => api.activate_collector(), 'Coleta automática ativada'); }}>
                  <Play size={14} /> Ativar
                </Button>
              ) : (
                <Button size="sm" variant="primary" isDisabled={starting || collecting || status.localPaused || !!status.settings?.paused}
                  onPress={collectNow}>
                  <RefreshCw size={14} /> {collecting ? 'Coletando…' : 'Coletar agora'}
                </Button>
              )}
              <IconButton label="Editar agenda" onPress={() => setEditing(true)} isDisabled={!status?.settings}><Pencil size={16} /></IconButton>
              {status?.active && (
                <IconButton label={status.localPaused ? 'Retomar neste computador' : 'Pausar neste computador'} isDisabled={busy}
                  onPress={() => { void act(api => api.pause_collector(!status.localPaused)); }}>
                  {status.localPaused ? <Play size={16} /> : <Pause size={16} />}
                </IconButton>
              )}
            </div>
          </div>
          {collecting ? (
            <div className="flex flex-col gap-1.5 pl-14">
              <div className="flex justify-between text-xs">
                <span className="truncate">Coletando {status!.progress?.classLabel ?? '…'}</span>
                <span className="text-muted">{status!.progress?.completed ?? 0}/{status!.progress?.total ?? 0}</span>
              </div>
              <ProgressBar aria-label="Progresso" size="sm" value={status!.progress?.total ? Math.round(((status!.progress.completed ?? 0) / status!.progress.total) * 100) : 0}>
                <ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track>
              </ProgressBar>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 pl-14 text-xs text-muted">
              <span className="flex items-center gap-1.5"><CalendarDays size={14} /> {draft.custom ? 'Agenda personalizada no Ecossistema' : scheduleText(draft)}</span>
              <span>Próxima: <span className="tabular-nums text-foreground">{fmtCountdown(next, nowMs)}</span></span>
              <span className="flex min-w-0 items-center gap-2">
                Última: <StatusChip status={last?.status} />
                {last && <span className="truncate" title={runSummary(last)}>{fmtDate(last.started)} · {runSummary(last)}</span>}
              </span>
            </div>
          )}
        </Card.Content>
      </Card>

      <ScheduleEditor open={editing} status={status} onClose={() => setEditing(false)}
        onSaved={saved => { setStatus(saved); setEditing(false); void refresh(); }} />
    </div>
  );
}
