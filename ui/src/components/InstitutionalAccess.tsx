import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import { ShieldCheck, LogIn } from 'lucide-react';
import { nativeApi } from '../api';
import { initializeLocalSettings } from '../localSettings';
import { paintTheme, readTheme } from '../theme';
import App from '../App';

export interface InstitutionalBridge {
  get_institutional_access_status(): Promise<{ authenticated: boolean; authorized: boolean; code?: string }>;
  open_institutional_login(): Promise<{ ok: true } | { error: string; code?: string }>;
  logout_institutional_access(): Promise<{ ok: true } | { error: string; code?: string }>;
}
async function bridge(): Promise<InstitutionalBridge> {
  let native = await nativeApi();
  if (!native?.get_institutional_access_status && window.location.hash === '#coletor-desktop') {
    await new Promise<void>((resolve, reject) => {
      const ready = () => { clearTimeout(timer); resolve(); };
      const timer = setTimeout(() => { window.removeEventListener('pywebviewready', ready); reject(new Error('O coletor não terminou de abrir.')); }, 4000);
      window.addEventListener('pywebviewready', ready, { once: true });
      if (window.pywebview?.api?.get_institutional_access_status) {
        window.removeEventListener('pywebviewready', ready); ready();
      }
    });
    native = await nativeApi();
  }
  if (!native?.get_institutional_access_status || !native.open_institutional_login || !native.logout_institutional_access)
    throw new Error('O acesso institucional está disponível no programa Windows.');
  return native as InstitutionalBridge;
}
export default function InstitutionalAccess() {
  const [authorized, setAuthorized] = useState(false), [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('Verificando o acesso deste computador.');
  const mounted = useRef(false), epoch = useRef(0), checking = useRef<number | null>(null), operation = useRef(false);
  const previouslyAuthorized = useRef(false);
  const recheck = useCallback(async () => {
    if (checking.current === epoch.current || operation.current || !mounted.current) return;
    const current = epoch.current;
    checking.current = current;
    try {
      const result = await (await bridge()).get_institutional_access_status();
      if (!mounted.current || current !== epoch.current) return;
      if (result.authenticated === true && result.authorized === true) {
        if (!previouslyAuthorized.current) await initializeLocalSettings();
        const confirmed = await (await bridge()).get_institutional_access_status();
        if (!mounted.current || current !== epoch.current) return;
        if (confirmed.authenticated !== true || confirmed.authorized !== true) {
          previouslyAuthorized.current = false; setAuthorized(false); setNotice('O acesso foi encerrado. Entre novamente no Ecossistema.'); return;
        }
        previouslyAuthorized.current = true; paintTheme(readTheme()); setAuthorized(true); setNotice('');
      } else {
        previouslyAuthorized.current = false; setAuthorized(false);
        setNotice(result.code === 'ACCESS_NOT_CONFIGURED' ? 'A configuração do acesso ainda não foi concluída.'
          : 'Entre no Ecossistema para usar o coletor neste computador.');
      }
    } catch (error) {
      if (mounted.current && current === epoch.current) {
        previouslyAuthorized.current = false; setAuthorized(false); setNotice(error instanceof Error ? error.message : 'Não foi possível verificar o acesso.');
      }
    } finally { if (checking.current === current) checking.current = null; }
  }, []);
  useEffect(() => {
    mounted.current = true; void recheck();
    const focus = () => { if (document.visibilityState !== 'hidden') void recheck(); };
    const timer = setInterval(focus, 30_000);
    window.addEventListener('focus', focus); window.addEventListener('online', focus); window.addEventListener('coletoraccesschanged', focus);
    return () => { mounted.current = false; epoch.current++; clearInterval(timer);
      window.removeEventListener('focus', focus); window.removeEventListener('online', focus); window.removeEventListener('coletoraccesschanged', focus); };
  }, [recheck]);
  async function login() {
    if (operation.current) return;
    operation.current = true; epoch.current++; setBusy(true); setNotice('Continue no navegador do Ecossistema.');
    try {
      const result = await (await bridge()).open_institutional_login();
      if ('error' in result) throw new Error(result.code === 'ACCESS_NOT_CONFIGURED'
        ? 'A configuração do acesso ainda não foi concluída.' : result.error);
    } catch (error) { setNotice(error instanceof Error ? error.message : 'Não foi possível abrir o acesso.'); }
    finally { operation.current = false; setBusy(false); void recheck(); }
  }
  async function logout() {
    if (operation.current) return;
    operation.current = true; previouslyAuthorized.current = false; epoch.current++; setAuthorized(false); setBusy(true);
    try {
      const result = await (await bridge()).logout_institutional_access();
      if ('error' in result) throw new Error(result.error);
      setNotice('Este computador foi desconectado.');
    } catch (error) { setNotice(error instanceof Error ? error.message : 'Confira a conexão para encerrar o vínculo.'); }
    finally { operation.current = false; setBusy(false); }
  }
  if (authorized) return <><div className="institutional-account"><span><ShieldCheck size={16} />Acesso ao coletor autorizado</span><Button size="sm" variant="ghost" isDisabled={busy} onPress={() => { void logout(); }}>Sair da conta</Button></div><App /></>;
  return <main className="institutional-entry"><section className="panel" aria-labelledby="institutional-title">
    <img src="./mascot/head.png" width="52" height="52" alt="" />
    <h1 id="institutional-title">Entrar no Ecossistema</h1><p>Autorize este computador para usar o Coletor de Frequência.</p>
    <Button isDisabled={busy} onPress={() => { void login(); }}><LogIn size={18} />Entrar no Ecossistema</Button>
    <Button variant="ghost" isDisabled={busy} onPress={() => { void recheck(); }}>Verificar acesso</Button>
    {notice && <p role="status">{notice}</p>}<p className="muted">O login é feito no navegador. Não informe sua senha neste programa.</p>
  </section></main>;
}
