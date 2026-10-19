// Small building blocks on HeroUI v3, the same ones the Atualizador de Planilhas uses.
import type { ReactNode } from 'react';
import { Button, Chip, Description, Input, Label, NumberField, Switch, TextField, Tooltip } from '@heroui/react';
import { I18nProvider, TimeField } from '@heroui/react';
import { parseTime } from '@internationalized/date';

type Tone = 'default' | 'success' | 'warning' | 'danger' | 'accent';
const RUN_STATUS: Record<string, { label: string; color: Tone }> = {
  ok: { label: 'Concluída', color: 'success' },
  review: { label: 'Com pendências', color: 'warning' },
  partial: { label: 'Parcial', color: 'warning' },
  stopped: { label: 'Interrompida', color: 'default' },
  error: { label: 'Falhou', color: 'danger' },
  running: { label: 'Coletando', color: 'accent' },
};
export function StatusChip({ status }: Readonly<{ status?: string | null }>) {
  if (!status) return <Chip size="sm" variant="soft" color="default">Nunca executada</Chip>;
  const s = RUN_STATUS[status] ?? { label: status, color: 'default' as const };
  return <Chip size="sm" variant="soft" color={s.color}>{s.label}</Chip>;
}

export function IconButton({ label, onPress, children, isDisabled }: Readonly<{ label: string; onPress: () => void; children: ReactNode; isDisabled?: boolean }>) {
  return (
    <Tooltip delay={400} closeDelay={0}>
      <Button isIconOnly size="sm" variant="ghost" aria-label={label} onPress={onPress} isDisabled={isDisabled}>{children}</Button>
      <Tooltip.Content>{label}</Tooltip.Content>
    </Tooltip>
  );
}

export function SwitchRow({ label, hint, value, onChange, isDisabled }: Readonly<{ label: string; hint?: string; value: boolean; onChange: (v: boolean) => void; isDisabled?: boolean }>) {
  return (
    <Switch isSelected={value} onChange={onChange} isDisabled={isDisabled} className="w-full">
      <Switch.Content className="flex w-full items-center justify-between gap-4 py-1.5">
        <span className="flex flex-col">
          <span className="text-sm">{label}</span>
          {hint && <span className="text-xs text-muted">{hint}</span>}
        </span>
        <Switch.Control><Switch.Thumb /></Switch.Control>
      </Switch.Content>
    </Switch>
  );
}

export function NumberInput({ label, value, onChange, min = 0, max, step = 1, suffix }: Readonly<{ label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string }>) {
  return (
    <NumberField value={value} onChange={v => onChange(Number.isFinite(v) ? v : min)} minValue={min} maxValue={max} step={step} fullWidth>
      <Label>{label}</Label>
      <NumberField.Group><NumberField.DecrementButton /><NumberField.Input /><NumberField.IncrementButton /></NumberField.Group>
      {suffix && <Description>{suffix}</Description>}
    </NumberField>
  );
}

export function TextInput({ label, value, onChange, placeholder, type = 'text', hint, autoComplete }: Readonly<{ label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; hint?: string; autoComplete?: string }>) {
  return (
    <TextField value={value} onChange={onChange} fullWidth>
      <Label>{label}</Label>
      <Input placeholder={placeholder} type={type} autoComplete={autoComplete} />
      {hint && <Description>{hint}</Description>}
    </TextField>
  );
}

function safeTime(value: string) { try { return parseTime(value); } catch { return null; } }
/** "HH:MM" (24 h) with HeroUI's time field. */
export function TimeInput({ label, value, onChange }: Readonly<{ label: string; value: string; onChange: (v: string) => void }>) {
  return (
    <I18nProvider locale="pt-BR">
      <TimeField value={value ? safeTime(value) : null} hourCycle={24} className="w-full"
        onChange={t => onChange(t ? `${String(t.hour).padStart(2, '0')}:${String(t.minute).padStart(2, '0')}` : '')}>
        <Label>{label}</Label>
        <TimeField.Group fullWidth><TimeField.Input>{segment => <TimeField.Segment segment={segment} />}</TimeField.Input></TimeField.Group>
      </TimeField>
    </I18nProvider>
  );
}

export function Section({ title, children, aside }: Readonly<{ title: string; children: ReactNode; aside?: ReactNode }>) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Stat({ label, value, icon }: Readonly<{ label: string; value: ReactNode; icon: ReactNode }>) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-separator bg-surface px-4 py-3">
      <div className="text-muted">{icon}</div>
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-lg font-semibold leading-tight tabular-nums">{value}</span>
        <span className="text-xs text-muted">{label}</span>
      </div>
    </div>
  );
}
