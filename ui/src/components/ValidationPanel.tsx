import { ShieldCheck, CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { collectDiagnostics, groupDiagnostics } from '../diagnostics';
import type { Preview } from '../types';

// Keep the source diagnostics intact; only the wording shown first is simplified.
const ISSUE_LABELS: Record<string, string> = {
  EXPECTED_SCOPE_INVALID: 'Confira a turma e o ano informados.',
  DOCUMENT_EMPTY: 'O arquivo está vazio.',
  DOCUMENT_TOO_LARGE: 'O arquivo é grande demais para ser lido.',
  DOCUMENT_MALFORMED: 'O arquivo está incompleto ou não pôde ser lido.',
  LOGIN_PAGE: 'O arquivo mostra a tela de entrada, não o diário.',
  REPORT_STRUCTURE_UNSUPPORTED: 'Não foi possível reconhecer o diário anual.',
  REPORT_VOLUME_EXCEEDED: 'Há dados demais neste arquivo. A prévia foi descartada.',
  SYNTHETIC_DATA: 'Este exemplo usa alunos fictícios.',
  SYNTHETIC_TRANSMISSION_FORBIDDEN: 'Dados de exemplo não podem ser enviados.',
  ROSTER_EMPTY: 'Não foram encontradas fichas de alunos.',
  ROSTER_INCOMPLETE: 'A quantidade de fichas não confere.',
  ROSTER_COMPLETENESS_UNVERIFIED: 'Não foi possível confirmar se todos os alunos estão no arquivo.',
  CLASS_ID_UNVERIFIED: 'Não foi possível confirmar a turma do arquivo.',
  CLASS_MISMATCH: 'A turma do arquivo não confere com a informada.',
  YEAR_MISMATCH: 'O ano do diário está ausente ou não confere.',
  REPORT_END_MISSING: 'Não foi possível confirmar se o diário está completo.',
  DOCUMENT_INCOMPLETE: 'Não foi possível confirmar se o diário está completo.',
  DUPLICATE_STUDENT_ROW: 'Há uma ficha repetida ou com identificação inválida.',
  STUDENT_ROW_INVALID: 'Há uma ficha repetida ou com identificação inválida.',
  STUDENT_HEADER_INVALID: 'Os dados no início de uma ficha não foram reconhecidos.',
  STUDENT_NAME_TOO_LONG: 'Há texto demais no início de uma ficha.',
  STUDENT_NAME_MISSING: 'Uma ficha está sem o nome do aluno.',
  ANNUAL_TABLE_INVALID: 'Não foi possível reconhecer a tabela anual de uma ficha.',
  GRID_COVERAGE_INVALID: 'A tabela do diário está incompleta ou fora da ordem esperada.',
  MONTH_COVERAGE_INVALID: 'Confira os meses de fevereiro a dezembro e o ano do diário.',
  LESSON_HEADER_INVALID: 'As aulas de 1 a 6 estão incompletas ou fora de ordem.',
  TOTALS_ROW_INVALID: 'O total de faltas por mês está ausente ou incompleto.',
  LEGEND_UNVERIFIED: 'A legenda das marcações não foi reconhecida.',
  DUPLICATE_CARD_CONTENT: 'Duas fichas têm o mesmo conteúdo. Confira o arquivo.',
  SOURCE_SYMBOL_TOO_LONG: 'Uma aula contém uma marcação inesperada.',
  SOURCE_SYMBOL_UNKNOWN: 'Há uma marcação que não foi reconhecida.',
  DUPLICATE_RECORD: 'Há uma aula repetida para a mesma ficha e data.',
  INVALID_DATE_MARKED: 'Há uma marcação em uma data que não existe.',
  SNAPSHOT_SCHEMA_UNSUPPORTED: 'Esta versão da prévia não é aceita.',
  SNAPSHOT_CHANGED: 'Os dados mudaram após a leitura. Abra o arquivo novamente.',
  IDENTITY_UNSAFE: 'A posição da ficha não identifica o aluno com segurança.',
  STUDENT_REFS_INVALID: 'Há fichas sem identificação ou com identificação repetida.',
  SNAPSHOT_SUMMARY_INVALID: 'Os totais não conferem com os registros lidos.',
  RECORD_STUDENT_UNKNOWN: 'Há uma aula ligada a uma ficha que não foi encontrada.',
  RECORD_POSITION_INVALID: 'Há uma data ou um número de aula inválido.',
  API_MAPPING_SCOPE_MISMATCH: 'A conferência dos alunos pertence a outra leitura, turma ou ano.',
  API_MAPPING_INCOMPLETE: 'Cada ficha precisa ser conferida uma única vez.',
  API_MAPPING_UID_INVALID: 'A identificação de um aluno é inválida.',
  API_MAPPING_DUPLICATE_UID: 'Duas fichas estão ligadas ao mesmo aluno.',
  ATTENDANCE_UNRESOLVED: 'Há marcações que precisam de conferência.',
  EXCUSED_ABSENCE_API_MAPPING_REQUIRED: 'Ainda falta definir como o Ecossistema receberá as faltas justificadas.',
  ATTENDANCE_STATE_INVALID: 'Há um registro de frequência inválido.',
};

export default function ValidationPanel({ preview }: { preview: Preview }) {
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const issues = collectDiagnostics(preview.snapshot.issues, preview.validation.issues);
  const extraIssues = groupDiagnostics(issues.filter(issue => !['SOURCE_SYMBOL_AMBIGUOUS', 'API_MAPPING_REQUIRED', 'TRANSMISSION_DISABLED', 'SOURCE_PROVENANCE_REQUIRED'].includes(issue.code)));
  const filtered = issues.filter(issue => !filter || issue.code === filter);
  const pages = Math.max(1, Math.ceil(filtered.length / 20));
  const current = Math.min(page, pages - 1);
  const details = filtered.slice(current * 20, (current + 1) * 20);
  return <section className="panel checks" aria-labelledby="checks-title"><h2 id="checks-title">O que conferir</h2>
    <div className="check-row"><ShieldCheck size={18} /><div><strong>Nenhum dado foi enviado</strong><p>Esta é uma prévia neste computador.</p></div></div>
    <div className="check-row"><CircleAlert size={18} /><div><strong>• não confirma presença</strong><p>Os alunos, as matrículas e o calendário ainda precisam de conferência.</p></div></div>
    {extraIssues.map(({ issue, diagnostics, cards }) => <div key={`${issue.severity}:${issue.code}`} className={`validation-issue ${issue.severity}`}><span className="issue-label">{issue.severity === 'error' ? 'Atenção' : 'Aviso'}</span><p>{ISSUE_LABELS[issue.code] ?? 'Este aviso precisa de conferência. Veja os detalhes.'}</p><small>{diagnostics} diagnósticos · {cards.size} fichas identificadas</small></div>)}
    {issues.length > 0 && <details className="validation-issue"><summary>Ver detalhes ({issues.length} diagnósticos)</summary>
      <p>Marcações repetidas na mesma ficha são agrupadas pelo leitor. A localização abaixo é a primeira registrada.</p>
      <label>Filtrar código <select value={filter} onChange={e => { setFilter(e.target.value); setPage(0); }}><option value="">Todos</option>{[...new Set(issues.map(i => i.code))].map(code => <option key={code}>{code}</option>)}</select></label>
      {details.map((issue, i) => <p key={`${issue.code}:${current}:${i}`}><strong>{issue.code}</strong> · {issue.source_student_ref ?? 'Documento'}{issue.date ? ` · ${issue.date}` : ''}{issue.lesson ? ` · posição ${issue.lesson}` : ''}<br />{issue.message}</p>)}
      <div><button disabled={current === 0} onClick={() => setPage(current - 1)}>Anterior</button><span> Página {current + 1} de {pages} </span><button disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Próxima</button></div>
    </details>}
    <div className="blocked-note"><strong>Envio desativado</strong><p>Esta versão não está conectada ao Ecossistema.</p></div>
  </section>;
}
