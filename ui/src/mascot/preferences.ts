export const FOX_KEY = 'coletor-smecel.fox.v1';
export interface FoxPreferences { version:1; show:boolean; animate:boolean }
export const DEFAULT_FOX: FoxPreferences = { version:1, show:true, animate:true };
export function readFoxPreferences(storage: Pick<Storage,'getItem'>): FoxPreferences {
  try {
    const value = storage.getItem(FOX_KEY);
    if (!value || value.length > 256) return { ...DEFAULT_FOX };
    const p = JSON.parse(value);
    if (p.version !== 1 || typeof p.show !== 'boolean' || typeof p.animate !== 'boolean') return { ...DEFAULT_FOX };
    return { version:1, show:p.show, animate:p.animate };
  } catch { return { ...DEFAULT_FOX }; }
}
