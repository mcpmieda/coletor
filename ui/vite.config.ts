import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
// The window loads only its own files: nothing remote, inline or evaluated may run in it. React Aria
// adds <style> elements, hence 'unsafe-inline' for styles alone. Production build only: the dev
// server needs inline scripts for hot reload.
export const CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'";
const contentSecurityPolicy: Plugin = { name: 'coletor-csp', apply: 'build',
  transformIndexHtml: () => [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' }] };
// React Aria carries its own strings in 34 languages and the interface speaks one (main.tsx sets
// pt-BR for all of it). An emptied language is skipped by its dictionary; en-US stays as its fallback.
const LANGUAGES = new Set(['pt-BR', 'en-US']);
export function emptiedLanguage(id: string): boolean {
  const language = /[\\/]node_modules[\\/]react-(?:aria|stately|aria-components)[\\/]dist[\\/].*[\\/]([a-z]{2}-[A-Z]{2})\.mjs$/.exec(id)?.[1];
  return !!language && !LANGUAGES.has(language);
}
const ownLanguageOnly: Plugin = { name: 'coletor-languages', apply: 'build', enforce: 'pre',
  load: id => (emptiedLanguage(id) ? 'export default undefined;' : null) };
export default defineConfig({
  plugins: [ownLanguageOnly, react(), tailwindcss(), contentSecurityPolicy],
  base: './',
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } } },
});
