import js from '@eslint/js';
import tseslint from 'typescript-eslint';
export default tseslint.config(
  { ignores: ['dist/**','node_modules/**'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parser: tseslint.parser, globals: { window:'readonly', document:'readonly', localStorage:'readonly', matchMedia:'readonly', fetch:'readonly', setTimeout:'readonly', clearTimeout:'readonly', console:'readonly', navigator:'readonly', performance:'readonly', requestAnimationFrame:'readonly', cancelAnimationFrame:'readonly', HTMLInputElement:'readonly', HTMLElement:'readonly', URL:'readonly', AbortController:'readonly', TextEncoder:'readonly' } },
    rules: { ...js.configs.recommended.rules, 'no-undef':'off', 'no-unused-vars':'off', 'no-eval':'error', 'no-implied-eval':'error', 'no-new-func':'error' },
  }
);
