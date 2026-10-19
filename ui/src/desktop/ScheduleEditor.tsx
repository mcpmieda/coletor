import { useEffect, useState } from 'react';
import { Alert, Button, ListBox, Label, Modal, Select, ToggleButton, ToggleButtonGroup, toast } from '@heroui/react';
import { Plus, Save, X } from 'lucide-react';
import type { SharedSchedule } from '../collector';
import { call, type Status } from './bridge';
import { DAY_LETTERS, DAY_NAMES, dayTimes, draftProblem, fromShared, toShared, type PeriodDraft } from './periods';
import { IconButton, NumberInput, Section, TimeInput } from './ui';

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
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  // The revision the draft was loaded from: saving with a newer polled one
  // would hide an edit made meanwhile on another computer.
  const [baseRevision, setBaseRevision] = useState<number | null>(null);
  useEffect(() => {
    if (!open) return;
    const next = fromShared(status?.settings?.schedule ?? null);
    setDraft(next); setError('');
    setBaseRevision(status?.settings?.revision ?? null);
  }, [open]); // Reload only when the dialog opens, not on every status poll.
  const set = (patch: Partial<PeriodDraft>) => setDraft(d => ({ ...d, ...patch }));
  const filled = draft.times.filter(Boolean);
  const repeated = [...new Set(filled.filter((t, i) => filled.indexOf(t) !== i))];
  const problem = (draft.mode === 'times' && repeated.length ? `Horário repetido: ${repeated.join(', ')}.` : null) ?? draftProblem(draft);
  const setTime = (index: number, value: string) => set({ times: draft.times.map((t, i) => (i === index ? value : t)) });
  // A new field starts 30 minutes after the latest time (or at 07:00).
  const addTime = () => {
    const latest = [...filled].sort().at(-1);
    const minutes = latest ? Math.min(23 * 60 + 59, Number(latest.slice(0, 2)) * 60 + Number(latest.slice(3)) + 30) : 7 * 60;
    set({ times: [...draft.times, `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`] });
  };
  const perDay = dayTimes(draft).length + (draft.finalCheck ? 1 : 0);

  async function save() {
    if (problem || baseRevision === null) return;
    setSaving(true); setError('');
    try {
      const schedule: SharedSchedule = toShared(draft);
      const saved = await call(api => api.save_shared_schedule(baseRevision, schedule));
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
                <div className="flex flex-col gap-2">
                  <span className="text-sm">Horários do dia</span>
                  <div className="grid grid-cols-3 gap-2">
                    {draft.times.map((time, index) => (
                      <div key={index} className="flex items-end gap-1">
                        <TimeInput label={`Horário ${index + 1}`} value={time} onChange={v => setTime(index, v)} />
                        <IconButton label={`Remover horário ${index + 1}`} onPress={() => set({ times: draft.times.filter((_, i) => i !== index) })}><X size={14} /></IconButton>
                      </div>
                    ))}
                  </div>
                  <Button size="sm" variant="secondary" className="self-start" isDisabled={draft.times.length >= 48} onPress={addTime}><Plus size={14} /> Adicionar horário</Button>
                </div>
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
            {draft.mode !== 'off' && perDay > 16 && (
              <Alert status="warning">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>Mais de 16 coletas por dia</Alert.Title>
                  <Alert.Description>Coletores de versão anterior param de coletar com esta agenda. Antes de salvar, atualize o Coletor em todos os computadores da escola.</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            {(problem || error) && (
              <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{error || problem}</Alert.Title></Alert.Content></Alert>
            )}
          </Modal.Body>
          <Modal.Footer className="flex justify-end gap-2">
            <Button variant="tertiary" onPress={onClose}>Cancelar</Button>
            <Button variant="primary" onPress={() => { void save(); }} isPending={saving} isDisabled={!!problem || baseRevision === null}><Save size={16} /> Salvar</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
