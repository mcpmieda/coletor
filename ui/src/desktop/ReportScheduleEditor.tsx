import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Modal, ToggleButton, ToggleButtonGroup } from '@heroui/react';
import { Save } from 'lucide-react';
import type { HistoryEntry, ReportSchedule } from '../collector';
import { call, type Status } from './bridge';
import { notify } from './foxSay';
import { DAY_LETTERS, DAY_NAMES } from './periods';
import { DEFAULT_REPORT, REPORT_MIN_EVERY, frequencyMinutes, reportClash, reportMinutes, reportProblem, reportTimes } from './reportPlan';
import { NumberInput, Section, SwitchRow, TimeInput, TimeValidationContext } from './ui';

/** The Smecel "Relatório de alunos" agenda, saved in the Ecossistema for every computer of the school. */
export default function ReportScheduleEditor({ open, status, history, onClose, onSaved }: Readonly<{
  open: boolean; status: Status | null; history: readonly HistoryEntry[]; onClose: () => void; onSaved: (status: Status) => void;
}>) {
  const [draft, setDraft] = useState<ReportSchedule>(DEFAULT_REPORT);
  const [revision, setRevision] = useState<number | null>(null);
  const [session, setSession] = useState(0), [saving, setSaving] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    const saved = status?.settings?.reportSchedule ?? null;
    const zone = status?.settings?.schedule?.timezone ?? DEFAULT_REPORT.timezone;
    setDraft(saved ? { ...saved, weekdays: [...saved.weekdays] } : { ...DEFAULT_REPORT, timezone: zone });
    setRevision(status?.settings?.revision ?? null); setError(''); setSession(s => s + 1);
  }, [open]);
  const set = (patch: Partial<ReportSchedule>) => setDraft(d => ({ ...d, ...patch }));
  // The margin is how long the runs really take on this computer (owner decision 29/10/2026).
  const lengths = useMemo(() => ({ report: reportMinutes(history), frequency: frequencyMinutes(history) }), [history]);
  const problem = reportProblem(draft) ?? reportClash(draft, status?.settings?.schedule, lengths.report, lengths.frequency);
  const times = reportTimes(draft);
  // Editor days are Monday first; the server's weekdays are Sunday first.
  const editorDays = draft.weekdays.map(d => (d + 6) % 7);

  async function save() {
    if (problem || revision === null) return;
    setSaving(true); setError('');
    try {
      const saved = await call(api => api.save_report_schedule(revision, draft));
      notify.success('Agenda do relatório salva para todos os computadores da escola'); onSaved(saved);
    } catch (e) {
      const code = (e as Error & { code?: string }).code;
      setError(code === 'revision-conflict' ? 'A agenda mudou em outro computador. Feche e abra de novo para ver a versão atual.' : (e instanceof Error ? e.message : 'Não foi possível salvar.'));
    } finally { setSaving(false); }
  }
  return <TimeValidationContext.Provider value={null}><Modal.Backdrop isOpen={open} onOpenChange={v => !v && !saving && onClose()} variant="blur">
    <Modal.Container size="md" scroll="inside"><Modal.Dialog className="max-h-[88vh]">
      <Modal.Header><Modal.Heading>Agenda do relatório de alunos</Modal.Heading>
        <p className="text-sm text-muted">Vale para todos os computadores da escola. Nunca roda junto da frequência.</p></Modal.Header>
      <Modal.Body className="flex flex-col gap-6 pb-2">
        <SwitchRow label="Leituras automáticas" hint="Lê o relatório no Smecel e atualiza datas de matrícula e transferência." value={draft.enabled} onChange={enabled => set({ enabled })} />
        <Section title="Repetição">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <NumberInput label="A cada (min)" value={draft.every} min={REPORT_MIN_EVERY} max={720} step={5} onChange={every => set({ every })} />
            <TimeInput key={`${session}-from`} label="Das" value={draft.from} onChange={from => set({ from })} />
            <TimeInput key={`${session}-to`} label="Até" value={draft.to} onChange={to => set({ to })} />
          </div>
          <div className="flex flex-col gap-2"><span className="text-sm">Dias</span>
            <ToggleButtonGroup size="sm" selectionMode="multiple" selectedKeys={editorDays.map(String)} className="flex flex-wrap"
              onSelectionChange={keys => set({ weekdays: [...keys].map(Number).sort().map(d => (d + 1) % 7) })}>
              {DAY_LETTERS.map((day, i) => <ToggleButton key={i} id={String(i)} aria-label={DAY_NAMES[i]} className="w-10">{day}</ToggleButton>)}
            </ToggleButtonGroup></div>
          {draft.enabled && !problem && <p className="text-xs text-muted">{times.length} leitura(s) por dia: {times.join(', ')}.</p>}
          <p className="text-xs text-muted">
            Distância da frequência pela duração das últimas coletas deste computador: frequência {lengths.frequency || '—'} min, relatório {lengths.report || '—'} min.
          </p>
        </Section>
        {(problem || error) && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{error || problem}</Alert.Title></Alert.Content></Alert>}
      </Modal.Body>
      <Modal.Footer className="flex justify-end gap-2"><Button variant="tertiary" onPress={onClose} isDisabled={saving}>Cancelar</Button>
        <Button variant="primary" onPress={() => { void save(); }} isPending={saving} isDisabled={!!problem || revision === null}><Save size={16} /> Salvar</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container>
  </Modal.Backdrop></TimeValidationContext.Provider>;
}
