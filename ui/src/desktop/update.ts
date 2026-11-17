/** What the Coletor answers to Ajustes > Verificar atualizações (updater.check_now in Python). */
export type UpdateCheck =
  | { state: 'unavailable' }
  | { state: 'current'; version: string }
  | { state: 'found'; version: string; collecting?: boolean };

/** What the fox says about it. A version found installs itself: the Coletor closes and opens again. */
export function updateMessage(result: UpdateCheck): string {
  if (result.state === 'current') return `Este é o Coletor mais novo (versão ${result.version}).`;
  if (result.state === 'found')
    return `Versão ${result.version} encontrada. O Coletor vai baixar a atualização, fechar e abrir de novo sozinho${result.collecting ? ' assim que a coleta em andamento terminar' : ' em instantes'}.`;
  return 'Esta cópia não foi instalada pelo instalador do Coletor e não se atualiza sozinha.';
}
