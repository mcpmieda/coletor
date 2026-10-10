import { useEffect, useRef, useState } from 'react';
import { INITIAL_FOX, POSE_POSITION, beginAction, foxPose, nextFox, type FoxActivity } from '../mascot/animation';
import { DEFAULT_FOX, FOX_KEY, readFoxPreferences } from '../mascot/preferences';

const CAPTIONS: Record<FoxActivity, string> = { idle:'Pronta para ajudar.', reading:'Lendo o diário…', review:'Há pontos para conferir.', error:'O arquivo precisa de atenção.' };
export default function FoxCompanion({ activity }: { activity: FoxActivity }) {
  const [preferences, setPreferences] = useState(() => { try { return readFoxPreferences(window.localStorage); } catch { return DEFAULT_FOX; } });
  const [animation, setAnimation] = useState(INITIAL_FOX);
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || !document.hidden);
  const [reduced, setReduced] = useState(() => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [inLayout, setInLayout] = useState(() => typeof matchMedia === 'undefined' || matchMedia('(min-width: 761px)').matches);
  const [storageNotice, setStorageNotice] = useState('');
  const lastInput = useRef(0);
  const enabled = preferences.show && preferences.animate && inLayout;
  useEffect(() => {
    lastInput.current = performance.now();
    const touch = () => { lastInput.current = performance.now(); };
    const visibility = () => setVisible(!document.hidden);
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => setReduced(media.matches);
    const layout = matchMedia('(min-width: 761px)');
    const layoutChanged = () => setInLayout(layout.matches);
    layout.addEventListener('change', layoutChanged);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pointermove', touch, { passive:true });
    window.addEventListener('keydown', touch);
    media.addEventListener('change', motion);
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pointermove', touch); window.removeEventListener('keydown', touch); media.removeEventListener('change', motion); layout.removeEventListener('change',layoutChanged); };
  }, []);
  useEffect(() => {
    setAnimation(s => nextFox(s, { activity, enabled, pageVisible:visible, reducedMotion:reduced, idleMs:0, random:0 }));
  }, [activity, enabled, visible, reduced]);
  useEffect(() => {
    if (!enabled || !visible || reduced || animation.delay === null) return;
    const timer = window.setTimeout(() => setAnimation(s => nextFox(s, { activity, enabled, pageVisible:visible, reducedMotion:reduced, idleMs:performance.now()-lastInput.current, random:Math.random() })), animation.delay);
    return () => window.clearTimeout(timer);
  }, [animation, activity, enabled, visible, reduced]);
  function preference(key:'show'|'animate', value:boolean) {
    const next = { ...preferences, [key]:value };
    setPreferences(next); setStorageNotice('');
    try { localStorage.setItem(FOX_KEY, JSON.stringify(next)); }
    catch { setStorageNotice('Preferência aplicada só nesta sessão.'); }
  }
  function pet() {
    lastInput.current = performance.now();
    if (enabled && visible && !reduced) setAnimation(beginAction('pet',activity));
  }
  const still = !enabled || !visible || reduced;
  const action = still ? 'idle' : animation.action;
  const pose = still ? 'idle' : foxPose(animation);
  const [column,row] = POSE_POSITION[pose];
  return <section className="fox-companion" aria-label="Mascote do coletor">
    {preferences.show && <div className={`fox-stage fox-${action}`} data-action={action} data-pose={pose} data-motion={still ? 'off' : 'on'}>
      <button className="fox-button" onClick={pet} aria-label="Fazer carinho na raposa" title="Fazer carinho na raposa"><span className="fox-frame"><img className="fox-sprite" src="./mascot/atlas.png" alt="Raposa vermelha, mascote do coletor" width="512" height="256" style={{ translate:`${-column * 128}px ${-row * 128}px` }} draggable={false} /></span></button>
      {action === 'sleep' && <span className="fox-zzz" aria-hidden="true">z z</span>}
      {action === 'pet' && <span className="fox-heart" aria-hidden="true">♥</span>}
      <p>{action === 'sleep' ? 'Descansando por aqui…' : action === 'pet' ? 'Oi! Vamos conferir juntos.' : CAPTIONS[activity]}</p>
    </div>}
    <div className="fox-preferences"><label><input type="checkbox" checked={preferences.show} onChange={e => preference('show',e.target.checked)} />Mostrar raposa</label><label><input type="checkbox" checked={preferences.animate} disabled={!preferences.show} onChange={e => preference('animate',e.target.checked)} />Animar raposa</label></div>
    {reduced && preferences.show && <span className="fox-note">Animação reduzida pelo sistema.</span>}
    {storageNotice && <span className="fox-note" role="status">{storageNotice}</span>}
  </section>;
}
