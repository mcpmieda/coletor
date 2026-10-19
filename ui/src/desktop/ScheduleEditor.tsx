import { useEffect, useState } from 'react';
import { Alert, Button, ListBox, Label, Modal, Select, ToggleButton, ToggleButtonGroup, toast } from '@heroui/react';
import { Save } from 'lucide-react';
import type { SharedSchedule } from '../collector';
import { call, type Status } from './bridge';
import { DAY_LETTERS, DAY_NAMES, dayTimes, draftProblem, fromShared, toShared, type PeriodDraft } from './periods';
import { NumberInput, Section, TextInput, TimeInput } from './ui';

const MODES: { id: PeriodDraft['mode']; label: string; hint: string }[] = [
  { id: 'interval', label: 'Em intervalos', hint: 'A cada X minutos, dentro do período do dia' },
  { id: 'times', label: 'Em horários fixos', hint: 'Nos horários que você escolher' },
  { id: 'off', label: 'Somente manual', hint: 'Sem coletas automáticas; use Coletar agora' },
];

/** School-wide agenda (shared by every computer), edited by periods. */
export default function ScheduleEditor({ open, status, onClose, onSaved }: Readonly<{
  open: boolean; status: Status | null; onClose: () => void; onSaved: (status: Status) => void;
}>) {
  const [draft, setDraft] = useState<PeriodDraft>(() => fromShared(status?.settings?.schedule ?? null));
  const [timesText, setTimesText] = useState('');
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    const next = fromShared(status?.settings?.schedule ?? null);
    setDraft(next); setTimesText(next.times.join(', ')); setError('');
  }, [open]); // Reload only when the dialog opens, not on every status poll.
  const set = (patch: Partial<PeriodDraft>) => setDraft(d => ({ ...d, ...patch }));
  const problem = draftProblem(draft);
  const perDay = dayTimes(draft).length + (draft.finalCheck ? 1 : 0);

  async function save() {
    if (problem || !status?.settings) return;
    setSaving(true); setError('');
    try {
      const schedule: SharedSchedule = toShared(draft);
      const saved = await call(api => api.save_shared_schedule(status.settings!.revision, schedule));
      toast.success('Agenda salva para todos os computadores da escola');
      onSaved(saved);
    } catch (e) {
      const code = (e as Error & { code?: string }).code;
      setError(code === 'revision-conflict' ? 'A agenda mudou em outro computador. Feche e abra de novo para ver a versão atual.' : (e instanceof Error ? e.message : 'Não foi possível salvar.'));
    } finally { setSaving(false); }
  }

  return (
    <Modal.Backdrop isOpen={open} onOpenChange={v => !v && onClose()} variant="blur">
      <Modal.Container size="lg" scroll="inside">
        <Modal.Dialog className="max-h-[88vh]">
          <Modal.Header>
            <Modal.Heading>Agenda de coleta</Modal.Heading>
            <p className="text-sm text-muted">Vale para todos os computadores da escola. Cada coleta lê todas as turmas.</p>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-6 pb-2">
            {draft.custom && (
              <Alert status="warning">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>A agenda atual tem horários diferentes por turno ou dia</Alert.Title>
                  <Alert.Description>Ela foi feita no Ecossistema. Ao salvar aqui, todos os dias escolhidos passam a usar os mesmos horários.</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            <Section title="Repetição">
              <Select value={draft.mode} onChange={k => k != null && set({ mode: k as PeriodDraft['mode'] })} fullWidth>
                <Label>Quando coletar</Label>
                <Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {MODES.map(m => (
                      <ListBox.Item key={m.id} id={m.id} textValue={m.label}>
                        <div className="flex flex-col"><span>{m.label}</span><span className="text-xs text-muted">{m.hint}</span></div>
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
              {draft.mode === 'interval' && (
                <div className="grid grid-cols-3 gap-3">
                  <NumberInput label="A cada (min)" value={draft.every} min={5} max={720} step={5} onChange={v => set({ every: v })} />
                  <TimeInput label="Das" value={draft.from} onChange={v => set({ from: v })} />
                  <TimeInput label="Até" value={draft.to} onChange={v => set({ to: v })} />
                </div>
              )}
              {draft.mode === 'times' && (
                <TextInput label="Horários" value={timesText} placeholder="07:30, 12:00, 17:30" hint="Separe por vírgula"
                  onChange={v => { setTimesText(v); set({ times: v.split(/[,; ]+/).filter(x => /^\d{1,2}:\d{2}$/.test(x)).map(x => x.padStart(5, '0')) }); }} />
              )}
              {draft.mode !== 'off' && (
                <div className="flex flex-col gap-2">
                  <span className="text-sm">Dias</span>
                  <ToggleButtonGroup size="sm" selectionMode="multiple" selectedKeys={draft.weekdays.map(String)}
                    onSelectionChange={k => set({ weekdays: [...k].map(Number).sort() })}>
                    {DAY_LETTERS.map((d, i) => <ToggleButton key={i} id={String(i)} aria-label={DAY_NAMES[i]} className="w-10">{d}</ToggleButton>)}
                  </ToggleButtonGroup>
                </div>
              )}
            </Section>
            {draft.mode !== 'off' && (
              <Section title="Conferência final do dia">
                <div className="grid grid-cols-[1fr_auto] items-end gap-3">
                  <TimeInput label="Horário (opcional)" value={draft.finalCheck} onChange={v => set({ finalCheck: v })} />
                  {draft.finalCheck && <Button variant="ghost" onPress={() => set({ finalCheck: '' })}>Remover</Button>}
                </div>
                <span className="text-xs text-muted">Uma última leitura depois do expediente, para pegar correções feitas no fim do dia.</span>
              </Section>
            )}
            {draft.mode !== 'off' && !problem && <p className="text-xs text-muted">{perDay} coleta(s) por dia escolhido.</p>}
            {(problem || error) && (
              <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{error || problem}</Alert.Title></Alert.Content></Alert>
            )}
          </Modal.Body>
          <Modal.Footer className="flex justify-end gap-2">
            <Button variant="tertiary" onPress={onClose}>Cancelar</Button>
            <Button variant="primary" onPress={() => { void save(); }} isPending={saving} isDisabled={!!problem || !status?.settings}><Save size={16} /> Salvar</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
