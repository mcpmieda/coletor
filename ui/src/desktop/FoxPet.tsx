// The fox with speech bubbles, like the Atualizador's dragon: it reacts to the
// collector, speaks rarely on its own and thanks you when petted. Every notice of
// the window is also said by it (foxSay.ts), so there is no toast in the corner.
import { useEffect, useRef, useState } from 'react';
import FoxCompanion from '../components/FoxCompanion';
import { pickPhrase, type FoxMood } from './foxPhrases';
import { onNotice, type NoticeKind } from './foxSay';
import type { FoxActivity } from '../mascot/animation';

type Bubble = { text: string; kind: NoticeKind | 'chat' };
const KIND_CLASS: Record<Bubble['kind'], string> = {
  chat: 'border-separator text-foreground',
  info: 'border-accent/40 text-foreground',
  success: 'border-success/50 text-success',
  danger: 'border-danger/50 text-danger',
};
// A notice stays longer than chatter; an error the longest, so it can be read.
const NOTICE_MS: Record<NoticeKind, number> = { info: 5200, success: 5200, danger: 9000 };

export default function FoxPet({ mood }: Readonly<{ mood: FoxMood }>) {
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const shown = useRef<Bubble | null>(null);
  const lastMood = useRef<FoxMood | null>(null);
  const show = (next: Bubble, ms: number) => {
    shown.current = next;
    setBubble(next);
    window.setTimeout(() => {
      if (shown.current !== next) return;
      shown.current = null;
      setBubble(null);
    }, ms);
  };
  // Chatter never covers a notice still on screen.
  const say = (text: string, ms = 5200) => {
    if (shown.current && shown.current.kind !== 'chat') return;
    show({ text, kind: 'chat' }, ms);
  };
  useEffect(() => onNotice(notice => show(notice, NOTICE_MS[notice.kind])), []);
  useEffect(() => {
    // Reacts to the collector's changes without repeating the same reaction.
    if (lastMood.current && lastMood.current !== mood && mood !== 'idle') say(pickPhrase(mood));
    lastMood.current = mood;
  }, [mood]);
  useEffect(() => {
    // Rare spontaneous line: first after 25–50 s, then every 1.5–4 min.
    let timer = 0;
    const schedule = (min: number, max: number) => {
      timer = window.setTimeout(() => {
        if (!document.hidden) say(pickPhrase(mood === 'paused' ? 'sleep' : 'idle'));
        schedule(90_000, 240_000);
      }, min + Math.random() * (max - min));
    };
    schedule(25_000, 50_000);
    return () => window.clearTimeout(timer);
  }, [mood]);
  const activity: FoxActivity = mood === 'running' ? 'reading' : mood === 'error' || bubble?.kind === 'danger' ? 'error' : 'idle';
  return (
    <div className="fox-sidebar relative pt-10">
      {/* Always in the tree so screen readers announce each notice. */}
      <div role="status" aria-live={bubble?.kind === 'danger' ? 'assertive' : 'polite'} className="sr-only">
        {bubble && bubble.kind !== 'chat' ? bubble.text : ''}
      </div>
      {bubble && (
        <div aria-hidden={bubble.kind !== 'chat'}
          className={`pet-bubble absolute bottom-[168px] left-1/2 z-10 w-max max-w-[210px] -translate-x-1/2 rounded-xl border bg-surface px-3 py-2 text-center text-xs leading-snug shadow-sm ${KIND_CLASS[bubble.kind]}`}>
          {bubble.text}
        </div>
      )}
      <FoxCompanion activity={activity} caption={false} onPet={() => say(pickPhrase('pet'), 3500)} />
    </div>
  );
}
