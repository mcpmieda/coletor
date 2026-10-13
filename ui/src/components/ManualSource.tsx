import { useEffect, useRef, useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import { nativeApi } from '../api';
import type { Preview } from '../types';

export interface ManualStatus {
  generation: number; state: string; cleanup_pending?: boolean;
  scope: { class_id?: string; year: number; url: string } | null;
  identity_verified: false; transmission_enabled: false; notice: string;
}
interface SchoolClass { class_id: string; year: number; name: string; stage: string; matrix: string; shift: string }
interface CatalogReply {
  session: ManualStatus; catalog: { classes: SchoolClass[]; context_label: string; filtered: boolean; list_complete_verified: false };
  selected_class_ids: string[]; unavailable_class_ids: string[]; selection_revision: number; notice: string;
}
type Failure = { error: string };
export interface ManualBridge {
  get_manual_class_selection_preferences(): Promise<{ last_year: number | null; revalidation_required: true; notice: string }>;
  prepare_manual_login(year: number): Promise<ManualStatus | Failure>;
  open_manual_session(generation: number, confirmed: boolean): Promise<ManualStatus | Failure>;
  discover_manual_classes(generation: number, confirmed: boolean): Promise<CatalogReply | Failure>;
  save_manual_class_selection(generation: number, ids: string[], revision: number): Promise<CatalogReply | Failure>;
  clear_manual_class_selection(generation: number, revision: number): Promise<CatalogReply | Failure>;
  capture_selected_class(generation: number, classId: string, confirmed: boolean): Promise<{ session: ManualStatus; preview: Preview } | Failure>;
  close_manual_session(): Promise<ManualStatus | Failure>;
  get_manual_session_status(): Promise<ManualStatus>;
}
function checked<T>(result: T | Failure): T {
  if (typeof result === 'object' && result !== null && 'error' in result) throw new Error(String(result.error));
  return result as T;
}
async function bridge(): Promise<ManualBridge> {
  const api = await nativeApi();
  if (!api?.prepare_manual_login || !api.discover_manual_classes || !api.capture_selected_class) {
    throw new Error('O acesso ao Smecel está disponível no programa Windows. Aqui você pode conferir arquivos e exemplos.');
  }
  return api as ManualBridge;
}
export default function ManualSource({ busy, onBusy, onRead, onClear }: {
  busy: boolean; onBusy: (value: boolean) => void; onRead: (work: () => Promise<Preview>) => Promise<void>; onClear: () => void;
}) {
  const [year, setYear] = useState('2026');
  const [session, setSession] = useState<ManualStatus | null>(null);
  const [catalog, setCatalog] = useState<CatalogReply | null>(null);
  const [classId, setClassId] = useState('');
  const [confirmation, setConfirmation] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(false), operation = useRef(0), closing = useRef(false);
  const yearEdited=useRef(false);
  useEffect(()=>{let current=true;void nativeApi().then(api=>api?.get_manual_class_selection_preferences?.()).then(prefs=>{
    if(current && !yearEdited.current && prefs?.last_year)setYear(String(prefs.last_year));
  }).catch(()=>undefined);return()=>{current=false;};},[]);
  useEffect(() => () => { operation.current++; void window.pywebview?.api.close_manual_session?.().catch(() => undefined); }, []);
  async function perform(work: () => Promise<ManualStatus | CatalogReply>) {
    if (active.current || busy || closing.current) return;
    active.current = true; onBusy(true); setError('');
    const id = ++operation.current;
    try {
      const result = await work();
      if (id === operation.current) {
        if ('catalog' in result) {
          setCatalog(result); setSession(result.session);
          if (!result.selected_class_ids.includes(classId)) setClassId(result.selected_class_ids[0] ?? '');
        } else setSession(result);
        setConfirmation(false);
      }
    } catch (e) { if (id === operation.current) { setError(e instanceof Error ? e.message : 'Não foi possível carregar as turmas.'); } }
    finally { active.current = false; onBusy(false); }
  }
  async function enter() {
    if (!confirmation) return;
    await perform(async () => {
      const id=operation.current, api=await bridge();
      if(id!==operation.current)throw new Error('Abertura cancelada.');
      const prepared=checked(await api.prepare_manual_login(Number(year)));
      if(id!==operation.current){await api.close_manual_session();throw new Error('Abertura cancelada.');}
      return checked(await api.open_manual_session(prepared.generation, true));
    });
  }
  async function discover() {
    if (!session) return;
    setCatalog(null); setClassId(''); onClear();
    await perform(async () => checked(await (await bridge()).discover_manual_classes(session.generation, true)));
  }
  async function close() {
    if (closing.current) return;
    closing.current = true; operation.current++; onClear(); setCatalog(null); setClassId(''); setConfirmation(false); setError('');
    try { setSession(checked(await (await bridge()).close_manual_session())); }
    catch {
      const status=await window.pywebview?.api.get_manual_session_status?.().catch(()=>undefined);
      if(status)setSession(status); setError('A limpeza não terminou. Encerre a sessão novamente antes de preparar outra.');
    } finally { closing.current = false; }
  }
  async function toggle(key: string, selected: boolean) {
    if (!catalog || !session || active.current || busy) return;
    const ids=selected ? [...catalog.selected_class_ids,key] : catalog.selected_class_ids.filter(id=>id!==key);
    onClear();setConfirmation(false);
    await perform(async()=>checked(await (await bridge()).save_manual_class_selection(session.generation,ids,catalog.selection_revision)));
  }
  async function capture() {
    if (!session || !classId || !confirmation || active.current || busy || closing.current) return;
    const generation=session.generation, id=++operation.current;
    active.current=true; setError(''); setConfirmation(false);
    try { await onRead(async()=>{
      const result=checked(await (await bridge()).capture_selected_class(generation,classId,true));
      if(id!==operation.current)throw new Error('Leitura descartada.');
      setSession(result.session);return result.preview;
    }); } finally { active.current=false; }
  }
  const live=!!session && (session.state!=='closed' || session.cleanup_pending);
  const opened=live && session.state!=='prepared' && session.state!=='opening' && !session.cleanup_pending;
  return <section className="panel source-panel" aria-labelledby="manual-source-title">
    <h2 id="manual-source-title">Entrar no Smecel e escolher turmas</h2>
    <p>Entre na janela separada do Edge, carregue as turmas e marque as que quer usar. Suas escolhas ficam salvas neste computador, por ano e contexto; a disponibilidade é conferida novamente em cada acesso.</p>
    <p className="muted">Senha, cookies e sessão não são salvos. Envio e coleta automática estão desligados. A lista observada não comprova todas as turmas da escola nem a identidade da conta.</p>
    <div className="source-controls"><TextField value={year} onChange={v=>{yearEdited.current=true;setYear(v);}} isDisabled={busy || !!live}><Label>Ano letivo no Smecel</Label><Input inputMode="numeric" maxLength={4}/></TextField>
      {!live && <><label className="status-line"><input type="checkbox" checked={confirmation} disabled={busy} onChange={e=>setConfirmation(e.target.checked)}/>Autorizo abrir o Smecel e ler a lista de turmas deste ano, sem envio.</label><Button isDisabled={busy || !confirmation} onPress={()=>{void enter();}}>Entrar no Smecel</Button></>}
      {opened && <Button isDisabled={busy} onPress={()=>{void discover();}}>Carregar turmas</Button>}
    </div>
    {opened && !catalog && <p role="status">Faça o login diretamente no site. Depois clique em Carregar turmas. Nenhum código de turma precisa ser digitado.</p>}
    {catalog && <>
      <p role="status">{catalog.catalog.context_label} · Ano {session?.scope?.year}</p>
      <p>{catalog.catalog.classes.length} turmas observadas na página atual. {catalog.catalog.filtered ? 'A lista está filtrada ou parcial. ' : ''}Turmas ausentes continuam salvas, mas não ficam disponíveis para leitura.</p>
      <fieldset className="class-choices" disabled={busy}><legend>Turmas para usar neste computador</legend>{catalog.catalog.classes.map(item=><label className="status-line" key={item.class_id}><input type="checkbox" aria-label={`Selecionar ${item.name}`} checked={catalog.selected_class_ids.includes(item.class_id)} onChange={e=>{void toggle(item.class_id,e.target.checked);}}/>{item.name}<span className="muted">{item.shift}</span></label>)}</fieldset>
      <p role="status">Seleção salva automaticamente. {catalog.unavailable_class_ids.length>0 ? `${catalog.unavailable_class_ids.length} escolhas anteriores aguardam revalidação em uma lista onde estejam visíveis.` : ''}</p>
      {catalog.notice && <p role="status">{catalog.notice}</p>}
      <label className="status-line">Turma para conferir<select aria-label="Turma para conferir" value={classId} disabled={busy} onChange={e=>{setClassId(e.target.value);setConfirmation(false);onClear();}}><option value="">Escolha uma turma marcada</option>{catalog.catalog.classes.filter(item=>catalog.selected_class_ids.includes(item.class_id)).map(item=><option value={item.class_id} key={item.class_id}>{item.name}</option>)}</select></label>
      <label className="status-line"><input type="checkbox" checked={confirmation} disabled={busy || !classId} onChange={e=>setConfirmation(e.target.checked)}/>Autorizo ler o diário desta turma e deste ano para uma prévia local, sem envio.</label>
      <Button isDisabled={busy || !classId || !confirmation} onPress={()=>{void capture();}}>Ler diário manualmente</Button>
      <Button variant="ghost" isDisabled={busy} onPress={()=>{if(session)void perform(async()=>checked(await (await bridge()).clear_manual_class_selection(session.generation,catalog.selection_revision)));}}>Limpar seleção deste ano e contexto</Button>
    </>}
    {(live || active.current) && <Button variant="ghost" onPress={()=>{void close();}}>Encerrar sessão e descartar prévia</Button>}
    {error && <p role="alert" className="error-message">{error}</p>}
  </section>;
}
