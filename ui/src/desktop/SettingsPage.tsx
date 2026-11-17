import { useEffect, useRef, useState } from 'react';
import { Button, Card, Chip, Modal, ToggleButton, ToggleButtonGroup } from '@heroui/react';
import { notify } from './foxSay';
import { CheckCircle2, KeyRound, ListChecks, LogOut, Monitor, Moon, RefreshCw, Sun, Trash2, XCircle } from 'lucide-react';
import ManualSource from '../components/ManualSource';
import { paintTheme, type ThemeMode } from '../theme';
import { call, type Preferences, type Status } from './bridge';
import { closeProblem, type ManualCloseResult } from './manualClose';
import { updateMessage } from './update';
import { SwitchRow, TextInput } from './ui';
import type { ColetorState } from './useColetor';

function Check({ ok, label, detail }: Readonly<{ ok: boolean; label: string; detail?: string }>) {
  return (
    <div className="flex items-center gap-3 py-2">
      {ok ? <CheckCircle2 size={17} className="text-success" /> : <XCircle size={17} className="text-danger" />}
      <span className="text-sm">{label}</span>
      {detail && <span className="ml-auto truncate text-xs text-muted">{detail}</span>}
    </div>
  );
}

/** tray: what the window already read for its "Ocultar na bandeja" button. Asking again here cost,
 *  every 10 s while Ajustes was open, two access checks in the Ecossistema and a schtasks process. */
export default function SettingsPage({ state, tray }: Readonly<{ state: ColetorState; tray: { available: boolean; autostart: boolean } }>) {
  const { status, prefs, setStatus, setPrefs, refresh } = state;
  const [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [changing, setChanging] = useState(false), [busy, setBusy] = useState(false);
  const [choosing, setChoosing] = useState(false), [leaving, setLeaving] = useState(false), [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState(''), closingRef = useRef(false);
  // The tray menu changes preferences too: read again when Ajustes opens, unless one was saved here meanwhile.
  const prefSaved = useRef(false);
  useEffect(() => {
    void call(api => api.get_local_settings()).then(r => { if (!prefSaved.current) setPrefs(r.settings); }).catch(() => undefined);
  }, [setPrefs]);
  const [checking, setChecking] = useState(false);
  // The Coletor asks GitHub now; a newer version installs itself, as the automatic update does.
  async function checkUpdate() {
    if (checking) return;
    setChecking(true);
    try {
      const result = await call(api => api.check_for_update());
      (result.state === 'unavailable' ? notify : notify.success)(updateMessage(result));
    } catch (e) { notify.danger(e instanceof Error ? e.message : 'Não foi possível verificar as atualizações.'); }
    finally { setChecking(false); }
  }
  const saved = status?.credential?.saved === true;
  const mode = prefs?.classes.mode ?? status?.classesMode ?? 'all';

  /** Resolves to whether the work was done (false: another one was going on, or it failed and the fox said so). */
  async function run<T>(work: Parameters<typeof call<T>>[0], done?: (value: T) => void, message?: string) {
    if (busy) return false;
    setBusy(true);
    try { const value = await call(work); done?.(value); if (message) notify.success(message); return true; }
    catch (e) { notify.danger(e instanceof Error ? e.message : 'Não foi possível concluir.'); return false; }
    finally { setBusy(false); }
  }
  // Closing the choice ends the Smecel session it opened (and resumes collection).
  // The dialog only goes away once the session is confirmed closed.
  async function finishChoosing() {
    if (closingRef.current) return;
    closingRef.current = true; setClosing(true); setCloseError('');
    try {
      const api = window.pywebview?.api as { close_manual_session?: () => Promise<ManualCloseResult> } | undefined;
      if (!api?.close_manual_session) throw new Error('O Coletor não está disponível nesta janela.');
      const problem = closeProblem(await api.close_manual_session());
      if (problem) throw new Error(problem);
      setChoosing(false);
    } catch (e) {
      setCloseError(e instanceof Error ? e.message : 'Não foi possível fechar o Smecel.');
    } finally { closingRef.current = false; setClosing(false); void refresh(); }
  }
  const pref = (work: Parameters<typeof call<{ settings: Preferences }>>[0], message?: string) =>
    run(work, (r: { settings: Preferences }) => { prefSaved.current = true; setPrefs(r.settings); void refresh(); }, message);

  return (
    <div className="grid grid-cols-2 gap-4">
      <Card>
        <Card.Header>
          <Card.Title>Acesso ao Smecel</Card.Title>
          <Card.Description>O Coletor entra sozinho no Smecel nos horários. A senha fica protegida pelo Windows e nunca volta para esta janela.</Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col gap-3">
          {saved && !changing ? (
            <Check ok label="Acesso salvo" detail={status?.credential?.account} />
          ) : (
            <form className="flex flex-col gap-3" onSubmit={e => { e.preventDefault(); void run(api => api.save_source_credential(email, password), (s: Status) => { setStatus(s); setChanging(false); setPassword(''); }, 'Acesso ao Smecel salvo'); }}>
              <TextInput label="E-mail do Smecel" value={email} onChange={setEmail} type="email" autoComplete="off" />
              <TextInput label="Senha do Smecel" value={password} onChange={setPassword} type="password" autoComplete="off" />
              <div className="flex gap-2">
                <Button type="submit" size="sm" variant="primary" isPending={busy} isDisabled={!email.trim() || !password}><KeyRound size={15} /> Salvar acesso</Button>
                {changing && <Button size="sm" variant="tertiary" onPress={() => { setChanging(false); setPassword(''); }}>Cancelar</Button>}
              </div>
            </form>
          )}
        </Card.Content>
        {saved && !changing && (
          <Card.Footer className="flex gap-2">
            <Button size="sm" variant="secondary" onPress={() => setChanging(true)}>Trocar acesso</Button>
            <Button size="sm" variant="ghost" onPress={() => { void run(api => api.forget_source_credential(), setStatus, 'Acesso removido deste computador'); }}><Trash2 size={15} /> Remover</Button>
          </Card.Footer>
        )}
      </Card>

      <Card>
        <Card.Header>
          <Card.Title>Turmas</Card.Title>
          <Card.Description>Com “Todas”, uma turma nova no Smecel entra sozinha na próxima coleta.</Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col gap-3">
          <ToggleButtonGroup size="sm" selectionMode="single" disallowEmptySelection selectedKeys={[mode]}
            onSelectionChange={k => { const m = String([...k][0]) as 'all' | 'chosen'; if (m !== mode) void pref(api => api.save_classes_mode(m)); }}>
            <ToggleButton id="all">Todas as turmas da escola</ToggleButton>
            <ToggleButton id="chosen">Somente as escolhidas</ToggleButton>
          </ToggleButtonGroup>
          {mode === 'chosen' && <span className="text-sm text-muted">{status?.selectedClasses ?? 0} turma(s) escolhida(s) neste computador.</span>}
        </Card.Content>
        {mode === 'chosen' && (
          <Card.Footer><Button size="sm" variant="secondary" onPress={() => setChoosing(true)}><ListChecks size={15} /> Escolher turmas</Button></Card.Footer>
        )}
      </Card>

      <Card>
        <Card.Header>
          <Card.Title>Coleta em segundo plano</Card.Title>
          <Card.Description>O Coletor fica ao lado do relógio e coleta sozinho, mesmo com esta janela fechada.</Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col">
          <Check ok={!!status?.active} label={status?.active ? 'Coleta automática ativa' : 'Coleta automática desligada'} />
          <Check ok={tray.autostart} label="Inicia sozinho ao entrar no Windows" />
          <Check ok={tray.available} label="Ícone perto do relógio" />
          <div className="mt-2 flex flex-col divide-y divide-separator border-t border-separator pt-1">
            <SwitchRow label="Mostrar o navegador durante a coleta" hint="Desligado, o Smecel é lido sem abrir janelas. Sem acesso salvo, a janela aparece para você entrar."
              value={prefs?.browser.visible ?? false} isDisabled={!prefs} onChange={v => { void pref(api => api.save_browser_preference(v)); }} />
            <SwitchRow label="Mostrar notificações" hint="Avisos ao lado do relógio quando algo precisa de você"
              value={prefs?.notifications?.show ?? true} isDisabled={!prefs} onChange={v => { void pref(api => api.save_notifications(v)); }} />
            <SwitchRow label="Pausar a coleta neste computador" hint="Os outros computadores da escola continuam coletando"
              value={!!status?.localPaused} isDisabled={!status?.active} onChange={v => { void run(api => api.pause_collector(v), setStatus); }} />
          </div>
        </Card.Content>
      </Card>

      <Card>
        <Card.Header>
          <Card.Title>Aparência</Card.Title>
          <Card.Description>Automático acompanha o tema do Windows.</Card.Description>
        </Card.Header>
        <Card.Footer>
          {/* Shown at once (saving asks the Ecossistema first) and put back when it was not saved. */}
          <ToggleButtonGroup size="sm" selectionMode="single" disallowEmptySelection selectedKeys={[prefs?.theme ?? 'system']}
            onSelectionChange={k => { const m = String([...k][0]) as ThemeMode, kept = prefs?.theme ?? 'system'; if (m === kept) return;
              paintTheme(m); void pref(api => api.save_theme(m)).then(done => { if (!done) paintTheme(kept); }); }}>
            <ToggleButton id="system"><Monitor size={14} /> Automático</ToggleButton>
            <ToggleButton id="light"><Sun size={14} /> Claro</ToggleButton>
            <ToggleButton id="dark"><Moon size={14} /> Escuro</ToggleButton>
          </ToggleButtonGroup>
        </Card.Footer>
      </Card>

      <Card>
        <Card.Header>
          <Card.Title>Este computador</Card.Title>
          <Card.Description>Autorizado no Ecossistema. Sair apaga o acesso salvo do Smecel e a fila deste computador.</Card.Description>
        </Card.Header>
        <Card.Content><Check ok label="Acesso ao coletor autorizado" /></Card.Content>
        <Card.Footer><Button size="sm" variant="danger-soft" onPress={() => setLeaving(true)}><LogOut size={15} /> Sair da conta</Button></Card.Footer>
      </Card>

      <Card>
        <Card.Content className="flex flex-row items-center gap-4">
          <img src="./mascot/head.png" alt="" width={48} height={48} className="size-12 shrink-0 rounded-xl bg-accent-soft p-1" style={{ imageRendering: 'pixelated' }} />
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="font-semibold">Coletor</span>
            <span className="text-sm text-muted">{state.version ? `Versão ${state.version} · ` : ''}Ecossistema Escolar</span>
          </div>
          <Chip size="sm" variant="soft" color={status?.active ? 'success' : 'default'}>{status?.active ? 'Coleta ativa' : 'Coleta desligada'}</Chip>
        </Card.Content>
        <Card.Footer>
          <Button size="sm" variant="secondary" isPending={checking} onPress={() => { void checkUpdate(); }}><RefreshCw size={15} /> Verificar atualizações</Button>
        </Card.Footer>
      </Card>

      <Modal.Backdrop isOpen={choosing} onOpenChange={open => { if (!open) void finishChoosing(); }} variant="blur">
        <Modal.Container size="lg" scroll="inside">
          <Modal.Dialog className="max-h-[88vh]">
            <Modal.Header><Modal.Heading>Escolher turmas</Modal.Heading></Modal.Header>
            <Modal.Body><ManualSource onChanged={() => { void refresh(); }} /></Modal.Body>
            <Modal.Footer className="flex items-center gap-3">
              {closeError && <span role="alert" className="mr-auto text-sm text-danger">{closeError}</span>}
              <Button variant="primary" isPending={closing} onPress={() => { void finishChoosing(); }}>{closeError ? 'Tentar fechar de novo' : 'Concluir'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>

      <Modal.Backdrop isOpen={leaving} onOpenChange={setLeaving}>
        <Modal.Container size="sm">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>Sair da conta neste computador?</Modal.Heading></Modal.Header>
            <Modal.Body><p className="text-sm text-muted">A coleta automática para aqui. Para voltar, entre de novo no Ecossistema.</p></Modal.Body>
            <Modal.Footer>
              <Button variant="tertiary" onPress={() => setLeaving(false)}>Cancelar</Button>
              <Button variant="danger" onPress={() => { void run(api => api.logout_institutional_access(), () => window.location.reload()); }}>Sair</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </div>
  );
}
