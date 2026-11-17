import { describe, expect, it } from 'vitest';
import { updateMessage } from './update';

describe('Ajustes > Verificar atualizações', () => {
  it('says the version is the newest, or which one was found and when it installs itself', () => {
    expect(updateMessage({ state: 'current', version: '0.4.350' })).toBe('Este é o Coletor mais novo (versão 0.4.350).');
    expect(updateMessage({ state: 'found', version: '0.4.351' })).toContain('Versão 0.4.351 encontrada');
    expect(updateMessage({ state: 'found', version: '0.4.351' })).toContain('em instantes');
    expect(updateMessage({ state: 'found', version: '0.4.351', collecting: true })).toContain('assim que a coleta em andamento terminar');
    expect(updateMessage({ state: 'unavailable' })).toContain('não se atualiza sozinha');
  });
});
