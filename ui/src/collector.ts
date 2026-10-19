import { nativeApi } from './api';
import { defaultSchedule, fromDraft, toDraft, type ScheduleDraft } from './schedule';

// UI projection of the Ecossistema V2 contract. The native transport is the
// authority; this bridge deliberately exposes no generic operation/payload API.
export interface SharedSchedule {
  timezone: string;
  rules: { weekday: number; shift: 'matutino' | 'vespertino'; enabled: boolean; times: string[]; recheck: string | null }[];
}
export interface CollectorStatus {
  state: 'connect' | 'ready' | 'reserve' | 'collecting' | 'paused' | 'login-required' | 'error';
  code: string | null; active: boolean; localPaused: boolean; persistent: boolean;
  progress: { completed: number; total: number; classLabel: string | null };
  lastReceipt: { receivedAt: string; resolvedRecords: number; unresolvedRecords: number; conflicts: number } | null;
  settings: { revision: number; paused: boolean; schedule: SharedSchedule | null } | null;
  /** The saved Smecel login is write-only: only a masked account comes back. */
  credential?: { saved: boolean; account?: string };
  /** Classes saved for this computer (display only; collection revalidates the list). */
  selectedClasses?: number | null;
}
export interface HistoryEntry {
  at: number; kind: string; code?: string; label?: string; sent?: number; unresolved?: number; conflicts?: number;
}
/** Ready for unattended collection: a saved Smecel access and at least one class. */
export function isConfigured(status: CollectorStatus | null): boolean {
  return status?.credential?.saved === true && (status.selectedClasses ?? 0) > 0;
}
export type CollectorResult = CollectorStatus | { error: string; code?: string };
export interface CollectorBridge {
  get_collector_status(): Promise<CollectorResult>;
  activate_collector(): Promise<CollectorResult>;
  collect_now(): Promise<CollectorResult>;
  pause_collector(paused: boolean): Promise<CollectorResult>;
  save_shared_schedule(revision: number, schedule: SharedSchedule): Promise<CollectorResult>;
  pause_school_collection(revision: number, paused: boolean): Promise<CollectorResult>;
  discard_pending_collection(): Promise<CollectorResult>;
  save_source_credential(email: string, password: string): Promise<CollectorResult>;
  forget_source_credential(): Promise<CollectorResult>;
  get_collector_history(): Promise<{ entries: HistoryEntry[] } | { error: string; code?: string }>;
}
export async function collectorBridge(): Promise<CollectorBridge> {
  const api = await nativeApi();
  if (!api?.get_collector_status || !api.activate_collector || !api.collect_now || !api.save_shared_schedule)
    throw new Error('A coleta está disponível no programa Windows.');
  return api as CollectorBridge;
}
export function checkedCollector(result: CollectorResult): CollectorStatus {
  if ('error' in result) throw new Error(result.code === 'revision-conflict'
    ? 'Os horários mudaram em outro computador. Recarregue e compare antes de salvar.' : result.error);
  return result;
}
export function sharedDraft(schedule: SharedSchedule | null): ScheduleDraft {
  const base = defaultSchedule();
  if (schedule) {
    base.timezone = schedule.timezone;
    base.rules = schedule.rules.map(r => ({ weekday: r.weekday === 0 ? 7 : r.weekday, shift: r.shift,
      selected: r.enabled, times: [...r.times], reconciliation: r.recheck ?? '' }));
  }
  return toDraft(base);
}
export function sharedFromDraft(draft: ScheduleDraft): SharedSchedule {
  const value = fromDraft(draft, 0);
  if (value.rules.some(r => r.times.length + (r.reconciliation ? 1 : 0) > 48))
    throw new Error('Use até 48 coletas por dia e turno, incluindo a conferência final.');
  return { timezone: value.timezone, rules: value.rules.map(r => ({ weekday: r.weekday % 7, shift: r.shift,
    enabled: r.selected, times: r.times, recheck: r.reconciliation || null })) };
}
export const COLLECTOR_STATES = { connect: 'Desligada', ready: 'Ativa neste computador', reserve: 'Reserva',
  collecting: 'Coletando', paused: 'Pausada', 'login-required': 'Entrar no Smecel', error: 'Precisa de atenção' };
export const COLLECTOR_CODES: Record<string, string> = {
  'lease-busy': 'Outro computador está coletando. Este fica de reserva.',
  'lease-fenced': 'A coleta foi interrompida no meio (conexão lenta ou outro computador). A próxima continua sozinha.',
  'revision-conflict': 'Os dados mudaram no Ecossistema. Descarte o lote pendente para coletar de novo.',
  'SOURCE_LOGIN_REQUIRED': 'Entre no Smecel e carregue as turmas.',
  'SOURCE_LOGIN_FAILED': 'O Smecel recusou o e-mail ou a senha salvos. Confira o acesso salvo.',
  'SOURCE_READ_FAILED': 'Não foi possível ler o diário de uma turma no Smecel. A coleta tenta de novo no próximo horário.',
  'SOURCE_CLASS_UNAVAILABLE': 'Há turma escolhida fora da lista do Smecel. Carregue as turmas de novo.',
  'SOURCE_CLASS_AMBIGUOUS': 'Há turma sem ligação no Centro. Confira na Importação do Ecossistema.',
  'CLASS_RECONCILIATION_REQUIRED': 'As demais turmas foram enviadas. Há turma do Smecel sem ligação no Centro; confira a Importação.',
  'SOURCE_LIST_FILTERED': 'O Smecel mostrou a lista de turmas filtrada. As turmas visíveis foram enviadas; confira se há pesquisa ativa na lista do Smecel.',
  'CENTER_CLASSES_REQUIRED': 'Importe a Relação e o Relatório no Centro de Administração.',
  'NO_SELECTED_CLASSES': 'Entre no Smecel e marque as turmas deste computador.',
  'PROTECTED_STORAGE_UNAVAILABLE': 'O Windows não conseguiu proteger os dados. Tente novamente.',
  'PROTECTED_STORAGE_LIMIT': 'A fila de envio está cheia. Confira a conexão com a internet.',
  'source-invalid': 'O Ecossistema recusou o diário. Confira as Falhas na aba Frequência da Importação.',
  'identity-review': 'A turma precisa de ligação no Centro. Confira a aba Frequência da Importação.',
  'not-authorized': 'Acesso negado. Entre novamente no Ecossistema.',
  CLOCK_OUT_OF_SYNC: 'O relógio do Windows está diferente do horário do Ecossistema. Sincronize data e hora do PC.',
  unavailable: 'Sem conexão com o Ecossistema. A coleta tenta de novo no próximo horário.',
  paused: 'A coleta foi pausada para a escola.',
};
/** Operational history in plain words; never student names. */
export interface RunSummary { at: number; classes: number; total: number; resolved: number; unresolved: number; conflicts: number; finished: boolean }
/** The latest collection from the local history, so the summary survives a restart. */
export function lastRun(entries: readonly HistoryEntry[]): RunSummary | null {
  const sorted = [...entries].sort((a, b) => a.at - b.at);
  const start = sorted.map(entry => entry.kind).lastIndexOf('collection-started');
  if (start < 0) return null;
  const run = { at: sorted[start].at, classes: 0, total: sorted[start].sent ?? 0, resolved: 0, unresolved: 0, conflicts: 0, finished: false };
  for (const entry of sorted.slice(start + 1)) {
    if (entry.kind === 'class-sent') {
      run.classes++; run.resolved += entry.sent ?? 0; run.unresolved += entry.unresolved ?? 0; run.conflicts += entry.conflicts ?? 0; run.at = entry.at;
    } else if (entry.kind === 'collection-finished') { run.finished = true; run.at = entry.at; break; }
  }
  return run.classes ? run : null;
}
export function historyText(entry: HistoryEntry): string {
  const counts = entry.sent === undefined ? '' : ` · ${entry.sent} aluno(s) reconhecido(s)`;
  const extra = (entry.unresolved ? ` · ${entry.unresolved} não reconhecido(s)` : '')
    + (entry.conflicts ? ` · ${entry.conflicts} conflito(s)` : '');
  switch (entry.kind) {
    case 'activated': return 'Coleta ativada neste computador';
    case 'paused': return 'Coleta pausada neste computador';
    case 'resumed': return 'Coleta retomada neste computador';
    case 'collection-started': return `Coleta iniciada · ${entry.sent ?? 0} turma(s)`;
    case 'class-sent': return `${entry.label ?? 'Turma'} enviada${counts}${extra}`;
    case 'collection-finished': return 'Coleta concluída';
    case 'failure': {
      const message = COLLECTOR_CODES[entry.code ?? ''] ?? 'Falha na coleta.';
      return entry.label ? `${message} (${entry.label})` : message;
    }
    default: return 'Evento do Coletor';
  }
}
