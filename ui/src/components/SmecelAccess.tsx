import { useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { KeyRound } from 'lucide-react';
import { collectorBridge, checkedCollector, type CollectorStatus } from '../collector';

/** Write-only: the password goes to Windows protection and never comes back to the window. */
export default function SmecelAccess({ status, onStatus }: Readonly<{
  status: CollectorStatus | null; onStatus: (status: CollectorStatus) => void;
}>) {
  const [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const saved = status?.credential?.saved === true;
  async function run(work: () => Promise<CollectorStatus>, done: string) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { onStatus(await work()); setNotice(done); setPassword(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível concluir.'); }
    finally { setBusy(false); }
  }
  return <section className="panel source-panel" aria-labelledby="smecel-access-title">
    <div className="section-heading"><h2 id="smecel-access-title">Acesso ao Smecel</h2><KeyRound size={20} className="muted" aria-hidden="true" /></div>
    {saved ? <>
      <p>Acesso salvo: <strong>{status?.credential?.account}</strong>. Quando o Smecel desconectar, o Coletor entra sozinho.</p>
      <div className="source-actions"><Button variant="secondary" isDisabled={busy} onPress={() => { void run(async () => checkedCollector(await (await collectorBridge()).forget_source_credential()), 'Acesso removido deste computador.'); }}>Remover acesso salvo</Button></div>
    </> : <form className="credential-form" onSubmit={event => { event.preventDefault(); void run(async () => checkedCollector(await (await collectorBridge()).save_source_credential(email, password)), ''); }}>
      <p>Salve o e-mail e a senha do Smecel para o Coletor entrar sozinho nos horários de coleta.</p>
      <TextField value={email} onChange={setEmail} isDisabled={busy} isRequired type="email" autoComplete="off"><Label>E-mail do Smecel</Label><Input /></TextField>
      <TextField value={password} onChange={setPassword} isDisabled={busy} isRequired type="password" autoComplete="off"><Label>Senha do Smecel</Label><Input /></TextField>
      <div className="source-actions"><Button type="submit" isDisabled={busy || !email.trim() || !password}>Salvar acesso</Button></div>
      <p className="muted">Protegido pelo Windows deste usuário. Sair da conta do Ecossistema apaga o acesso salvo.</p>
    </form>}
    {notice && <output>{notice}</output>}
    {error && <p className="error-message" role="alert">{error}</p>}
  </section>;
}
