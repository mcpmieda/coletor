import { useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { Clock3, RotateCcw, Save, Users } from 'lucide-react';
import { StatusChip } from '../ui';
import { DAYS, SHIFTS, defaultSchedule, fromDraft, readSchedule, saveSchedule, toDraft, type Shift } from '../schedule';

function initialState() {
  try { return readSchedule(window.localStorage); }
  catch { return { config: defaultSchedule(), notice: 'Armazenamento local indisponível. Você ainda pode editar a prévia.' }; }
}
export default function ScheduleSettings() {
  const [initial] = useState(initialState);
  const [saved, setSaved] = useState(initial.config);
  const [draft, setDraft] = useState(() => toDraft(initial.config));
  const [shift, setShift] = useState<Shift>('matutino');
  const [notice, setNotice] = useState(initial.notice);
  const [error, setError] = useState('');
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved));
  const selectedCount = draft.rules.filter(r => r.selected).length;
  function changeRule(day: number, field: 'selected' | 'timesText' | 'reconciliation', value: string | boolean) {
    setDraft(d => ({ ...d, rules: d.rules.map(r => r.weekday === day && r.shift === shift ? { ...r, [field]: value } : r) }));
    setNotice(''); setError('');
  }
  function save() {
    setError(''); setNotice('');
    let config;
    try { config = fromDraft(draft, saved.localRevision); }
    catch (e) { setError(e instanceof Error ? e.message : 'Revise a agenda.'); return; }
    try {
      const result = saveSchedule(window.localStorage, config);
      setSaved(result); setDraft(toDraft(result));
      setNotice('Prévia salva neste navegador. Compartilhamento entre os três usuários ainda não está ativo.');
    } catch { setError('Não foi possível salvar neste navegador. Suas alterações continuam na tela.'); }
  }
  return <div className="schedule-page">
    <section className="panel schedule-intro"><div className="section-heading"><div><h2>Uma agenda para a escola</h2><p>Os três usuários usarão a mesma configuração quando o login e a sincronização forem implementados.</p></div><Users size={22} className="muted" /></div><div className="schedule-notice"><StatusChip tone="warning">Automação inativa</StatusChip><p>Esta versão permite editar e salvar uma prévia local. Não abre o Smecel nem executa coletas. Na janela Windows privada, o rascunho pode ser descartado ao fechar.</p></div></section>
    <section className="panel schedule-editor" aria-labelledby="schedule-title"><div className="section-heading"><div><h2 id="schedule-title">Horários de coleta</h2><p>Padrão: fim de cada aula + 10 minutos e rechecagem do turno.</p></div><Clock3 size={22} className="muted" /></div>
      <div className="schedule-meta"><TextField value={draft.timezone} onChange={v => { setDraft(d => ({ ...d, timezone: v })); setError(''); setNotice(''); }}><Label>Fuso da escola</Label><Input maxLength={80} /></TextField><div><strong>Configuração escolar · versão 1</strong><p>Revisão local {saved.localRevision} · {selectedCount} dias/turnos selecionados</p><p>Compartilhamento: planejado</p></div></div>
      <div className="schedule-shifts" role="group" aria-label="Turno da agenda">{(Object.keys(SHIFTS) as Shift[]).map(s => <Button key={s} variant={s === shift ? 'primary' : 'secondary'} aria-pressed={s === shift} onPress={() => setShift(s)}>{SHIFTS[s]}</Button>)}</div>
      <p className="schedule-hint">Separe os horários por vírgulas. Dias selecionados compõem apenas o rascunho; o calendário letivo ainda será validado.</p>
      <div className="schedule-rules">{draft.rules.filter(r => r.shift === shift).map(rule => {
        const day = DAYS[rule.weekday - 1];
        return <div className={`schedule-rule${rule.selected ? '' : ' schedule-rule-off'}`} key={rule.weekday}>
          <label className="schedule-day"><input type="checkbox" checked={rule.selected} onChange={e => changeRule(rule.weekday, 'selected', e.target.checked)} aria-label={`Incluir ${day} ${SHIFTS[shift]}`} /><span>{day}</span></label>
          <TextField value={rule.timesText} onChange={v => changeRule(rule.weekday, 'timesText', v)} isDisabled={!rule.selected}><Label>Coletas</Label><Input aria-label={`Coletas ${day} ${SHIFTS[shift]}`} maxLength={150} placeholder="08:05, 09:00" /></TextField>
          <TextField value={rule.reconciliation} onChange={v => changeRule(rule.weekday, 'reconciliation', v)} isDisabled={!rule.selected}><Label>Rechecagem</Label><Input aria-label={`Rechecagem ${day} ${SHIFTS[shift]}`} maxLength={5} placeholder="HH:MM" /></TextField>
        </div>;
      })}</div>
      {error && <div className="error-message" role="alert">{error}</div>}
      {notice && <p className="schedule-feedback" role="status">{notice}</p>}
      <div className="schedule-actions"><span>{dirty ? 'Alterações ainda não salvas' : 'Prévia local · nenhuma agenda ativada'}</span><div><Button variant="ghost" isDisabled={!dirty} onPress={() => { setDraft(toDraft(saved)); setError(''); setNotice('Alterações descartadas; prévia anterior restaurada.'); }}>Descartar alterações</Button><Button variant="secondary" onPress={() => { setDraft(toDraft(defaultSchedule())); setError(''); setNotice('Padrões restaurados na tela. Salve para substituir a prévia local.'); }}><RotateCcw size={15} />Restaurar padrão</Button><Button onPress={save}><Save size={15} />Salvar prévia local</Button></div></div>
    </section>
    <p className="schedule-source">Base: HORARIO 2026.xlsb, versão 75, data interna 22/06. A vigência deve ser conferida antes da automação. Estes horários organizam coletas; não reduzem as seis posições do diário Smecel nem alteram o cálculo de faltas. Sábados letivos dependem do calendário.</p>
  </div>;
}
