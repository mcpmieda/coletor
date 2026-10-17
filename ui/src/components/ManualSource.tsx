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
  useEffect(() => () => { operation.current++; }, []);
  useEffect(() => {
    let alive = true;
    const timer = setInterval(() => {
      if (active.current || closing.current) return;
      void window.pywebview?.api.get_manual_session_status?.().then(status => {
        if (!alive || active.current || closing.current) return;
        if (status.state === 'closed') { setSession(status); setCatalog(null); setClassId(''); }
      }).catch(() => undefined);
    }, 20_000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
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
  /** One click: open the isolated Edge, sign in with the saved access and read the list. */
  async function load() {
    setCatalog(null); setClassId(''); onClear();
    await perform(async () => {
      const id=operation.current, api=await bridge();
      let current=session;
      if(!current || current.state==='closed' || current.cleanup_pending){
        const prepared=checked(await api.prepare_manual_login(Number(year)));
        if(id!==operation.current){await api.close_manual_session();throw new Error('Abertura cancelada.');}
        current=checked(await api.open_manual_session(prepared.generation, true));
        if(id!==operation.current){await api.close_manual_session();throw new Error('Abertura cancelada.');}
        setSession(current);
      }
      return checked(await api.discover_manual_classes(current.generation, true));
    });
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
  async function selectAll(all: boolean) {
    if (!catalog || !session || active.current || busy) return;
    const ids=all ? catalog.catalog.classes.map(item=>item.class_id) : [];
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
  const selected=catalog?.selected_class_ids.length ?? 0, total=catalog?.catalog.classes.length ?? 0;
  return <section className="panel source-panel" aria-labelledby="manual-source-title">
    <div className="section-heading"><div><h2 id="manual-source-title">Turmas deste computador</h2>
      <p>O Coletor abre o Smecel, entra com o acesso salvo e mostra a lista. As escolhas ficam salvas.</p></div></div>
    <div className="manual-controls"><TextField className="manual-year" value={year} onChange={v=>{yearEdited.current=true;setYear(v);}} isDisabled={busy || !!live}><Label>Ano letivo</Label><Input inputMode="numeric" maxLength={4}/></TextField>
      <Button isDisabled={busy || !/^\d{4}$/.test(year)} onPress={()=>{void load();}}>{busy && !catalog ? 'Carregando turmas…' : catalog ? 'Recarregar turmas' : 'Carregar turmas do Smecel'}</Button>
      {live && <Button variant="ghost" onPress={()=>{void close();}}>Fechar o Smecel</Button>}
    </div>
    {opened && !catalog && error && <output>Se o Smecel pedir, entre na janela do Edge e clique em Carregar turmas de novo.</output>}
    {catalog && <>
      <div className="class-toolbar"><output>{catalog.catalog.context_label} · Ano {session?.scope?.year} · {selected} de {total} turma(s) escolhida(s){catalog.catalog.filtered ? ' · lista filtrada' : ''}</output>
        <div className="source-actions"><Button size="sm" variant="secondary" isDisabled={busy || selected===total} onPress={()=>{void selectAll(true);}}>Marcar todas</Button><Button size="sm" variant="ghost" isDisabled={busy || selected===0} onPress={()=>{void selectAll(false);}}>Desmarcar todas</Button></div></div>
      <fieldset className="class-choices" disabled={busy}><legend className="sr-only">Turmas deste computador</legend>{catalog.catalog.classes.map(item=><label className="class-choice" key={item.class_id}><input type="checkbox" aria-label={`Selecionar ${item.name}`} checked={catalog.selected_class_ids.includes(item.class_id)} onChange={e=>{void toggle(item.class_id,e.target.checked);}}/>{item.name}<span className="muted">{item.shift}</span></label>)}</fieldset>
      {catalog.unavailable_class_ids.length>0 && <output>{catalog.unavailable_class_ids.length} turma(s) escolhida(s) não aparece(m) nesta lista.</output>}
      {catalog.notice && <output>{catalog.notice}</output>}
      <details className="manual-check"><summary>Conferir uma turma sem enviar</summary>
        <label className="manual-select"><span>Turma para conferir</span><select aria-label="Turma para conferir" value={classId} disabled={busy} onChange={e=>{setClassId(e.target.value);setConfirmation(false);onClear();}}><option value="">Escolha uma turma marcada</option>{catalog.catalog.classes.filter(item=>catalog.selected_class_ids.includes(item.class_id)).map(item=><option value={item.class_id} key={item.class_id}>{item.name}</option>)}</select></label>
        <label className="consent"><input type="checkbox" checked={confirmation} disabled={busy || !classId} onChange={e=>setConfirmation(e.target.checked)}/>Autorizo ler este diário só para conferir aqui.</label>
        <Button isDisabled={busy || !classId || !confirmation} onPress={()=>{void capture();}}>Ler diário</Button>
      </details>
    </>}
    {error && <p role="alert" className="error-message">{error}</p>}
  </section>;
}
