import { useEffect, useRef, useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { collectorBridge, checkedCollector, sharedDraft, sharedFromDraft, type CollectorStatus } from '../collector';
import { DAYS, SHIFTS, type Shift } from '../schedule';

export default function SharedScheduleSettings() {
  const [status, setStatus] = useState<CollectorStatus | null>(null);
  const [draft, setDraft] = useState(() => sharedDraft(null));
  const [shift, setShift] = useState<Shift>('matutino');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const active = useRef(false), mounted = useRef(false);
  async function reload() {
    if (active.current) return;
    active.current = true; setBusy(true); setError('');
    try {
      const value = checkedCollector(await (await collectorBridge()).get_collector_status());
      if (mounted.current) { setStatus(value); setDraft(sharedDraft(value.settings?.schedule ?? null)); setNotice(value.settings?.schedule ? 'Horários da escola carregados.' : 'Confira a sugestão e salve os horários da escola.'); }
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'Não foi possível carregar.'); }
    finally { active.current = false; if (mounted.current) setBusy(false); }
  }
  useEffect(() => { mounted.current = true; void reload(); return () => { mounted.current = false; }; }, []);
  async function save() {
    if (active.current || !status?.settings) return;
    active.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const value = checkedCollector(await (await collectorBridge()).save_shared_schedule(status.settings.revision, sharedFromDraft(draft)));
      if (mounted.current) { setStatus(value); setDraft(sharedDraft(value.settings?.schedule ?? null)); setNotice('Horários compartilhados com os computadores da escola.'); }
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'Não foi possível salvar.'); }
    finally { active.current = false; if (mounted.current) setBusy(false); }
  }
  async function pause() {
    if (active.current || !status?.settings) return;
    active.current = true; setBusy(true); setError('');
    try {
      const value = checkedCollector(await (await collectorBridge()).pause_school_collection(status.settings.revision, !status.settings.paused));
      if (mounted.current) { setStatus(value); setNotice(value.settings?.paused ? 'Coleta pausada para a escola.' : 'Coleta retomada para a escola.'); }
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'Não foi possível alterar a pausa.'); }
    finally { active.current = false; if (mounted.current) setBusy(false); }
  }
  return <section className="panel schedule-editor"><h2>Horários da escola</h2>
    <p>Estes horários são compartilhados pelos computadores autorizados.</p>
    <div className="schedule-meta"><TextField value={draft.timezone} isDisabled={busy} onChange={timezone => setDraft(value => ({ ...value, timezone }))}><Label>Fuso horário da escola</Label><Input maxLength={80} /></TextField><p>Revisão {status?.settings?.revision ?? '—'} · {status?.settings?.paused ? 'Escola pausada' : 'Escola em funcionamento'}</p></div>
    <div className="schedule-shifts" role="group" aria-label="Turno">{(Object.keys(SHIFTS) as Shift[]).map(s => <Button key={s} isDisabled={busy} variant={s === shift ? 'primary' : 'secondary'} aria-pressed={s === shift} onPress={() => setShift(s)}>{SHIFTS[s]}</Button>)}</div>
    <div className="schedule-rules">{draft.rules.filter(r => r.shift === shift).map(rule => {
      const day = DAYS[rule.weekday - 1];
      function update(field: 'selected' | 'timesText' | 'reconciliation', value: boolean | string) {
        if (active.current) return;
        setDraft(current => ({ ...current, rules: current.rules.map(r => r.weekday === rule.weekday && r.shift === shift ? { ...r, [field]: value } : r) }));
      }
      return <div className="schedule-rule" key={rule.weekday}>
        <label className="schedule-day"><input type="checkbox" disabled={busy} checked={rule.selected} onChange={event => update('selected', event.target.checked)} aria-label={`Incluir ${day} ${SHIFTS[shift]}`} />{day}</label>
        <TextField value={rule.timesText} isDisabled={busy || !rule.selected} onChange={value => update('timesText', value)}><Label>Buscar frequência<span className="sr-only"> {day} {SHIFTS[shift]}</span></Label><Input placeholder="08:05, 09:00" maxLength={150} /></TextField>
        <TextField value={rule.reconciliation} isDisabled={busy || !rule.selected} onChange={value => update('reconciliation', value)}><Label>Conferir no fim<span className="sr-only"> {day} {SHIFTS[shift]}</span></Label><Input placeholder="HH:MM" maxLength={5} /></TextField>
      </div>;
    })}</div>
    {error && <p className="error-message" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="schedule-actions"><Button variant="secondary" isDisabled={busy} onPress={() => { void reload(); }}>Recarregar e descartar alterações</Button><Button variant="secondary" isDisabled={busy} onPress={() => { setDraft(sharedDraft(null)); setNotice('Sugestão aplicada. Salve para compartilhar.'); }}>Usar sugestão</Button><Button isDisabled={busy || !status?.settings} onPress={() => { void save(); }}>Salvar horários</Button><Button variant="secondary" isDisabled={busy || !status?.settings} onPress={() => { void pause(); }}>{status?.settings?.paused ? 'Retomar para a escola' : 'Pausar para a escola'}</Button></div>
  </section>;
}
