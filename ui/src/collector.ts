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
}
export interface HistoryEntry {
  at: number; kind: string; code?: string; label?: string; sent?: number; unresolved?: number; conflicts?: number;
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
  if (value.rules.some(r => r.times.length + (r.reconciliation ? 1 : 0) > 16))
    throw new Error('Use até 16 coletas por dia e turno, incluindo a conferência final.');
  return { timezone: value.timezone, rules: value.rules.map(r => ({ weekday: r.weekday % 7, shift: r.shift,
    enabled: r.selected, times: r.times, recheck: r.reconciliation || null })) };
}
export const COLLECTOR_STATES = { connect: 'Desligada', ready: 'Ativa neste computador', reserve: 'Reserva',
  collecting: 'Coletando', paused: 'Pausada', 'login-required': 'Entrar no Smecel', error: 'Precisa de atenção' };
export const COLLECTOR_CODES: Record<string, string> = {
  'lease-busy': 'Outro computador está coletando. Este fica de reserva.',
  'lease-fenced': 'O computador ativo mudou. Descarte o lote pendente para coletar de novo.',
  'revision-conflict': 'Os dados mudaram no Ecossistema. Descarte o lote pendente para coletar de novo.',
  'SOURCE_LOGIN_REQUIRED': 'Entre no Smecel e carregue as turmas.',
  'SOURCE_LOGIN_FAILED': 'O Smecel recusou o e-mail ou a senha salvos. Confira o acesso salvo.',
  'SOURCE_CLASS_UNAVAILABLE': 'Há turma escolhida fora da lista do Smecel. Carregue as turmas de novo.',
  'SOURCE_CLASS_AMBIGUOUS': 'Há turma sem ligação no Centro. Confira na Importação do Ecossistema.',
  'CLASS_RECONCILIATION_REQUIRED': 'As demais turmas foram enviadas. Há turma do Smecel sem ligação no Centro; confira a Importação.',
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
