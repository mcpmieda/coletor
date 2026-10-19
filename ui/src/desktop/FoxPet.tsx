// The fox with speech bubbles, like the Atualizador's dragon: it reacts to the
// collector, speaks rarely on its own and thanks you when petted.
import { useEffect, useRef, useState } from 'react';
import FoxCompanion from '../components/FoxCompanion';
import { pickPhrase, type FoxMood } from './foxPhrases';
import type { FoxActivity } from '../mascot/animation';

export default function FoxPet({ mood }: Readonly<{ mood: FoxMood }>) {
  const [bubble, setBubble] = useState<string | null>(null);
  const lastMood = useRef<FoxMood | null>(null);
  const say = (text: string, ms = 5200) => {
    setBubble(text);
    window.setTimeout(() => setBubble(b => (b === text ? null : b)), ms);
  };
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
  const activity: FoxActivity = mood === 'running' ? 'reading' : mood === 'error' ? 'error' : 'idle';
  return (
    <div className="fox-sidebar relative pt-10">
      {bubble && (
        <div className="pet-bubble absolute bottom-[168px] left-1/2 z-10 w-max max-w-[210px] -translate-x-1/2 rounded-xl border border-separator bg-surface px-3 py-2 text-center text-xs leading-snug text-foreground shadow-sm">
          {bubble}
        </div>
      )}
      <FoxCompanion activity={activity} caption={false} onPet={() => say(pickPhrase('pet'), 3500)} />
    </div>
  );
}
