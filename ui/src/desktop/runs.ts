import { COLLECTOR_CODES, type HistoryEntry } from '../collector';

export interface ClassResult { label: string; sent: number; unresolved: number; conflicts: number; readMs?: number; sendMs?: number }
export interface Run {
  id: string; started: number; finished: number | null; status: 'ok' | 'review' | 'partial' | 'stopped' | 'error' | 'running';
  total: number; classes: ClassResult[]; resolved: number; unresolved: number; conflicts: number; problem: string | null;
}

/** Collections (start → classes → finish/failure) from the local history, newest first. */
export function groupRuns(entries: readonly HistoryEntry[]): Run[] {
  const sorted = [...entries].sort((a, b) => a.at - b.at);
  const runs: Run[] = [];
  let current: Run | null = null;
  const close = (finished: number, status: Run['status'], problem: string | null) => {
    if (!current) return;
    current.finished = finished; current.problem = problem;
    // Sent but with students to reconcile is not the same as clean.
    current.status = (status === 'ok' || status === 'review') && current.classes.length < current.total ? 'partial'
      : status === 'ok' && (current.unresolved || current.conflicts) ? 'review' : status;
    runs.push(current); current = null;
  };
  for (const e of sorted) {
    if (e.kind === 'collection-started') {
      if (current) close(e.at, 'error', 'Interrompida antes de terminar.');
      current = { id: String(e.at), started: e.at, finished: null, status: 'running', total: e.sent ?? 0, classes: [], resolved: 0, unresolved: 0, conflicts: 0, problem: null };
    } else if (e.kind === 'class-sent' && current) {
      const item = { label: e.label ?? 'Turma', sent: e.sent ?? 0, unresolved: e.unresolved ?? 0, conflicts: e.conflicts ?? 0,
        readMs: (e as HistoryEntry & { readMs?: number }).readMs, sendMs: (e as HistoryEntry & { sendMs?: number }).sendMs };
      current.classes.push(item); current.resolved += item.sent; current.unresolved += item.unresolved; current.conflicts += item.conflicts;
    } else if (e.kind === 'collection-finished') close(e.at, e.code ? 'review' : 'ok', e.code ? problemText(e.code) : null);
    else if (e.kind === 'failure' && current) close(e.at, current.classes.length ? 'partial' : 'error', problemText(e.code));
    // Paused (here or by the school) or taken over by another PC: not a failure.
    else if (e.kind === 'collection-stopped' && current) close(e.at, 'stopped', problemText(e.code));
  }
  if (current) runs.push(current);
  return runs.reverse();
}

export function problemText(code?: string): string {
  return (code && COLLECTOR_CODES[code]) || 'Confira a conexão e tente novamente.';
}

export function runSummary(run: Run): string {
  if (run.status === 'running') return `Coletando · ${run.classes.length} de ${run.total} turma(s)`;
  const parts = [`${run.classes.length} de ${run.total} turma(s)`, `${run.resolved} aluno(s)`];
  if (run.unresolved) parts.push(`${run.unresolved} não reconhecido(s)`);
  if (run.conflicts) parts.push(`${run.conflicts} conflito(s)`);
  return parts.join(' · ') + (run.problem && run.status !== 'ok' ? ` · ${run.problem}` : '');
}

export type Level = 'info' | 'warn' | 'error';
export interface LogEvent { id: string; at: number; level: Level; message: string; detail?: string }

const EVENT_TEXT: Record<string, [Level, string]> = {
  activated: ['info', 'Coleta automática ativada neste computador.'],
  paused: ['warn', 'Coleta pausada neste computador.'],
  resumed: ['info', 'Coleta retomada neste computador.'],
  'collection-started': ['info', 'Coleta iniciada.'],
  'collection-finished': ['info', 'Coleta concluída.'],
  'smecel-login': ['info', 'Entrada automática no Smecel.'],
  'smecel-login-failed': ['error', 'O Smecel recusou o acesso salvo.'],
  'access-required': ['error', 'O computador precisa entrar no Ecossistema.'],
  started: ['info', 'Programa iniciado.'],
  superseded: ['warn', 'Lote interrompido substituído por uma nova leitura.'],
  'queue-quarantined': ['warn', 'Fila cifrada de um acesso anterior separada; ela não podia mais ser lida nem conferida.'],
  'queue-restored': ['info', 'Lote(s) separado(s) voltaram a ser lidos e foram devolvidos à fila para conferência.'],
  'queue-expired': ['warn', 'Lote(s) sem recibo com mais de 7 dias descartado(s) da fila local.'],
  'late-cancelled': ['info', 'Horário atrasado cancelado: ele saiu da agenda enquanto a coleta anterior rodava.'],
  'collection-stopped': ['info', 'Coleta interrompida (pausa ou outro computador assumiu).'],
  'late-start': ['info', 'Horário que chegou durante a coleta anterior: coletado logo depois, uma vez só.'],
  'login-retry': ['info', 'A sessão do Smecel expirou: o Coletor entrou de novo e leu na hora.'],
  'login-catch-up': ['info', 'Horário(s) perdido(s) esperando a entrada no Smecel: coletado logo depois, uma vez só.'],
};
const QUIET = new Set(['lease-busy', 'paused', 'CANCELLED', 'NO_CLASSES_IN_SHIFT']);
/** Short, plain cause of each failure (Registros detail), instead of the technical code. */
const FAILURE_CAUSE: Record<string, string> = {
  ACCESS_UNAVAILABLE: 'Internet ou Ecossistema fora do ar por um tempo.',
  unavailable: 'Resposta estranha do Ecossistema. Se repetir, avise o suporte.',
  'lease-fenced': 'Outro computador assumiu ou a conexão caiu no envio.',
  'revision-conflict': 'Alguém mudou dados no Ecossistema durante o envio.',
  'not-authorized': 'O acesso deste computador expirou ou foi retirado.',
  ACCESS_REQUIRED: 'Este computador precisa entrar no Ecossistema de novo.',
  SOURCE_LOGIN_REQUIRED: 'A sessão do Smecel expirou.',
  SOURCE_LOGIN_FAILED: 'E-mail ou senha do Smecel não aceitos.',
  SOURCE_READ_FAILED: 'O Smecel demorou ou falhou ao abrir um diário.',
  CLOCK_OUT_OF_SYNC: 'Data ou hora do computador erradas.',
  PROTECTED_STORAGE_UNAVAILABLE: 'O Windows não conseguiu guardar os dados com segurança.',
};
// The collector retries these by itself: worth seeing, not counted as failures.
const TEMPORARY = new Set(['ACCESS_UNAVAILABLE']);

/** One readable line per history fact, newest first (Registros). */
export function logEvents(entries: readonly HistoryEntry[]): LogEvent[] {
  return [...entries].sort((a, b) => b.at - a.at).map((e, i) => {
    const id = `${e.at}:${e.kind}:${i}`;
    if (e.kind === 'class-sent') {
      const extra = [
        e.unresolved ? `${e.unresolved} não reconhecido(s): nome sem par na Relação` : '',
        e.conflicts ? `${e.conflicts} conflito(s): marcação mudou no Smecel, decida no Centro` : '',
      ].filter(Boolean).join(' · ');
      // The same diary as last sent goes as a short message (owner request 28/10/2026: say so).
      const sent = e.unchanged ? 'sem alteração' : 'enviada';
      return { id, at: e.at, level: e.unresolved || e.conflicts ? 'warn' : 'info', message: `${e.label ?? 'Turma'} ${sent} · ${e.sent ?? 0} aluno(s)`, detail: extra || undefined };
    }
    if (e.kind === 'schedule-sent') {
      return { id, at: e.at, level: 'info', message: e.sent ? `Grade de horários enviada · ${e.sent} turma(s) com mudança` : 'Grade de horários conferida · sem alteração' };
    }
    if (e.kind === 'class-failed') {
      // The run went on with the other classes (owner request 28/10/2026).
      return { id, at: e.at, level: 'error', message: `${e.label ?? 'Turma'}: diário não lido. As outras turmas seguiram; esta é lida de novo no próximo horário.`,
        detail: e.code ? FAILURE_CAUSE[e.code] : undefined };
    }
    if (e.kind === 'unknown-mark') {
      // Logged once per mark (owner request 20/10/2026): the mark itself and where it first appeared.
      return { id, at: e.at, level: 'warn', message: `Marcação desconhecida no Smecel: ${e.code ?? '?'}`,
        detail: [e.label ? `Vista primeiro em ${e.label}` : '', 'Essa posição não entra nas contas até o coletor ser atualizado'].filter(Boolean).join(' · ') };
    }
    if (e.kind === 'failure') {
      const level: Level = QUIET.has(e.code ?? '') ? 'info' : TEMPORARY.has(e.code ?? '') ? 'warn' : 'error';
      const cause = e.code ? FAILURE_CAUSE[e.code] : undefined;
      return { id, at: e.at, level, message: problemText(e.code), detail: [e.label, cause].filter(Boolean).join(' · ') || undefined };
    }
    const [level, message] = EVENT_TEXT[e.kind] ?? ['info', e.kind];
    return { id, at: e.at, level, message, detail: e.label };
  });
}

/** Failures in the last 24 h: one rule for the Registros badge and the Tarefas tile. */
export function failures24h(entries: readonly HistoryEntry[], nowMs = Date.now()): number {
  return logEvents(entries).filter(e => e.level === 'error' && nowMs / 1000 - e.at < 86_400).length;
}

export const fmtDate = (s: number) => new Date(s * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
export function fmtDuration(start: number, end: number | null): string {
  if (end === null) return '—';
  const seconds = Math.max(0, Math.round(end - start));
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, '0')} s`;
}
export function fmtCountdown(target: Date | null, nowMs = Date.now()): string {
  if (!target) return '—';
  const s = Math.max(0, Math.round((target.getTime() - nowMs) / 1000));
  if (s >= 3600 * 24) return target.toLocaleString('pt-BR', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m}:${String(sec).padStart(2, '0')}`;
}
