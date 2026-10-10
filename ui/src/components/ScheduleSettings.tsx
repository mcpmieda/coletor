import { useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { Clock3, RotateCcw, Save, Users } from 'lucide-react';
import { StatusChip } from '../ui';
import { DAYS, SHIFTS, defaultSchedule, fromDraft, toDraft, type Shift } from '../schedule';

import { isDesktopSettings, readLocalSchedule, saveLocalSchedule } from '../localSettings';

function initialState() {
  try { return readLocalSchedule(); }
  catch { return { config: defaultSchedule(), notice: 'Você pode editar, mas não foi possível carregar os horários salvos.' }; }
}
export default function ScheduleSettings() {
  const [initial] = useState(initialState);
  const [saved, setSaved] = useState(initial.config);
  const [draft, setDraft] = useState(() => toDraft(initial.config));
  const [shift, setShift] = useState<Shift>('matutino');
  const [notice, setNotice] = useState(initial.notice);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved));
  const selectedCount = draft.rules.filter(r => r.selected).length;
  function changeRule(day: number, field: 'selected' | 'timesText' | 'reconciliation', value: string | boolean) {
    setDraft(d => ({ ...d, rules: d.rules.map(r => r.weekday === day && r.shift === shift ? { ...r, [field]: value } : r) }));
    setNotice(''); setError('');
  }
  async function save() {
    if (saving) return;
    setError(''); setNotice('');
    let config;
    try { config = fromDraft(draft, saved.localRevision); }
    catch (e) { setError(e instanceof Error ? e.message : 'Confira os horários.'); return; }
    setSaving(true);
    try {
      const result = await saveLocalSchedule(config);
      setSaved(result); setDraft(toDraft(result));
      setNotice('Horários salvos só neste computador.');
    } catch { setError('Não foi possível salvar. Suas alterações continuam na tela.'); }
    finally { setSaving(false); }
  }
  return <div className="schedule-page">
    <section className="panel schedule-intro"><div className="section-heading"><div><h2>Horários da escola</h2><p>Por enquanto, os horários ficam só neste computador.</p></div><Users size={22} className="muted" /></div><div className="schedule-notice"><StatusChip tone="warning">Coleta ainda indisponível</StatusChip><p>Você pode ajustar os horários. O programa ainda não abre o Smecel.</p></div></section>
    <section className="panel schedule-editor" aria-labelledby="schedule-title"><div className="section-heading"><div><h2 id="schedule-title">Dias e horários</h2><p>Já deixamos uma sugestão. Altere se precisar.</p></div><Clock3 size={22} className="muted" /></div>
      <div className="schedule-meta"><TextField isDisabled={saving} value={draft.timezone} onChange={v => { setDraft(d => ({ ...d, timezone: v })); setError(''); setNotice(''); }}><Label>Fuso horário da escola</Label><Input maxLength={80} /></TextField><div><strong>Horários deste computador</strong><p>{selectedCount} dias e turnos selecionados</p><p>Ainda não são compartilhados</p></div></div>
      <div className="schedule-shifts" role="group" aria-label="Turno">{(Object.keys(SHIFTS) as Shift[]).map(s => <Button key={s} isDisabled={saving} variant={s === shift ? 'primary' : 'secondary'} aria-pressed={s === shift} onPress={() => setShift(s)}>{SHIFTS[s]}</Button>)}</div>
      <p className="schedule-hint">Separe por vírgulas: 08:05, 09:00. Marcar um dia não confirma que haverá aula.</p>
      <div className="schedule-rules">{draft.rules.filter(r => r.shift === shift).map(rule => {
        const day = DAYS[rule.weekday - 1];
        return <div className={`schedule-rule${rule.selected ? '' : ' schedule-rule-off'}`} key={rule.weekday}>
          <label className="schedule-day"><input type="checkbox" disabled={saving} checked={rule.selected} onChange={e => changeRule(rule.weekday, 'selected', e.target.checked)} aria-label={`Incluir ${day} ${SHIFTS[shift]}`} /><span>{day}</span></label>
          <TextField value={rule.timesText} onChange={v => changeRule(rule.weekday, 'timesText', v)} isDisabled={saving || !rule.selected}><Label>Buscar frequência<span className="sr-only"> {day} {SHIFTS[shift]}</span></Label><Input maxLength={150} placeholder="08:05, 09:00" /></TextField>
          <TextField value={rule.reconciliation} onChange={v => changeRule(rule.weekday, 'reconciliation', v)} isDisabled={saving || !rule.selected}><Label>Conferir no fim<span className="sr-only"> {day} {SHIFTS[shift]}</span></Label><Input maxLength={5} placeholder="HH:MM" /></TextField>
        </div>;
      })}</div>
      {error && <div className="error-message" role="alert">{error}</div>}
      {notice && <p className="schedule-feedback" role="status">{notice}</p>}
      <div className="schedule-actions"><span>{dirty ? 'Alterações ainda não salvas' : 'Coleta automática ainda não disponível'}</span><div><Button variant="ghost" isDisabled={saving || !dirty} onPress={() => { setDraft(toDraft(saved)); setError(''); setNotice('Voltamos aos horários salvos.'); }}>Desfazer alterações</Button><Button variant="secondary" isDisabled={saving} onPress={() => { setDraft(toDraft(defaultSchedule())); setError(''); setNotice('Sugestão aplicada. Clique em Salvar horários para guardar.'); }}><RotateCcw size={15} />Usar sugestão</Button><Button isDisabled={saving} onPress={() => { void save(); }}><Save size={15} />{saving ? 'Salvando…' : 'Salvar horários'}</Button></div></div>
    </section>
    <p className="schedule-source">{isDesktopSettings() ? 'Ao salvar, os horários ficam neste computador mesmo depois de fechar o programa.' : 'Nesta prévia, os horários salvos ficam somente neste navegador.'}</p>
    <details className="schedule-source"><summary>Sobre estes horários</summary><p>Sugestão baseada no horário escolar de 22/06. Confira se ainda vale. Feriados e sábados dependem do calendário da escola.</p><p>Depois, usuários e computadores autorizados poderão usar os mesmos horários. O acesso e o compartilhamento ainda serão preparados.</p><p>Mudar horários de coleta não muda as faltas nem os dias de aula.</p></details>
  </div>;
}

