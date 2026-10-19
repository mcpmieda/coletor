import { describe, expect, it } from 'vitest';
import { checkedCollector, sharedDraft, sharedFromDraft } from './collector';
describe('Shared school agenda V2 bridge', () => {
  it('maps Sunday to server 0 and preserves optional weekends and IANA zone', () => {
    const value = sharedFromDraft(sharedDraft(null));
    expect(value.timezone).toBe('America/Bahia');
    expect(new Set(value.rules.map(r => `${r.weekday}:${r.shift}`)).size).toBe(14);
    expect(value.rules.filter(r => r.weekday === 0)).toHaveLength(2);
    expect(sharedFromDraft(sharedDraft(value))).toEqual(value);
    expect(value).not.toHaveProperty('localRevision');
    expect(value).not.toHaveProperty('storageMode');
  });
  it('never overwrites a shared revision conflict or reports false saved state', () => {
    expect(() => checkedCollector({ error: 'hidden backend data', code: 'revision-conflict' })).toThrow('Recarregue');
  });
  it('counts final recheck in the maximum 48 slots per day/shift', () => {
    const draft = sharedDraft(null);
    draft.rules[0].timesText = Array.from({ length: 48 }, (_, i) => `08:${String(i).padStart(2, '0')}`).join(',');
    draft.rules[0].reconciliation = '09:00';
    expect(() => sharedFromDraft(draft)).toThrow('48');
  });
});
