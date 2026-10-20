import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import { Plus, X } from 'lucide-react';
import { nextTimeField } from './periods';
import { IconButton, TimeInput } from './ui';

export default function TimeRows({ values, onChange }: Readonly<{ values: string[]; onChange: (values: string[]) => void }>) {
  const prefix = useId();
  const counter = useRef(0);
  const container = useRef<HTMLDivElement>(null);
  const makeRow = (value: string) => ({ id: `${prefix}-${counter.current++}`, value });
  const [rows, setRows] = useState(() => values.map(makeRow));
  useEffect(() => {
    if (JSON.stringify(values) !== JSON.stringify(rows.map(r => r.value))) setRows(values.map(makeRow));
  }, [values]);
  const publish = (next: typeof rows) => { setRows(next); onChange(next.map(r => r.value)); };
  const remove = (id: string) => {
    const index = rows.findIndex(r => r.id === id);
    const next = rows.filter(r => r.id !== id);
    const focus = next[Math.min(index, next.length - 1)]?.id;
    publish(next);
    requestAnimationFrame(() => {
      if (focus) container.current?.querySelector<HTMLElement>(`[data-time-row="${focus}"] [role="spinbutton"]`)?.focus();
      else container.current?.querySelector<HTMLButtonElement>('[data-add-time]')?.focus();
    });
  };
  const addition = nextTimeField(values);
  return <div ref={container} className="flex flex-col gap-2">
    <span className="text-sm">Horários do dia</span>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((row, index) => <div key={row.id} data-time-row={row.id} className="flex min-w-0 items-end gap-1">
        <div className="min-w-0 flex-1"><TimeInput label={`Horário ${index + 1}`} value={row.value}
          onChange={value => publish(rows.map(r => r.id === row.id ? { ...r, value } : r))} /></div>
        <IconButton label={`Remover horário ${index + 1}`} onPress={() => remove(row.id)}><X size={14} /></IconButton>
      </div>)}
    </div>
    <Button data-add-time size="sm" variant="secondary" className="self-start" isDisabled={!addition.allowed}
      onPress={() => publish([...rows, makeRow(addition.value)])}><Plus size={14} /> Adicionar horário</Button>
    {!addition.allowed && values.length < 48 && values.every(Boolean) && <span className="text-xs text-muted">Não há mais horários disponíveis neste dia.</span>}
  </div>;
}
