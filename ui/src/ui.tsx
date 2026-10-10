import type { ReactNode } from 'react';
import { Chip, Select, Label, ListBox } from '@heroui/react';
export function StatusChip({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'success' | 'warning' | 'danger' }) {
  return <Chip size="sm" variant="soft" color={tone}>{children}</Chip>;
}
export function SelectField({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: { id: string; label: string }[] }) {
  return <Select value={value} onChange={key => key != null && onChange(String(key))} fullWidth>
    <Label>{label}</Label><Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
    <Select.Popover><ListBox>{options.map(option => <ListBox.Item key={option.id} id={option.id} textValue={option.label}>{option.label}<ListBox.ItemIndicator /></ListBox.Item>)}</ListBox></Select.Popover>
  </Select>;
}
