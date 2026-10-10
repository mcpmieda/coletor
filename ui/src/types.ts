export type AttendanceState = 'present' | 'absent' | 'planned_unknown' | 'unmarked' | 'unknown' | 'excused_absent' | 'non_school_day' | 'outside_enrollment';
export interface Student { source_student_ref: string; display_name: string; mat: null }
export interface AttendanceRecord { source_student_ref: string; date: string; lesson: number; state: AttendanceState; source_symbol: string }
export interface Issue { code: string; severity: 'error' | 'warning'; message: string; source_student_ref?: string; date?: string; lesson?: number }
export interface Snapshot {
  schema_version: string;
  snapshot_id: string;
  class_id: string;
  year: number;
  source_format: string;
  source_document_complete: boolean;
  source_student_refs_durable: false;
  students: Student[];
  records: AttendanceRecord[];
  issues: Issue[];
  summary: { students: number; records: number; states: Partial<Record<AttendanceState, number>>; blocking_issues: number };
}
export interface Preview { snapshot: Snapshot; validation: { allowed: boolean; issues: Issue[] }; mode: 'demo' | 'local'; processed_at: string }
export const STATE_LABELS: Record<AttendanceState, string> = { present: 'Presença marcada', absent: 'Falta marcada', planned_unknown: 'Aula prevista / sem confirmação', unmarked: 'Sem marcação', unknown: 'Marca não reconhecida', excused_absent: 'Falta justificada', non_school_day: 'Dia não letivo', outside_enrollment: 'Fora do período de matrícula' };
