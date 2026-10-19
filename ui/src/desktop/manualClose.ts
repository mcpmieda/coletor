/** Result of close_manual_session: the class choice may only disappear once
 *  the Smecel session is confirmed closed and its cleanup finished. */
export interface ManualCloseResult { error?: string; state?: string; cleanup_pending?: boolean }

export function closeProblem(result: ManualCloseResult | null | undefined): string | null {
  if (!result) return 'O Coletor não respondeu ao fechar o Smecel.';
  if (result.error) return result.error;
  if (result.state !== 'closed' || result.cleanup_pending) return 'O Smecel ainda está sendo fechado.';
  return null;
}
