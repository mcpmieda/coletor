import { expect, test } from 'vitest';
import { CSP, emptiedLanguage } from '../vite.config';
import viteConfig from '../vite.config.ts?raw';

test('the built page runs no inline, evaluated or remote code, and loads nothing from outside', () => {
  const policy = Object.fromEntries(CSP.split('; ').map(part => [part.split(' ')[0], part.split(' ').slice(1)]));
  expect(policy['default-src']).toEqual(["'none'"]);
  expect(policy['script-src']).toEqual(["'self'"]);
  expect(policy['img-src']).toEqual(["'self'"]);
  expect(policy['connect-src']).toEqual(["'self'"]);
  expect(CSP).not.toMatch(/unsafe-eval|https?:|data:|blob:|\*/);
  // Production build only: the dev server's hot reload needs inline scripts.
  expect(viteConfig).toMatch(/name: 'coletor-csp', apply: 'build'/);
});

test('only the languages of React Aria that the window can ask for are built in', () => {
  const files = Object.keys(import.meta.glob(['../node_modules/react-aria/dist/**/??-??.mjs', '../node_modules/react-stately/dist/**/??-??.mjs',
    '../node_modules/react-aria-components/dist/**/??-??.mjs'], { exhaustive: true }));
  const language = (file: string) => file.slice(file.lastIndexOf('/') + 1, -4);
  for (const name of ['react-aria', 'react-stately', 'react-aria-components']) {
    const own = files.filter(file => file.includes(`/${name}/dist/`));
    // The installed packages still keep one file per language, ours among them.
    expect(own.filter(file => language(file) === 'pt-BR').length, name).toBeGreaterThan(0);
    expect(own.filter(file => language(file) === 'fr-FR').length, name).toBe(own.filter(file => language(file) === 'pt-BR').length);
  }
  for (const file of files) expect(emptiedLanguage(file), file).toBe(!['pt-BR', 'en-US'].includes(language(file)));
  expect(emptiedLanguage('C:\\ui\\node_modules\\react-aria\\dist\\private\\intl\\numberfield\\fr-FR.mjs')).toBe(true);
  expect(emptiedLanguage('/ui/node_modules/react-aria/dist/private/numberfield/useNumberField.mjs')).toBe(false);
  expect(emptiedLanguage('/ui/src/pt-PT.mjs')).toBe(false);
});
