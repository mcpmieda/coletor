import { useState } from 'react';
import { Alert, Button, Checkbox, ListBox, Label, Modal, Select, ToggleButton, ToggleButtonGroup } from '@heroui/react';
import { notify } from './foxSay';
import { Save } from 'lucide-react';
import type { HistoryEntry, SharedSchedule } from '../collector';
import { frequencyMinutes, reportClash, reportMinutes } from './reportPlan';
import { call, type Status } from './bridge';
import { DAY_LETTERS, DAY_NAMES, MAX_EVERY_MINUTES, MIN_GAP_MINUTES, cloneSchedule, draftProblem, draftSignature, editorDay, fromShared, sharedScheduleProblem, timezoneProblem, toShared, type PeriodDraft } from './periods';
import { NumberInput, Section, SwitchRow, TextInput, TimeInput, TimeValidationContext, useIncompleteTimes } from './ui';
import TimeRows from './TimeRows';

const MODES: { id: PeriodDraft['mode']; label: string }[] = [
  { id: 'interval', label: 'Em intervalos' }, { id: 'times', label: 'Em horários fixos' }, { id: 'off', label: 'Somente manual' },
];
const sameSchedule = (a: SharedSchedule | null, b: SharedSchedule) => a !== null && a.timezone === b.timezone && a.rules.length === b.rules.length &&
  a.rules.every(rule => { const other = b.rules.find(r => r.weekday === rule.weekday && r.shift === rule.shift);
    return other && other.enabled === rule.enabled && other.recheck === rule.recheck && JSON.stringify(other.times) === JSON.stringify(rule.times); });

/** Mounted while open: it edits the agenda as saved at that moment, whatever a later poll brings. */
export default function ScheduleEditor({ status, history = [], onClose, onSaved }: Readonly<{
  status: Status | null; history?: readonly HistoryEntry[]; onClose: () => void; onSaved: (status: Status) => void;
}>) {
  const [opened] = useState(() => {
    const original = status?.settings?.schedule ?? null, draft = fromShared(original);
    return { draft, source: original ? cloneSchedule(original) : null, rules: original ? cloneSchedule(original) : toShared(draft),
      revision: status?.settings?.revision ?? null };
  });
  const { source, revision: baseRevision } = opened;
  const [draft, setDraft] = useState(opened.draft);
  const [rulesDraft, setRulesDraft] = useState(opened.rules);
  const [perRule, setPerRule] = useState(opened.draft.custom), [ruleIndex, setRuleIndex] = useState(0);
  const [zoneConfirmed, setZoneConfirmed] = useState(false);
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  const [incomplete, reportTime] = useIncompleteTimes();
  const set = (patch: Partial<PeriodDraft>) => setDraft(d => ({ ...d, ...patch }));
  const candidate = perRule ? { ...rulesDraft, timezone: draft.timezone } : toShared(draft);
  const unchanged = sameSchedule(source, candidate);
  const zoneChanged = !!source && source.timezone !== draft.timezone;
  const problem = incomplete ? 'Preencha ou remova o horário incompleto.' :
    unchanged && (perRule || draft.initial === draftSignature(draft)) ? null :
      (perRule ? sharedScheduleProblem(candidate) : draftProblem(draft))
      // Never together with the student report (owner decision 29/10/2026), by the real run lengths.
      ?? reportClash(status?.settings?.reportSchedule, candidate, reportMinutes(history), frequencyMinutes(history));
  const blocked = !!problem || (zoneChanged && !zoneConfirmed) || baseRevision === null;
  const perDay = Math.max(...Array.from({ length: 7 }, (_, weekday) => new Set(candidate.rules.filter(r => r.enabled && r.weekday === weekday).flatMap(r => [...r.times, ...(r.recheck ? [r.recheck] : [])])).size));
  const rule = rulesDraft.rules[ruleIndex];
  const setRule = (patch: Partial<SharedSchedule['rules'][number]>) => setRulesDraft(schedule => ({ ...schedule,
    rules: schedule.rules.map((r, index) => index === ruleIndex ? { ...r, ...patch } : r) }));
  let localTime = '';
  if (!timezoneProblem(draft.timezone)) localTime = new Intl.DateTimeFormat('pt-BR', { timeZone: draft.timezone, hour: '2-digit', minute: '2-digit' }).format(new Date());

  async function save() {
    if (blocked || baseRevision === null) return;
    if (unchanged) { onClose(); return; }
    setSaving(true); setError('');
    try {
      const saved = await call(api => api.save_shared_schedule(baseRevision, candidate));
      notify.success('Agenda salva para todos os computadores da escola'); onSaved(saved);
    } catch (e) {
      const code = (e as Error & { code?: string }).code;
      setError(code === 'revision-conflict' ? 'A agenda mudou em outro computador. Feche e abra de novo para ver a versão atual.' : (e instanceof Error ? e.message : 'Não foi possível salvar.'));
    } finally { setSaving(false); }
  }
  return <TimeValidationContext.Provider value={reportTime}><Modal.Backdrop isOpen onOpenChange={v => !v && !saving && onClose()} variant="blur">
    <Modal.Container size="lg" scroll="inside"><Modal.Dialog className="max-h-[88vh]">
      <Modal.Header><Modal.Heading>Agenda de coleta</Modal.Heading>
        <p className="text-sm text-muted">Vale para todos os computadores da escola. Revisão {baseRevision ?? 'indisponível'}.</p></Modal.Header>
      <Modal.Body className="flex flex-col gap-6 pb-2">
        <Section title="Fuso horário">
          <TextInput label="Fuso horário" value={draft.timezone} onChange={value => { set({ timezone: value }); setZoneConfirmed(false); }} placeholder="America/Bahia" />
          {localTime && <span className="text-xs text-muted">Hora da escola: {localTime}</span>}
          {zoneChanged && <Checkbox isSelected={zoneConfirmed} onChange={setZoneConfirmed}>
            <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><Checkbox.Content>Confirmo a alteração do fuso e dos horários de execução.</Checkbox.Content>
          </Checkbox>}
        </Section>
        {perRule ? <>
          <Section title="Dia e turno">
            <Select fullWidth value={String(ruleIndex)} onChange={key => key != null && setRuleIndex(Number(key))}>
              <Label>Dia e turno</Label><Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
              <Select.Popover><ListBox>{rulesDraft.rules.map((r, index) => <ListBox.Item key={String(index)} id={String(index)}
                textValue={`${DAY_NAMES[editorDay(r.weekday)]} · ${r.shift === 'matutino' ? 'Matutino' : 'Vespertino'}`}>
                {DAY_NAMES[editorDay(r.weekday)]} · {r.shift === 'matutino' ? 'Matutino' : 'Vespertino'}<ListBox.ItemIndicator />
              </ListBox.Item>)}</ListBox></Select.Popover>
            </Select>
            <SwitchRow label="Coletas automáticas neste turno" value={rule.enabled} onChange={enabled => setRule({ enabled })} />
            <TimeRows key={ruleIndex} values={rule.times} onChange={times => setRule({ times })} />
            <TimeInput key={`recheck-${ruleIndex}`} label="Conferência do turno (opcional)" value={rule.recheck ?? ''} onChange={value => setRule({ recheck: value || null })} />
          </Section>
        </> : <>
          <Section title="Repetição">
            <Select value={draft.mode} onChange={key => key != null && set({ mode: key as PeriodDraft['mode'] })} fullWidth>
              <Label>Quando coletar</Label><Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
              <Select.Popover><ListBox>{MODES.map(mode => <ListBox.Item key={mode.id} id={mode.id} textValue={mode.label}>
                {mode.label}<ListBox.ItemIndicator /></ListBox.Item>)}</ListBox></Select.Popover>
            </Select>
            {draft.mode === 'interval' && <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <NumberInput label="A cada (min)" value={draft.every} min={MIN_GAP_MINUTES} max={MAX_EVERY_MINUTES} step={5} onChange={value => set({ every: value })} />
              <TimeInput label="Das" value={draft.from} onChange={value => set({ from: value })} />
              <TimeInput label="Até" value={draft.to} onChange={value => set({ to: value })} />
            </div>}
            {draft.mode === 'times' && <TimeRows values={draft.times} onChange={times => set({ times })} />}
            {draft.mode !== 'off' && <div className="flex flex-col gap-2"><span className="text-sm">Dias</span>
              <ToggleButtonGroup size="sm" selectionMode="multiple" selectedKeys={draft.weekdays.map(String)}
                className="flex flex-wrap" onSelectionChange={keys => set({ weekdays: [...keys].map(Number).sort() })}>
                {DAY_LETTERS.map((day, i) => <ToggleButton key={i} id={String(i)} aria-label={DAY_NAMES[i]} className="w-10">{day}</ToggleButton>)}
              </ToggleButtonGroup></div>}
          </Section>
          {draft.mode !== 'off' && <Section title="Conferência final do dia">
            <div className="grid grid-cols-[1fr_auto] items-end gap-3">
              <TimeInput label="Horário (opcional)" value={draft.finalCheck} onChange={value => set({ finalCheck: value })} />
              {draft.finalCheck && <Button variant="ghost" onPress={() => set({ finalCheck: '' })}>Remover</Button>}
            </div>
          </Section>}
          <Button size="sm" variant="secondary" isDisabled={!!problem} onPress={() => { setRulesDraft(candidate); setPerRule(true); }}>Editar por dia e turno</Button>
          {draft.mode !== 'off' && !problem && <p className="text-xs text-muted">{perDay} coleta(s) por dia escolhido.</p>}
        </>}
        {perDay > 16 && <Alert status="warning"><Alert.Indicator /><Alert.Content>
          <Alert.Title>Mais de 16 coletas por dia</Alert.Title><Alert.Description>Antes de salvar, atualize o Coletor em todos os computadores da escola.</Alert.Description>
        </Alert.Content></Alert>}
        {(problem || error) && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{error || problem}</Alert.Title></Alert.Content></Alert>}
      </Modal.Body>
      <Modal.Footer className="flex justify-end gap-2"><Button variant="tertiary" onPress={onClose} isDisabled={saving}>Cancelar</Button>
        <Button variant="primary" onPress={() => { void save(); }} isPending={saving} isDisabled={blocked}><Save size={16} /> Salvar</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container>
  </Modal.Backdrop></TimeValidationContext.Provider>;
}
