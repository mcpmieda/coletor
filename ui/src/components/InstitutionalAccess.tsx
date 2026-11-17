import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import { LogIn } from 'lucide-react';
import { bridgeReady, nativeApi } from '../api';
import { COLLECTOR_CODES } from '../collector';
import { onWindowVisibility, windowVisible } from '../desktop';
import { initializeLocalSettings } from '../localSettings';
import { paintTheme, readTheme } from '../theme';
import DesktopApp from '../desktop/DesktopApp';

interface LocalRecovery {
  pending: boolean; count: number | null; oldest: number | null;
  newest: number | null; unreadable: boolean;
  /** False while the queue waits for the live access to be opened (not a problem). */
  bound?: boolean;
}
export interface InstitutionalBridge {
  get_local_recovery_status(): Promise<LocalRecovery>;
  discard_local_pending_collection(): Promise<{ ok: true; discarded: boolean } | { error: string; code?: string }>;
  get_institutional_access_status(): Promise<{ authenticated: boolean; authorized: boolean; code?: string; pairingCode?: string }>;
  open_institutional_login(): Promise<{ ok: true } | { error: string; code?: string }>;
  logout_institutional_access(): Promise<{ ok: true } | { error: string; code?: string }>;
}
async function bridge(): Promise<InstitutionalBridge> {
  let native = await nativeApi();
  if (!native?.get_institutional_access_status && window.location.hash === '#coletor-desktop') {
    await bridgeReady(() => !!window.pywebview?.api?.get_institutional_access_status, 4000, 'O coletor não terminou de abrir.');
    native = await nativeApi();
  }
  if (!native?.get_institutional_access_status || !native.open_institutional_login || !native.logout_institutional_access || !native.get_local_recovery_status || !native.discard_local_pending_collection)
    throw new Error('O acesso institucional está disponível no programa Windows.');
  return native as InstitutionalBridge;
}
/** User-visible messages are based on fixed, nonsecret codes, never native error text. */
function loginFailureMessage(code?: string): string {
  const messages: Record<string, string> = {
    PAIRING_PENDING: 'Já existe uma solicitação de autorização neste computador. Confira o código exibido ou cancele a tentativa anterior.',
    ACCESS_UNAVAILABLE: 'Não foi possível consultar o servidor do Ecossistema. Confira a conexão com a internet.',
    LOGIN_UNAVAILABLE: 'O Windows não confirmou a abertura do navegador. Clique em Entrar no Ecossistema novamente para tentar abrir o mesmo pedido, sem apagar a chave.',
    ACCESS_NOT_CONFIGURED: 'O serviço de autorização do Ecossistema não está disponível ou configurado.',
    DEVICE_KEY_UNAVAILABLE: 'O Windows não conseguiu preparar a chave protegida deste perfil. Confira as permissões do dispositivo.',
    DEVICE_KEY_MISSING: 'A chave protegida do computador não foi encontrada. Não exclua arquivos; solicite suporte.',
    DEVICE_STATE_INVALID: 'O estado de segurança deste computador está inconsistente. Não exclua chaves nem lotes; solicite suporte.',
    ACCESS_CLEANUP_PENDING: 'Há uma limpeza de acesso pendente; conclua a saída antes de tentar novamente.',
    SERVER_REVOCATION_PENDING: 'A revogação do vínculo anterior ainda precisa ser concluída.',
    PENDING_BATCHES: 'Há lotes sem recibo. Confira os recibos e não exclua dados antes de trocar o acesso.',
    PROTECTED_STORAGE_UNAVAILABLE: 'Não foi possível conferir os lotes protegidos; nenhum dado deve ser descartado.',
    CANCELLED: 'Outra operação está em andamento. Aguarde antes de iniciar a autorização.',
    ACCESS_REQUIRED: 'O Coletor não conseguiu iniciar a autorização. Verifique o acesso do dispositivo.',
    INVALID_ACCESS_RESPONSE: 'O servidor retornou uma resposta inválida de autorização.',
    CLOCK_OUT_OF_SYNC: COLLECTOR_CODES.CLOCK_OUT_OF_SYNC,
  };
  const key = typeof code === 'string' && Object.hasOwn(messages, code) ? code : undefined;
  return key
    ? messages[key] + ' Código: ' + key + '.'
    : 'Não foi possível iniciar a autorização. Se persistir, solicite suporte.';
}
/** Answers that revoke nothing (no connection, a wrong Windows clock): the Coletor tries again by
 *  itself, so an open panel stays. Signing in again would pair this computer a second time. */
export const accessRetried = (code?: string) => code === 'ACCESS_UNAVAILABLE' || code === 'CLOCK_OUT_OF_SYNC';
/** How often a pending authorization request is asked about (a request lasts ten minutes). */
export const PAIRING_POLL_MS = 3000;
export default function InstitutionalAccess() {
  const [authorized, setAuthorized] = useState(false), [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('Verificando o acesso deste computador.');
  const [pairingCode, setPairingCode] = useState('');
  const [cleanupPending, setCleanupPending] = useState(false);
  const [recovery, setRecovery] = useState<LocalRecovery | null>(null);
  // Live-confirmed access (the panel may already show from the local summary).
  const [verified, setVerified] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState('');
  // The access check itself refused this computer's clock: said over the panel until it is right again.
  const [clockWrong, setClockWrong] = useState(false);
  const mounted = useRef(false), epoch = useRef(0), checking = useRef<number | null>(null), operation = useRef(false);
  const previouslyAuthorized = useRef(false);
  // Polling must not erase the result of a direct user-initiated login action.
  const loginFailure = useRef<string | null>(null);
  const recheck = useCallback(async () => {
    if (checking.current === epoch.current || operation.current || !mounted.current) return;
    const current = epoch.current;
    checking.current = current;
    try {
      const result = await (await bridge()).get_institutional_access_status();
      const local = await (await bridge()).get_local_recovery_status();
      if (!mounted.current || current !== epoch.current) return;
      setRecovery(local);
      setPairingCode(typeof result.pairingCode === 'string' && /^[0-9]{6}$/.test(result.pairingCode) ? result.pairingCode : '');
      setCleanupPending(result.code === 'SERVER_REVOCATION_PENDING');
      setClockWrong(result.code === 'CLOCK_OUT_OF_SYNC');
      if (result.authenticated === true && result.authorized === true) {
        if (!previouslyAuthorized.current) {
          await initializeLocalSettings();
          // Painted once, before the panel opens. A panel already open (from the local summary)
          // paints its own preference: a later check must never put an older theme back.
          if (!optimistic.current) paintTheme(readTheme());
        }
        const confirmed = await (await bridge()).get_institutional_access_status();
        if (!mounted.current || current !== epoch.current) return;
        if (confirmed.authenticated !== true || confirmed.authorized !== true) {
          previouslyAuthorized.current = false; setAuthorized(false); setVerified(false); setNotice('O acesso foi encerrado. Entre novamente no Ecossistema.'); return;
        }
        previouslyAuthorized.current = true; loginFailure.current = null; setAuthorized(true); setVerified(true); setNotice('');
      } else if (accessRetried(result.code) && (optimistic.current || previouslyAuthorized.current)) {
        // No connection or a wrong clock, at opening or after the access was confirmed: keep the
        // panel (from the local summary or as it is); the collector itself retries and never works
        // without live access. Any other answer is a real loss of access and falls to the entry screen below.
        setNotice('');
      } else {
        previouslyAuthorized.current = false; setAuthorized(false); setVerified(false); optimistic.current = false;
        if (!loginFailure.current) setNotice(result.code === 'ACCESS_NOT_CONFIGURED'
          ? 'A configuração do acesso ainda não foi concluída.'
          : result.code === 'ACCESS_CLEANUP_PENDING' ? 'A limpeza anterior ainda não terminou. Use Entrar no Ecossistema para repetir a verificação segura.'
          : result.code === 'SERVER_REVOCATION_PENDING' ? 'A revogação do dispositivo anterior ainda precisa ser confirmada no Ecossistema.'
          : result.code === 'CLOCK_OUT_OF_SYNC' ? COLLECTOR_CODES.CLOCK_OUT_OF_SYNC
          : result.pairingCode ? 'Pedido iniciado. No navegador, confira o código e clique em Autorizar este computador.'
          : 'Entre no Ecossistema para usar o coletor neste computador.');
      }
    } catch (error) {
      if (mounted.current && current === epoch.current && !optimistic.current) {
        previouslyAuthorized.current = false; setAuthorized(false); setVerified(false);
        if (!loginFailure.current) setNotice(error instanceof Error ? error.message : 'Não foi possível verificar o acesso.');
      }
    } finally { if (checking.current === current) checking.current = null; }
  }, []);
  const optimistic = useRef(false);
  useEffect(() => {
    mounted.current = true;
    // Instant opening: a computer authorized before shows its panel from the
    // local summary right away; the live check below confirms or closes it.
    void bridge().then(api => (api as InstitutionalBridge & { get_startup_snapshot?: () => Promise<{ paired: boolean; settings?: { theme?: string } }> })
      .get_startup_snapshot?.()).then(snapshot => {
        if (!mounted.current || !snapshot?.paired || previouslyAuthorized.current) return;
        const theme = snapshot.settings?.theme;
        if (theme === 'light' || theme === 'dark' || theme === 'system') paintTheme(theme);
        optimistic.current = true; setAuthorized(true); setNotice('');
      }).catch(() => undefined).finally(() => { void recheck(); });
    // Not while the window is hidden in the tray; checked again as soon as it is shown.
    const focus = () => { if (windowVisible()) void recheck(); };
    const timer = setInterval(focus, 30_000);
    const stopVisibility = onWindowVisibility(focus);
    window.addEventListener('focus', focus); window.addEventListener('online', focus); window.addEventListener('coletoraccesschanged', focus);
    return () => { mounted.current = false; epoch.current++; clearInterval(timer); stopVisibility();
      window.removeEventListener('focus', focus); window.removeEventListener('online', focus); window.removeEventListener('coletoraccesschanged', focus); };
  }, [recheck]);
  // A request waiting for the click in the browser is asked about often, shown or not: the panel
  // opens by itself a moment after "Autorizar este computador", with nothing to press here.
  useEffect(() => {
    if (!pairingCode) return;
    const timer = setInterval(() => { void recheck(); }, PAIRING_POLL_MS);
    return () => clearInterval(timer);
  }, [pairingCode, recheck]);
  async function login() {
    if (operation.current) return;
    operation.current = true; epoch.current++; loginFailure.current = null;
    setBusy(true); setNotice('Preparando a autorização no Windows e no Ecossistema.');
    try {
      const result = await (await bridge()).open_institutional_login();
      if ('error' in result) {
        loginFailure.current = loginFailureMessage(result.code);
        setNotice(loginFailure.current);
      } else {
        setNotice('Pedido preparado. No navegador, confira o código e clique em Autorizar este computador.');
      }
    } catch {
      // Never copy potentially sensitive native exceptions into the DOM.
      loginFailure.current = loginFailureMessage();
      setNotice(loginFailure.current);
    } finally {
      operation.current = false; setBusy(false); void recheck();
    }
  }
  async function logout() {
    if (operation.current) return;
    operation.current = true; epoch.current++; loginFailure.current = null; setBusy(true);
    let blockedByPendingBatch = false;
    try {
      const result = await (await bridge()).logout_institutional_access();
      if ('error' in result) {
        if (result.code === 'PENDING_BATCHES' || result.code === 'PROTECTED_STORAGE_UNAVAILABLE') {
          // The native operation did not revoke the device. Keep the authorized
          // UI visible and preserve this actionable message for the operator.
          blockedByPendingBatch = true; setNotice(result.error); setCleanupPending(false); return;
        }
        throw new Error(result.error);
      }
      previouslyAuthorized.current = false; optimistic.current = false; setAuthorized(false); setVerified(false);
      setNotice('Este computador foi desconectado.');
    } catch (error) {
      setCleanupPending(true);
      setNotice(error instanceof Error ? error.message : 'Confira a conexão para encerrar o vínculo.');
    } finally {
      operation.current = false; setBusy(false); setPairingCode('');
      if (!blockedByPendingBatch) void recheck();
    }
  }
  async function recoverLocal() {
    if (operation.current) return;
    operation.current = true; epoch.current++; setBusy(true); setRecoveryNotice('');
    try {
      const result = await (await bridge()).discard_local_pending_collection();
      if ('error' in result) setRecoveryNotice(result.error);
      else setRecoveryNotice(result.discarded
        ? 'Fila local descartada mediante confirmação do Windows. Faça uma nova coleta para recuperar as informações ausentes.'
        : 'Não havia lotes locais pendentes.');
      setRecovery(await (await bridge()).get_local_recovery_status());
    } catch { setRecoveryNotice('Falha ao conferir a fila local. Nenhum descarte foi confirmado.'); }
    finally { operation.current = false; setBusy(false); void recheck(); }
  }
  function recoveryPanel() {
    if (!recovery?.pending) return null;
    const date = (value: number | null) => value === null ? 'desconhecida'
      : new Date(value * 1000).toLocaleString('pt-BR');
    return <section className="panel" aria-label="Recuperação de lotes locais">
      <p role="alert">Há {recovery.count === null ? 'lotes cifrados de quantidade desconhecida' : `${recovery.count} lote(s)`} sem recibo.
        Primeiro: {date(recovery.oldest)}. Último: {date(recovery.newest)}.</p>
      <p>Quando a autorização for revogada, não é possível consultar recibos.
        O descarte local pode perder registros que ainda não chegaram ao Centro.
        Só prossiga após conferir com a administração. Será exigida confirmação do Windows.</p>
      <Button variant="secondary" isDisabled={busy} onPress={() => { void recoverLocal(); }}>
        Descartar fila local com confirmação do Windows
      </Button>
    </section>;
  }
  // Authorized: the collector reconciles, supersedes or sets aside the local
  // queue by itself. Only a queue still unreadable after it was opened with
  // the live access (bound) asks a person.
  if (authorized) return <>{verified && recovery?.pending && recovery.unreadable && recovery.bound !== false && <div className="p-4">{recoveryPanel()}</div>}{recoveryNotice && <p role="alert" className="p-4">{recoveryNotice}</p>}{clockWrong && <p role="alert" className="p-4">{COLLECTOR_CODES.CLOCK_OUT_OF_SYNC}</p>}<DesktopApp /></>;
  return <main className="institutional-entry"><section className="panel" aria-labelledby="institutional-title">
    <img src="./mascot/head.png" width="52" height="52" alt="" />
    <h1 id="institutional-title">Entrar no Ecossistema</h1><p>Autorize este computador para usar o Coletor.</p>
    <Button isDisabled={busy} onPress={() => { void login(); }}><LogIn size={18} />{pairingCode ? "Abrir navegador novamente" : "Entrar no Ecossistema"}</Button>
    <Button variant="ghost" isDisabled={busy} onPress={() => { void recheck(); }}>Verificar acesso</Button>
    {(pairingCode || cleanupPending) && <Button variant="ghost" isDisabled={busy} onPress={() => { void logout(); }}>{cleanupPending ? 'Concluir saída' : 'Cancelar autorização'}</Button>}
    {recoveryPanel()}
    {recoveryNotice && <p role="alert">{recoveryNotice}</p>}
    {notice && <p role="status">{notice}</p>}<p className="muted">O login é feito no navegador. Não informe sua senha neste programa.</p>
    {pairingCode && <p role="status">O navegador deve mostrar este mesmo código: <strong>{pairingCode}</strong></p>}
  </section></main>;
}
