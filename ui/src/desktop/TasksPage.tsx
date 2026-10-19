import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Chip, ProgressBar, toast } from '@heroui/react';
import { Activity, CalendarClock, CalendarDays, KeyRound, LayoutList, Pause, Pencil, Play, RefreshCw, School, Settings, ShieldCheck } from 'lucide-react';
import { COLLECTOR_CODES } from '../collector';
import { call, type Status } from './bridge';
import { fromShared, nextRun, scheduleText } from './periods';
import { fmtCountdown, fmtDate, groupRuns, runSummary } from './runs';
import ScheduleEditor from './ScheduleEditor';
import { IconButton, Stat, StatusChip } from './ui';
import type { ColetorState } from './useColetor';

export default function TasksPage({ state, onOpenSettings }: Readonly<{ state: ColetorState; onOpenSettings: () => void }>) {
  const { status, history, setStatus, refresh, error, cached } = state;
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNowMs(Date.now()), 1000); return () => clearInterval(t); }, []);

  const runs = useMemo(() => groupRuns(history), [history]);
  const last = runs.find(r => r.status !== 'running') ?? null;
  const draft = fromShared(status?.settings?.schedule ?? null);
  const next = status?.active && !status.localPaused && !status.settings?.paused ? nextRun(draft, new Date(nowMs)) : null;
  const errors24h = runs.filter(r => r.status === 'error' && nowMs / 1000 - r.started < 86_400).length;
  const collecting = status?.state === 'collecting';
  const credential = status?.credential?.saved === true;
  const classes = status?.classesMode === 'all' ? 'Todas' : (status?.selectedClasses ?? 0);
  const code = status?.code ?? null;

  async function act(work: Parameters<typeof call<Status>>[0], message?: string) {
    if (busy) return;
    setBusy(true);
    try { setStatus(await call(work)); if (message) toast(message); }
    catch (e) { toast.danger(e instanceof Error ? e.message : 'Não foi possível concluir.'); }
    finally { setBusy(false); void refresh(); }
  }

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Não deu para confirmar o estado da coleta agora</Alert.Title>
            <Alert.Description>{cached ? 'Os números abaixo são do último resumo salvo neste computador. ' : 'Os números abaixo são da última verificação. '}{error}</Alert.Description>
          </Alert.Content>
          <Button size="sm" variant="secondary" className="shrink-0 self-center" onPress={() => { void refresh(); }}><RefreshCw size={14} /> Tentar de novo</Button>
        </Alert>
      )}
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
      {code && !collecting && code !== 'lease-busy' && code !== 'CANCELLED' && (
        <Alert status={code === 'paused' ? 'default' : 'danger'}>
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
      {(last?.unresolved ?? 0) > 0 && (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{last!.unresolved} aluno(s) não reconhecido(s) na última coleta</Alert.Title>
            <Alert.Description>O nome no Smecel combina com mais de um aluno, ou com nenhum, no Ecossistema. Confira na conciliação do Centro de Administração.</Alert.Description>
          </Alert.Content>
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
                <Button size="sm" variant="primary" isDisabled={busy || collecting || status.localPaused || !!status.settings?.paused}
                  onPress={() => { void act(api => api.collect_now(), 'Coleta iniciada'); }}>
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
                <span className="truncate">Coletando {status!.progress.classLabel ?? '…'}</span>
                <span className="text-muted">{status!.progress.completed}/{status!.progress.total}</span>
              </div>
              <ProgressBar aria-label="Progresso" size="sm" value={status!.progress?.total ? Math.round(((status!.progress.completed ?? 0) / status!.progress.total) * 100) : 0}>
                <ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track>
              </ProgressBar>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 pl-14 text-xs text-muted">
              <span className="flex items-center gap-1.5"><CalendarDays size={14} /> {scheduleText(draft)}</span>
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
