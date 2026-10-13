import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@heroui/react';
import { SelectField, StatusChip } from '../ui';
import { STATE_LABELS, type Preview } from '../types';
const PAGE_SIZE = 24;
export default function AttendancePreview({ preview }: { preview: Preview }) {
  const { snapshot } = preview;
  const [student, setStudent] = useState('all');
  const [month, setMonth] = useState('all');
  const [page, setPage] = useState(0);
  const names = useMemo(() => new Map(snapshot.students.map(s => [s.source_student_ref, s.display_name])), [snapshot]);
  const months = useMemo(() => Array.from(new Set(snapshot.records.map(r => r.date.slice(0, 7)))).sort(), [snapshot]);
  const rows = useMemo(() => snapshot.records.filter(r => (student === 'all' || r.source_student_ref === student) && (month === 'all' || r.date.startsWith(month))), [snapshot, student, month]);
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return <section className="panel preview-panel" aria-labelledby="preview-title">
    <div className="section-heading"><div><h2 id="preview-title">Prévia da turma</h2><p>{snapshot.class_id} · Ano {snapshot.year} · {snapshot.students.length} fichas</p></div><StatusChip tone="warning">Alunos a conferir</StatusChip></div>
    <div className="filters">
      <SelectField label="Aluno" value={student} onChange={v => { setStudent(v); setPage(0); }} options={[{ id: 'all', label: 'Todos os alunos' }, ...snapshot.students.map(s => ({ id: s.source_student_ref, label: s.display_name }))]} />
      <SelectField label="Mês" value={month} onChange={v => { setMonth(v); setPage(0); }} options={[{ id: 'all', label: 'Todos os meses' }, ...months.map(m => ({ id: m, label: new Intl.DateTimeFormat('pt-BR', { month: 'long', timeZone: 'UTC' }).format(new Date(m + '-01T12:00:00Z')) }))]} />
    </div>
    <div className="table-scroll"><table><caption className="sr-only">Registros do diário; os alunos e as matrículas ainda precisam de conferência</caption><thead><tr><th>Aluno no diário</th><th>Data</th><th>Posição</th><th>No diário</th></tr></thead><tbody>{visible.map(r => <tr key={`${r.source_student_ref}:${r.date}:${r.lesson}`}><td><strong>{names.get(r.source_student_ref) ?? 'Ficha sem nome'}</strong><span className="table-detail">Aluno não conferido</span></td><td className="numeric">{r.date.split('-').reverse().join('/')}</td><td className="numeric">{r.lesson}ª</td><td><span className={`state state-${r.state}`}><span className="state-dot" />{STATE_LABELS[r.state]}</span></td></tr>)}</tbody></table>{!rows.length && <p className="empty-results">Nenhum registro neste filtro.</p>}</div>
    <div className="table-footer"><span>{rows.length.toLocaleString('pt-BR')} registros · Página {page + 1} de {pages}</span><div><Button isIconOnly size="sm" variant="ghost" aria-label="Página anterior" isDisabled={page === 0} onPress={() => setPage(p => p - 1)}><ChevronLeft size={16} /></Button><Button isIconOnly size="sm" variant="ghost" aria-label="Próxima página" isDisabled={page + 1 >= pages} onPress={() => setPage(p => p + 1)}><ChevronRight size={16} /></Button></div></div>
  </section>;
}
