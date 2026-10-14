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
export const COLLECTOR_STATES = { connect: 'Conectar', ready: 'Computador ativo', reserve: 'Reserva',
  collecting: 'Coletando frequência', paused: 'Pausado', 'login-required': 'Reconectar ao Smecel', error: 'Precisa de atenção' };
export const COLLECTOR_CODES: Record<string, string> = {
  'lease-busy': 'Outro computador está coletando. Este fica de reserva.',
  'lease-fenced': 'O computador ativo mudou. Confira a fila e faça uma nova coleta.',
  'revision-conflict': 'A revisão mudou. Confira a fila e faça uma nova coleta.',
  'SOURCE_LOGIN_REQUIRED': 'Entre novamente no Smecel e carregue as turmas.',
  'SOURCE_CLASS_UNAVAILABLE': 'Há turmas selecionadas ausentes da lista atual. Confira a lista no Smecel.',
  'SOURCE_CLASS_AMBIGUOUS': 'A turma precisa ser conferida na Importação do Ecossistema.',
  'NO_SELECTED_CLASSES': 'Entre no Smecel e selecione as turmas para este computador.',
  'PROTECTED_STORAGE_UNAVAILABLE': 'O Windows não conseguiu proteger os dados. Tente novamente.',
  'PROTECTED_STORAGE_LIMIT': 'A fila atingiu o limite. Confira a conexão e as coletas pendentes.',
  'source-invalid': 'O diário não corresponde à turma e ao ano esperados.',
  'identity-review': 'A identificação precisa ser conferida na Importação do Ecossistema.',
  unavailable: 'Confira a conexão e tente novamente.', paused: 'A coleta foi pausada para a escola.',
};
