import type { Preview } from './types';
interface NativeApi { load_demo(): Promise<Preview | { error: string }>; preview_html(html: string, classId: string, year: number): Promise<Preview | { error: string }> }
declare global { interface Window { pywebview?: { api: NativeApi } } }
function unwrap(body: Preview | { error: string }): Preview {
  if (!('snapshot' in body)) throw new Error(body.error);
  return body;
}
async function request(path: string, init?: RequestInit): Promise<Preview> {
  let response: Response;
  try { response = await fetch(path, { ...init, cache: 'no-store', credentials: 'omit' }); }
  catch { throw new Error('O serviço local não respondeu. Inicie o aplicativo e tente novamente.'); }
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.snapshot) throw new Error(body?.error ?? 'Não foi possível validar este diário.');
  return body as Preview;
}
async function nativeApi(): Promise<NativeApi | undefined> {
  if (window.pywebview?.api) return window.pywebview.api;
  // A native window may load its static UI before injecting its read-only bridge.
  if (window.location.protocol === 'file:') {
    await new Promise<void>((resolve, reject) => {
      const ready = () => { clearTimeout(timer); resolve(); };
      const timer = setTimeout(() => { window.removeEventListener('pywebviewready', ready); reject(new Error('A ponte desktop não ficou pronta. Reabra o aplicativo.')); }, 4000);
      window.addEventListener('pywebviewready', ready, { once: true });
    });
  }
  return window.pywebview?.api;
}
export async function loadDemo(signal?: AbortSignal): Promise<Preview> {
  const native = await nativeApi();
  if (native) return unwrap(await native.load_demo());
  return request('/api/demo', { signal });
}
export async function previewHtml(html: string, classId: string, year: number, signal?: AbortSignal): Promise<Preview> {
  const native = await nativeApi();
  if (native) return unwrap(await native.preview_html(html, classId.trim(), year));
  return request('/api/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ html, class_id: classId.trim(), year }),
  });
}
