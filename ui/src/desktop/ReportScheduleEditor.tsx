import { useMemo, useState } from 'react';
import { Alert, Button, Modal, ToggleButton, ToggleButtonGroup } from '@heroui/react';
import { Save } from 'lucide-react';
import type { HistoryEntry, ReportSchedule } from '../collector';
import { call, type Status } from './bridge';
import { notify } from './foxSay';
import { DAY_LETTERS, DAY_NAMES, MAX_EVERY_MINUTES, editorDay, serverDay } from './periods';
import { DEFAULT_REPORT, REPORT_MIN_EVERY, frequencyMinutes, reportClash, reportMinutes, reportProblem, reportTimes } from './reportPlan';
import { NumberInput, Section, SwitchRow, TimeInput, TimeValidationContext, useIncompleteTimes } from './ui';

/** The Smecel "Relatório de alunos" agenda, saved in the Ecossistema for every computer of the school.
 *  Mounted while open: it edits the agenda as saved at that moment, whatever a later poll brings. */
export default function ReportScheduleEditor({ status, history, onClose, onSaved }: Readonly<{
  status: Status | null; history: readonly HistoryEntry[]; onClose: () => void; onSaved: (status: Status) => void;
}>) {
  const [draft, setDraft] = useState<ReportSchedule>(() => {
    const saved = status?.settings?.reportSchedule ?? null;
    return saved ? { ...saved, weekdays: [...saved.weekdays] }
      : { ...DEFAULT_REPORT, timezone: status?.settings?.schedule?.timezone ?? DEFAULT_REPORT.timezone };
  });
  const [revision] = useState(status?.settings?.revision ?? null);
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  const [incomplete, reportTime] = useIncompleteTimes();
  const set = (patch: Partial<ReportSchedule>) => setDraft(d => ({ ...d, ...patch }));
  // The margin is how long the runs really take on this computer (owner decision 29/10/2026).
  const lengths = useMemo(() => ({ report: reportMinutes(history), frequency: frequencyMinutes(history) }), [history]);
  // A time left half typed still holds its last complete value: never saved in place of what is on screen.
  const problem = (incomplete ? 'Preencha os horários.' : reportProblem(draft))
    ?? reportClash(draft, status?.settings?.schedule, lengths.report, lengths.frequency);
  const times = reportTimes(draft);
  // Editor days are Monday first; the server's weekdays are Sunday first.
  const editorDays = draft.weekdays.map(editorDay);

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
  return <TimeValidationContext.Provider value={reportTime}><Modal.Backdrop isOpen onOpenChange={v => !v && !saving && onClose()} variant="blur">
    <Modal.Container size="md" scroll="inside"><Modal.Dialog className="max-h-[88vh]">
      <Modal.Header><Modal.Heading>Agenda do relatório de alunos</Modal.Heading>
        <p className="text-sm text-muted">Vale para todos os computadores da escola. Nunca roda junto da frequência.</p></Modal.Header>
      <Modal.Body className="flex flex-col gap-6 pb-2">
        <SwitchRow label="Leituras automáticas" hint="Lê o relatório no Smecel e atualiza datas de matrícula e transferência." value={draft.enabled} onChange={enabled => set({ enabled })} />
        <Section title="Repetição">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <NumberInput label="A cada (min)" value={draft.every} min={REPORT_MIN_EVERY} max={MAX_EVERY_MINUTES} step={5} onChange={every => set({ every })} />
            <TimeInput label="Das" value={draft.from} onChange={from => set({ from })} />
            <TimeInput label="Até" value={draft.to} onChange={to => set({ to })} />
          </div>
          <div className="flex flex-col gap-2"><span className="text-sm">Dias</span>
            <ToggleButtonGroup size="sm" selectionMode="multiple" selectedKeys={editorDays.map(String)} className="flex flex-wrap"
              onSelectionChange={keys => set({ weekdays: [...keys].map(Number).sort().map(serverDay) })}>
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
