import { useMemo, useState, type ReactNode } from 'react';
import { Button, Modal, Table, ToggleButton, ToggleButtonGroup } from '@heroui/react';
import { AlertTriangle, Info, XCircle } from 'lucide-react';
import type { HistoryEntry } from '../collector';
import { fmtDate, fmtDuration, groupRuns, logEvents, runSummary, type Level, type Run } from './runs';
import { StatusChip } from './ui';

const seconds = (ms?: number) => (ms === undefined ? '—' : `${(ms / 1000).toFixed(1).replace('.', ',')} s`);

// ------------------------------------------------------------------ Histórico
export function HistoryPage({ history }: Readonly<{ history: HistoryEntry[] }>) {
  const runs = useMemo(() => groupRuns(history), [history]);
  const [open, setOpen] = useState<Run | null>(null);
  if (!runs.length) return <p className="py-16 text-center text-muted">Nenhuma coleta ainda.</p>;
  return (
    <>
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label="Coletas" onRowAction={k => setOpen(runs.find(r => r.id === String(k)) ?? null)}>
            <Table.Header>
              <Table.Column isRowHeader>Início</Table.Column>
              <Table.Column>Duração</Table.Column>
              <Table.Column>Status</Table.Column>
              <Table.Column>Resumo</Table.Column>
            </Table.Header>
            <Table.Body>
              {runs.map(r => (
                <Table.Row key={r.id} id={r.id} className="cursor-pointer">
                  <Table.Cell className="whitespace-nowrap">{fmtDate(r.started)}</Table.Cell>
                  <Table.Cell className="whitespace-nowrap text-muted">{fmtDuration(r.started, r.finished)}</Table.Cell>
                  <Table.Cell><StatusChip status={r.status} /></Table.Cell>
                  <Table.Cell className="max-w-[460px] truncate text-muted">{runSummary(r)}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
      <Modal.Backdrop isOpen={!!open} onOpenChange={v => !v && setOpen(null)} variant="blur">
        <Modal.Container size="lg" scroll="inside">
          <Modal.Dialog className="max-h-[85vh]">
            <Modal.Header>
              <Modal.Heading>Coleta de {open && fmtDate(open.started)}</Modal.Heading>
              <p className="text-sm text-muted">{open && `${fmtDuration(open.started, open.finished)} · ${runSummary(open)}`}</p>
            </Modal.Header>
            <Modal.Body className="flex flex-col gap-1">
              {(open?.classes ?? []).map((c, i) => (
                <div key={`${c.label}-${i}`} className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-default">
                  <StatusChip status={c.unresolved || c.conflicts ? 'review' : 'ok'} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{c.label}</div>
                    <div className="text-xs text-muted">
                      {c.sent} aluno(s){c.unresolved ? ` · ${c.unresolved} não reconhecido(s)` : ''}{c.conflicts ? ` · ${c.conflicts} conflito(s)` : ''}
                    </div>
                  </div>
                  <span className="text-xs tabular-nums text-muted" title="Leitura no Smecel · envio ao Ecossistema">{seconds(c.readMs)} · {seconds(c.sendMs)}</span>
                </div>
              ))}
              {open?.problem && <p className="px-2 pt-2 text-sm text-danger">{open.problem}</p>}
              {!open?.classes.length && !open?.problem && <p className="py-6 text-center text-muted">Nenhuma turma enviada nesta coleta.</p>}
            </Modal.Body>
            <Modal.Footer><Button variant="tertiary" onPress={() => setOpen(null)}>Fechar</Button></Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </>
  );
}

// ------------------------------------------------------------------ Registros
const LEVEL_ICON: Record<Level, ReactNode> = {
  info: <Info size={15} className="text-muted" />,
  warn: <AlertTriangle size={15} className="text-warning" />,
  error: <XCircle size={15} className="text-danger" />,
};

export function LogsPage({ history }: Readonly<{ history: HistoryEntry[] }>) {
  const [level, setLevel] = useState<'all' | 'warn' | 'error'>('all');
  const events = useMemo(() => logEvents(history).filter(e => level === 'all' || (level === 'warn' ? e.level !== 'info' : e.level === 'error')), [history, level]);
  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <ToggleButtonGroup size="sm" selectionMode="single" disallowEmptySelection selectedKeys={[level]} onSelectionChange={k => setLevel(String([...k][0]) as typeof level)}>
          <ToggleButton id="all">Todos</ToggleButton>
          <ToggleButton id="warn">Avisos</ToggleButton>
          <ToggleButton id="error">Erros</ToggleButton>
        </ToggleButtonGroup>
        <span className="text-xs text-muted">Últimos 30 dias deste computador</span>
      </div>
      {events.length === 0 ? <p className="py-16 text-center text-muted">Nada por aqui.</p> : (
        <div className="flex flex-col divide-y divide-separator rounded-xl border border-separator bg-surface">
          {events.map(e => (
            <div key={e.id} className="flex items-start gap-3 px-4 py-2.5 text-sm">
              <span className="mt-0.5">{LEVEL_ICON[e.level]}</span>
              <span className="w-28 shrink-0 text-xs leading-5 text-muted">{fmtDate(e.at)}</span>
              <div className="min-w-0 flex-1">
                <div className="selectable break-words">{e.message}</div>
                {e.detail && <div className="truncate text-xs text-muted">{e.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
