import preset from './schedule-presets.json';

export const SCHEDULE_KEY = 'coletor-smecel.schedule-preview.v1';
export const DAYS = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo'];
export const SHIFTS = { matutino: 'Manhã', vespertino: 'Tarde' } as const;
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
  if (!value || typeof value !== 'object') return fail('Não foi possível ler os horários.');
  const c = value as SchoolSchedule;
  if (c.schemaVersion !== 1 || c.scope !== 'school' || c.storageMode !== 'local-preview' || c.sharedRevision !== null || !Number.isSafeInteger(c.localRevision) || c.localRevision < 0) return fail('Estes horários salvos não são compatíveis com esta versão.');
  if (typeof c.timezone !== 'string' || c.timezone.length > 80 || !c.timezone.includes('/')) return fail('Informe o fuso horário, por exemplo America/Bahia.');
  try { new Intl.DateTimeFormat('pt-BR', { timeZone: c.timezone }); } catch { return fail('Fuso horário não reconhecido.'); }
  if (!Array.isArray(c.rules) || c.rules.length !== 14) return fail('Confira os sete dias da semana, de manhã e à tarde.');
  const keys = new Set<string>();
  const rules = c.rules.map(r => {
    if (!r || !Number.isInteger(r.weekday) || r.weekday < 1 || r.weekday > 7 || typeof r.shift !== 'string' || !Object.hasOwn(SHIFTS, r.shift) || typeof r.selected !== 'boolean') return fail('Dia ou turno não reconhecido.');
    const key = `${r.shift}-${r.weekday}`;
    if (keys.has(key)) return fail('Dia e turno duplicados. Confira os horários salvos.');
    keys.add(key);
    const label = `${DAYS[r.weekday - 1]} / ${SHIFTS[r.shift]}`;
    if (!Array.isArray(r.times) || r.times.length > 16 || r.times.some(t => typeof t !== 'string' || !TIME.test(t))) return fail(`${label}: horário inválido.`);
    if (new Set(r.times).size !== r.times.length) return fail(`${label}: remova horários repetidos.`);
    if (typeof r.reconciliation !== 'string' || (r.reconciliation !== '' && !TIME.test(r.reconciliation))) return fail(`${label}: confira o horário da conferência final.`);
    if (r.selected && !r.times.length) return fail(`${label}: inclua ao menos um horário de coleta.`);
    if (r.reconciliation && r.times.includes(r.reconciliation)) return fail(`${label}: a conferência final não pode repetir um horário de coleta.`);
    if (r.reconciliation && r.times.some(t => t >= r.reconciliation)) return fail(`${label}: a conferência final deve ficar depois das coletas.`);
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
    if (raw.length > 16000) return fail('O arquivo de horários está grande demais.');
    return { config: validateSchedule(JSON.parse(raw)), notice: '' };
  } catch {
    return { config: defaultSchedule(), notice: 'Não foi possível ler os horários salvos. Mostramos a sugestão inicial; salvar substituirá os horários deste computador.' };
  }
}
export function saveSchedule(storage: Pick<StoragePort, 'setItem'>, config: SchoolSchedule): SchoolSchedule {
  const valid = validateSchedule({ ...config, localRevision: config.localRevision + 1 });
  storage.setItem(SCHEDULE_KEY, JSON.stringify(valid));
  return valid;
}
