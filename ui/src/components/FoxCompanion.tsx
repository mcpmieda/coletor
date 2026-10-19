import { useEffect, useRef, useState } from 'react';
import { INITIAL_FOX, POSE_POSITION, beginAction, foxPose, nextFox, type FoxActivity } from '../mascot/animation';

const CAPTIONS: Record<FoxActivity, string> = { idle:'Pronta para ajudar.', reading:'Lendo o diário…', review:'Há pontos para conferir.', error:'O arquivo precisa de atenção.' };
/** Always present; it moves only while visible and when the system allows motion. */
export default function FoxCompanion({ activity, caption: showCaption = true, onPet }: Readonly<{ activity: FoxActivity; caption?: boolean; onPet?: () => void }>) {
  const [animation, setAnimation] = useState(INITIAL_FOX);
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || (!document.hidden && window.__coletorWindowVisible !== false));
  const [reduced, setReduced] = useState(() => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [inLayout, setInLayout] = useState(() => typeof matchMedia === 'undefined' || matchMedia('(min-width: 761px)').matches);
  const lastInput = useRef(0);
  useEffect(() => {
    lastInput.current = performance.now();
    const touch = () => { lastInput.current = performance.now(); };
    const visibility = () => setVisible(!document.hidden && window.__coletorWindowVisible !== false);
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => setReduced(media.matches);
    const layout = matchMedia('(min-width: 761px)');
    const layoutChanged = () => setInLayout(layout.matches);
    layout.addEventListener('change', layoutChanged);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('coletorwindowvisibility', visibility);
    window.addEventListener('pointermove', touch, { passive:true });
    window.addEventListener('keydown', touch);
    media.addEventListener('change', motion);
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('coletorwindowvisibility', visibility); window.removeEventListener('pointermove', touch); window.removeEventListener('keydown', touch); media.removeEventListener('change', motion); layout.removeEventListener('change',layoutChanged); };
  }, []);
  useEffect(() => {
    setAnimation(s => nextFox(s, { activity, enabled: inLayout, pageVisible:visible, reducedMotion:reduced, idleMs:0, random:0 }));
  }, [activity, inLayout, visible, reduced]);
  useEffect(() => {
    if (!inLayout || !visible || reduced || animation.delay === null) return;
    const timer = window.setTimeout(() => setAnimation(s => nextFox(s, { activity, enabled: inLayout, pageVisible:visible, reducedMotion:reduced, idleMs:performance.now()-lastInput.current, random:Math.random() })), animation.delay);
    return () => window.clearTimeout(timer);
  }, [animation, activity, inLayout, visible, reduced]);
  function pet() {
    lastInput.current = performance.now();
    onPet?.();
    if (inLayout && visible && !reduced) setAnimation(beginAction('pet',activity));
  }
  const still = !inLayout || !visible || reduced;
  const action = still ? 'idle' : animation.action;
  const pose = still ? 'idle' : foxPose(animation);
  const [column,row] = POSE_POSITION[pose];
  let caption = CAPTIONS[activity];
  if (action === 'sleep') caption = 'Descansando por aqui…';
  else if (action === 'pet') caption = 'Oi! Vamos conferir juntos.';
  return <section className="fox-companion" aria-label="Mascote do coletor">
    <div className={`fox-stage fox-${action}`} data-action={action} data-pose={pose} data-motion={still ? 'off' : 'on'}>
      <button className="fox-button" onClick={pet} aria-label="Fazer carinho na raposa" title="Fazer carinho na raposa"><span className="fox-frame"><img className="fox-sprite" src="./mascot/atlas.png" alt="Raposa vermelha, mascote do coletor" width="512" height="256" style={{ translate:`${-column * 128}px ${-row * 128}px` }} draggable={false} /></span></button>
      {action === 'sleep' && <span className="fox-zzz" aria-hidden="true">z z</span>}
      {action === 'pet' && <span className="fox-heart" aria-hidden="true">♥</span>}
      {showCaption && <p>{caption}</p>}
    </div>
  </section>;
}
