// UI projection of the Ecossistema V2 contract shared by the desktop panel
// (ui/src/desktop). The native transport is the authority.
export interface SharedSchedule {
  timezone: string;
  rules: { weekday: number; shift: 'matutino' | 'vespertino'; enabled: boolean; times: string[]; recheck: string | null }[];
}
export interface CollectorStatus {
  state: 'connect' | 'ready' | 'reserve' | 'collecting' | 'paused' | 'login-required' | 'error';
  code: string | null; active: boolean; localPaused: boolean; persistent: boolean;
  progress: { completed: number; total: number; classLabel: string | null };
  /** A run started and is still signing in / reading the class list: show the bar already. */
  preparing?: boolean;
  lastReceipt: { receivedAt: string; resolvedRecords: number; unresolvedRecords: number; conflicts: number } | null;
  settings: { revision: number; paused: boolean; schedule: SharedSchedule | null } | null;
  /** The saved Smecel login is write-only: only a masked account comes back. */
  credential?: { saved: boolean; account?: string };
  /** Classes saved for this computer (display only; collection revalidates the list). */
  selectedClasses?: number | null;
}
export interface HistoryEntry {
  at: number; kind: string; code?: string; label?: string; sent?: number; unresolved?: number; conflicts?: number;
  /** class-sent: the diary was the same as last sent, so only the short message went.
   *  incidents-sent: the Ecossistema already had every incident. */
  unchanged?: boolean;
}
export type CollectorResult = CollectorStatus | { error: string; code?: string };
export const COLLECTOR_CODES: Record<string, string> = {
  'lease-busy': 'Outro computador está coletando. Este fica de reserva.',
  'lease-fenced': 'A coleta foi interrompida no meio (conexão lenta ou outro computador). A próxima continua sozinha.',
  'revision-conflict': 'Os dados mudaram no Ecossistema enquanto a turma era enviada. A próxima coleta lê de novo sozinha.',
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
  ACCESS_UNAVAILABLE: 'Sem conexão com o Ecossistema. O Coletor tenta de novo sozinho.',
  NO_CLASSES_IN_SHIFT: 'Nenhuma turma deste turno para coletar.',
  unavailable: 'O Ecossistema respondeu de um jeito inesperado. A coleta tenta de novo no próximo horário; se continuar, veja Registros.',
  paused: 'A coleta foi pausada para a escola.',
};
