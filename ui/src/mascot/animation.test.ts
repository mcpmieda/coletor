import { expect,test } from 'vitest';
import { INITIAL_FOX, MIN_FRAME_MS, POSE_POSITION, POSES, beginAction, foxPose, nextFox, type AnimationContext } from './animation';
import { DEFAULT_FOX, FOX_KEY, readFoxPreferences } from './preferences';
const context: AnimationContext = { activity:'idle',enabled:true,pageVisible:true,reducedMotion:false,idleMs:0,random:0 };
test('all named actions use known real sprite poses', () => {
  const allowed=['idle','blink','ears','tail-left','tail-right','curious','sleep','happy'];
  for (const frames of Object.values(POSES)) expect(frames.every(f => allowed.includes(f))).toBe(true);
  expect(Object.keys(POSES)).toHaveLength(13);
});
test.each(['enabled','pageVisible'])('%s disabled stops scheduling', flag => {
  expect(nextFox(beginAction('tail','idle'),{ ...context,[flag]:false }).delay).toBeNull();
});
test('reduced motion stops all frame scheduling and restores the static pose', () => {
  const s=nextFox(beginAction('pet','idle'),{ ...context,reducedMotion:true });
  expect(s.delay).toBeNull();expect(foxPose(s)).toBe('idle');
});
test('reading means local parsing and cannot become synchronized/success', () => {
  const s=nextFox(INITIAL_FOX,{ ...context,activity:'reading' });
  expect(s.action).toBe('reading');expect(s.delay).toBe(400);
  expect(nextFox(s,{ ...context,activity:'review' }).action).toBe('review');
  expect(nextFox(s,{ ...context,activity:'error' }).action).toBe('error');
});
test('sleep requires inactivity and wakes after interaction', () => {
  const sleep=nextFox(INITIAL_FOX,{ ...context,idleMs:120000 });
  expect(sleep.action).toBe('sleep');expect(foxPose(sleep)).toBe('sleep');
  expect(nextFox(sleep,{ ...context,idleMs:121000 }).delay).toBe(2500);
  expect(nextFox(sleep,context).action).toBe('wake');
});
test('blink, ears, tail, curiosity, hop and walk are all reachable', () => {
  expect([.1,.3,.5,.7,.85,.95].map(random => nextFox(INITIAL_FOX,{ ...context,random }).action)).toEqual(['blink','ears','tail','curious','hop','walk']);
});
test('long idle simulation is bounded and does not spin at display refresh rate', () => {
  let state=INITIAL_FOX, elapsed=0, callbacks=0;
  while(elapsed<60000) { state=nextFox(state,{ ...context,random:(callbacks%10)/10 });expect(state.delay).toBeGreaterThanOrEqual(MIN_FRAME_MS);elapsed+=state.delay!;callbacks++; }
  expect(callbacks).toBeLessThan(100);
});
test('preference storage recovers safely and whitelists only display options', () => {
  expect(readFoxPreferences({getItem:()=>'{bad'})).toEqual(DEFAULT_FOX);
  expect(readFoxPreferences({getItem:()=>JSON.stringify({version:1,show:false,animate:false,token:'discard'})})).toEqual({version:1,show:false,animate:false});
  expect(FOX_KEY).toContain('fox.v1');
});

test('eight real poses use unique cells of one shared atlas', () => {
  expect(Object.keys(POSE_POSITION)).toHaveLength(8);
  expect(new Set(Object.values(POSE_POSITION).map(v => v.join(','))).size).toBe(8);
  expect(Object.values(POSE_POSITION).every(([x,y]) => x>=0 && x<4 && y>=0 && y<2)).toBe(true);
});
