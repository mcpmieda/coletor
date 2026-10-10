import { ShieldCheck, CircleAlert } from 'lucide-react';
import type { Preview } from '../types';
export default function ValidationPanel({ preview }: { preview: Preview }) {
  const issues = [...preview.snapshot.issues, ...preview.validation.issues].filter((issue, index, all) => all.findIndex(i => i.code === issue.code && i.message === issue.message) === index);
  return <section className="panel checks" aria-labelledby="checks-title"><h2 id="checks-title">Validação antes do envio</h2>
    <div className="check-row"><ShieldCheck size={18} /><div><strong>Arquivo processado localmente</strong><p>Nenhum dado foi enviado ao Ecossistema.</p></div></div>
    <div className="check-row"><CircleAlert size={18} /><div><strong>Presença exige confirmação</strong><p>Marcas de aula prevista continuam sem confirmação. Células vazias não viram presenças.</p></div></div>
    {issues.slice(0, 8).map((issue, i) => <div key={`${issue.code}:${i}`} className={`validation-issue ${issue.severity}`}><span className="issue-label">{issue.severity === 'error' ? 'Bloqueio' : 'Atenção'}</span><p>{issue.message}</p></div>)}
    {issues.length > 8 && <p className="muted">Mais {issues.length - 8} ocorrências. Revise a estrutura do diário antes de avançar.</p>}
    <div className="blocked-note"><strong>Envio indisponível neste protótipo</strong><p>A associação à matrícula e a aprovação da API são obrigatórias na próxima etapa.</p></div>
  </section>;
}
