/** Deterministic, bounded animation policy. It never schedules collection work. */
export type FoxActivity = 'idle' | 'reading' | 'review' | 'error';
export type FoxPose = 'idle' | 'blink' | 'ears' | 'tail-left' | 'tail-right' | 'curious' | 'sleep' | 'happy';
export type FoxAction = 'idle' | 'blink' | 'ears' | 'tail' | 'curious' | 'hop' | 'walk' | 'sleep' | 'wake' | 'reading' | 'review' | 'error' | 'pet';
export const POSE_POSITION: Record<FoxPose, readonly [number,number]> = { idle:[0,0], blink:[1,0], ears:[2,0], curious:[3,0], 'tail-left':[0,1], 'tail-right':[1,1], sleep:[2,1], happy:[3,1] };
export const POSES: Record<FoxAction, readonly FoxPose[]> = {
  idle: ['idle'], blink: ['idle','blink','idle'], ears: ['idle','ears','idle','ears','idle'],
  tail: ['idle','tail-left','tail-right','tail-left','idle'], curious: ['idle','curious','blink','curious','idle'],
  hop: ['idle','curious','idle'], walk: ['tail-left','tail-right','tail-left','tail-right','idle'],
  sleep: ['sleep'], wake: ['sleep','curious','blink','idle'],
  reading: ['curious','tail-left','curious','tail-right'], review: ['curious','blink','idle'],
  error: ['curious','ears','curious','idle'], pet: ['curious','happy','happy','blink','idle'],
};
export interface FoxAnimation { action: FoxAction; frame: number; activity: FoxActivity; delay: number | null }
export interface AnimationContext { activity: FoxActivity; enabled: boolean; pageVisible: boolean; reducedMotion: boolean; idleMs: number; random: number }
export const INITIAL_FOX: FoxAnimation = { action:'idle', frame:0, activity:'idle', delay:1800 };
export const MIN_FRAME_MS = 160;
export function beginAction(action: FoxAction, activity: FoxActivity): FoxAnimation {
  return { action, frame:0, activity, delay:action === 'idle' ? 1800 : action === 'sleep' ? 2500 : action === 'reading' ? 400 : MIN_FRAME_MS };
}
export function foxPose(state: FoxAnimation): FoxPose { return POSES[state.action][state.frame] ?? 'idle'; }
export function nextFox(state: FoxAnimation, context: AnimationContext): FoxAnimation {
  const { activity, enabled, pageVisible, reducedMotion, idleMs, random } = context;
  if (!enabled || !pageVisible || reducedMotion) return { action:'idle', frame:0, activity, delay:null };
  if (activity !== state.activity) return beginAction(activity === 'idle' ? 'wake' : activity, activity);
  if (activity === 'reading') return { ...state, action:'reading', frame:(state.action === 'reading' ? state.frame + 1 : 0) % POSES.reading.length, delay:400 };
  if (state.action === 'sleep') return idleMs < 120000 ? beginAction('wake', activity) : { ...state, delay:2500 };
  if (state.frame + 1 < POSES[state.action].length) return { ...state, frame:state.frame + 1, delay:MIN_FRAME_MS };
  if (state.action !== 'idle') return { ...beginAction('idle', activity), delay:1800 + Math.floor(Math.min(.999,Math.max(0,random))*1800) };
  if (idleMs >= 120000) return beginAction('sleep', activity);
  const r = Math.min(.999,Math.max(0,random));
  const action: FoxAction = r < .28 ? 'blink' : r < .46 ? 'ears' : r < .67 ? 'tail' : r < .82 ? 'curious' : r < .91 ? 'hop' : 'walk';
  return beginAction(action,activity);
}
