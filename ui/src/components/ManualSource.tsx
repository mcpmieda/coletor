import { useEffect, useRef, useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { nativeApi } from '../api';
import type { Preview } from '../types';

export interface ManualStatus {
  generation: number;
  state: 'closed' | 'prepared' | 'opening' | 'awaiting_user' | 'capturing' | 'preview_ready';
  scope: { class_id: string; year: number; url: string } | null;
  identity_verified: false;
  transmission_enabled: false;
  notice: string;
}
type Failure = { error: string };
export interface ManualBridge {
  prepare_manual_session(classId: string, year: number): Promise<ManualStatus | Failure>;
  open_manual_session(generation: number, confirmed: boolean): Promise<ManualStatus | Failure>;
  capture_manual_preview(generation: number, confirmed: boolean): Promise<{ session: ManualStatus; preview: Preview } | Failure>;
  close_manual_session(): Promise<ManualStatus | Failure>;
  get_manual_session_status(): Promise<ManualStatus>;
}
function checked<T>(result: T | Failure): T {
  if (typeof result === 'object' && result !== null && 'error' in result) throw new Error(String(result.error));
  return result as T;
}
async function bridge(): Promise<ManualBridge> {
  const api = await nativeApi();
  if (!api?.prepare_manual_session || !api.open_manual_session || !api.capture_manual_preview || !api.close_manual_session) {
    throw new Error('A sessão manual está disponível no programa Windows. Aqui você pode conferir arquivos e exemplos.');
  }
  return api as ManualBridge;
}
export default function ManualSource({ busy, onBusy, onRead, onClear }: {
  busy: boolean; onBusy: (value: boolean) => void;
  onRead: (work: () => Promise<Preview>) => Promise<void>; onClear: () => void;
}) {
  const [classId, setClassId] = useState('');
  const [year, setYear] = useState('2026');
  const [session, setSession] = useState<ManualStatus | null>(null);
  const [confirmation, setConfirmation] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(false);
  const operation = useRef(0);
  const closing = useRef(false);
  useEffect(() => () => {
    operation.current++;
    void window.pywebview?.api.close_manual_session?.().catch(() => undefined);
  }, []);
  async function perform(work: () => Promise<ManualStatus>) {
    if (active.current || busy || closing.current) return;
    active.current = true; onBusy(true); setError('');
    const id = ++operation.current;
    try { const result = await work(); if (id === operation.current) { setSession(result); setConfirmation(false); } }
    catch (e) { if (id === operation.current) setError(e instanceof Error ? e.message : 'Não foi possível abrir a sessão.'); }
    finally { active.current = false; onBusy(false); }
  }
  async function close() {
    if (closing.current) return;
    closing.current = true; operation.current++; onClear(); setConfirmation(false); setError('');
    try { setSession(checked(await (await bridge()).close_manual_session())); }
    catch { setError('Não foi possível confirmar o encerramento. Feche o programa para encerrar sua sessão.'); }
    finally { closing.current = false; }
  }
  async function capture() {
    if (!session || active.current || busy || !confirmation || closing.current) return;
    const generation = session.generation;
    const id = ++operation.current;
    active.current = true; setError(''); setConfirmation(false);
    try {
      await onRead(async () => {
        const result = checked(await (await bridge()).capture_manual_preview(generation, true));
        if (id !== operation.current) throw new Error('Leitura descartada.');
        setSession(result.session);
        return result.preview;
      });
    } finally { active.current = false; }
  }
  const prepared = session?.state === 'prepared';
  const opened = session?.state === 'awaiting_user' || session?.state === 'preview_ready';
  const live = !!session && session.state !== 'closed';
  return <section className="panel source-panel" aria-labelledby="manual-source-title">
    <h2 id="manual-source-title">Sessão manual no Smecel</h2>
    <p>Você entra no site em uma janela separada do Microsoft Edge. A leitura só acontece após sua confirmação e fica na memória deste computador.</p>
    <p className="muted">O programa não confirma a identidade da escola nem a lista completa de alunos. Envio e coleta automática estão desligados. Não informe senhas nesta tela.</p>
    <div className="source-controls">
      <TextField value={classId} onChange={setClassId} isDisabled={busy || live}><Label>Código numérico da turma no Smecel</Label><Input inputMode="numeric" /></TextField>
      <TextField value={year} onChange={setYear} isDisabled={busy || live}><Label>Ano do diário manual</Label><Input inputMode="numeric" maxLength={4} /></TextField>
      <Button isDisabled={busy || live} onPress={() => { void perform(async () => checked(await (await bridge()).prepare_manual_session(classId.trim(), Number(year)))); }}>Preparar sessão</Button>
    </div>
    {live && <>
      <p role="status">Turma {session.scope?.class_id} · Ano {session.scope?.year} · {prepared ? 'Sessão preparada, sem acesso ao site.' : 'Confira o diário na janela separada. A entrada no site não foi verificada pelo programa.'}</p>
      <p><code>{session.scope?.url}</code></p>
      {opened && <p>Depois de entrar no site, abra esse endereço na janela separada do Edge e confira a escola, a turma e o ano antes de autorizar a leitura.</p>}
      {(prepared || opened) && <label className="status-line"><input type="checkbox" checked={confirmation} disabled={busy} onChange={e => setConfirmation(e.target.checked)} />{prepared ? 'Autorizo abrir esta turma e este ano no Smecel e fazer o login diretamente no site.' : 'Conferi a turma e o ano na janela separada e autorizo ler este diário para uma prévia local, sem envio.'}</label>}
      {prepared && <Button isDisabled={busy || !confirmation} onPress={() => { void perform(async () => checked(await (await bridge()).open_manual_session(session.generation, true))); }}>Abrir Smecel</Button>}
      {opened && <Button isDisabled={busy || !confirmation} onPress={() => { void capture(); }}>Ler diário manualmente</Button>}
    </>}
    {(live || active.current) && <Button variant="ghost" onPress={() => { void close(); }}>Encerrar sessão e descartar prévia</Button>}
    {error && <p role="alert" className="error-message">{error}</p>}
  </section>;
}
