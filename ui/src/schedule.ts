import preset from './schedule-presets.json';

export const SCHEDULE_KEY = 'coletor-smecel.schedule-preview.v1';
export const DAYS = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo'];
export const SHIFTS = { matutino: 'Matutino', vespertino: 'Vespertino' } as const;
export type Shift = keyof typeof SHIFTS;
export interface ScheduleRule { weekday: number; shift: Shift; selected: boolean; times: string[]; reconciliation: string }
export interface SchoolSchedule {
  schemaVersion: 1;
  scope: 'school';
  storageMode: 'local-preview';
  localRevision: number;
  sharedRevision: null;
  timezone: string;
  rules: ScheduleRule[];
}
export interface ScheduleDraft { timezone: string; rules: (Omit<ScheduleRule, 'times'> & { timesText: string })[] }
export type StoragePort = Pick<Storage, 'getItem' | 'setItem'>;
const TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const fail = (message: string): never => { throw new Error(message); };
export function defaultSchedule(): SchoolSchedule {
  return { schemaVersion: 1, scope: 'school', storageMode: 'local-preview', localRevision: 0, sharedRevision: null, timezone: 'America/Bahia', rules: preset.rules.map(r => ({ ...r, shift: r.shift as Shift, times: [...r.times] })) };
}
export function toDraft(config: SchoolSchedule): ScheduleDraft {
  return { timezone: config.timezone, rules: config.rules.map(({ times, ...rule }) => ({ ...rule, timesText: times.join(', ') })) };
}
export function parseTimes(text: string): string[] {
  if (text.length > 150) return fail('Use até 16 horários por dia e turno.');
  if (!text.trim()) return [];
  const times = text.split(',').map(t => t.trim());
  if (times.length > 16 || times.some(t => !TIME.test(t))) return fail('Use horários de 00:00 a 23:59, separados por vírgulas.');
  if (new Set(times).size !== times.length) return fail('Remova os horários repetidos no mesmo dia e turno.');
  return times.sort();
}
export function validateSchedule(value: unknown): SchoolSchedule {
  if (!value || typeof value !== 'object') return fail('Configuração de agenda inválida.');
  const c = value as SchoolSchedule;
  if (c.schemaVersion !== 1 || c.scope !== 'school' || c.storageMode !== 'local-preview' || c.sharedRevision !== null || !Number.isSafeInteger(c.localRevision) || c.localRevision < 0) return fail('Versão ou escopo da agenda incompatível.');
  if (typeof c.timezone !== 'string' || c.timezone.length > 80 || !c.timezone.includes('/')) return fail('Informe um fuso IANA, como America/Bahia.');
  try { new Intl.DateTimeFormat('pt-BR', { timeZone: c.timezone }); } catch { return fail('Fuso horário não reconhecido.'); }
  if (!Array.isArray(c.rules) || c.rules.length !== 14) return fail('A agenda deve conter os sete dias e os dois turnos.');
  const keys = new Set<string>();
  const rules = c.rules.map(r => {
    if (!r || !Number.isInteger(r.weekday) || r.weekday < 1 || r.weekday > 7 || typeof r.shift !== 'string' || !Object.hasOwn(SHIFTS, r.shift) || typeof r.selected !== 'boolean') return fail('Dia ou turno inválido.');
    const key = `${r.shift}-${r.weekday}`;
    if (keys.has(key)) return fail('Dia e turno duplicados.');
    keys.add(key);
    const label = `${DAYS[r.weekday - 1]} / ${SHIFTS[r.shift]}`;
    if (!Array.isArray(r.times) || r.times.length > 16 || r.times.some(t => typeof t !== 'string' || !TIME.test(t))) return fail(`${label}: horário inválido.`);
    if (new Set(r.times).size !== r.times.length) return fail(`${label}: remova horários repetidos.`);
    if (typeof r.reconciliation !== 'string' || (r.reconciliation !== '' && !TIME.test(r.reconciliation))) return fail(`${label}: confira o horário da rechecagem.`);
    if (r.selected && !r.times.length) return fail(`${label}: inclua ao menos um horário de coleta.`);
    if (r.reconciliation && r.times.includes(r.reconciliation)) return fail(`${label}: a rechecagem não pode repetir um horário de coleta.`);
    if (r.reconciliation && r.times.some(t => t >= r.reconciliation)) return fail(`${label}: a rechecagem deve ficar depois das coletas.`);
    return { weekday: r.weekday, shift: r.shift, selected: r.selected, times: [...r.times].sort(), reconciliation: r.reconciliation };
  });
  // Reconstruct only the allowed fields. Never retain arbitrary imported data.
  return { schemaVersion: 1, scope: 'school', storageMode: 'local-preview', localRevision: c.localRevision, sharedRevision: null, timezone: c.timezone, rules };
}
export function fromDraft(draft: ScheduleDraft, localRevision: number): SchoolSchedule {
  return validateSchedule({ ...defaultSchedule(), localRevision, timezone: draft.timezone.trim(), rules: draft.rules.map(({ timesText, ...r }) => ({ ...r, times: parseTimes(timesText) })) });
}
export function readSchedule(storage: Pick<StoragePort, 'getItem'>): { config: SchoolSchedule; notice: string } {
  try {
    const raw = storage.getItem(SCHEDULE_KEY);
    if (raw === null) return { config: defaultSchedule(), notice: '' };
    if (raw.length > 16000) return fail('Agenda local excedeu o limite.');
    return { config: validateSchedule(JSON.parse(raw)), notice: '' };
  } catch {
    return { config: defaultSchedule(), notice: 'Não foi possível ler a agenda salva. Os padrões estão na prévia; salvar substituirá apenas a agenda local.' };
  }
}
export function saveSchedule(storage: Pick<StoragePort, 'setItem'>, config: SchoolSchedule): SchoolSchedule {
  const valid = validateSchedule({ ...config, localRevision: config.localRevision + 1 });
  storage.setItem(SCHEDULE_KEY, JSON.stringify(valid));
  return valid;
}
