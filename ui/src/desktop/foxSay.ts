// Every notice of the window is said by the fox (owner request 21/10/2026): no toast in the
// corner. Pages call notify(); FoxPet listens and shows it in its speech bubble.
export type NoticeKind = 'info' | 'success' | 'danger';
export interface Notice { text: string; kind: NoticeKind }

const EVENT = 'coletor-fox-say';
// A module bus, not window: the same in the window and in the unit tests (no DOM there).
const bus = new EventTarget();

function emit(text: string, kind: NoticeKind) {
  bus.dispatchEvent(new CustomEvent<Notice>(EVENT, { detail: { text, kind } }));
}

/** Same calls as the toast it replaces: notify('…'), notify.success('…'), notify.danger('…'). */
export const notify = Object.assign((text: string) => emit(text, 'info'), {
  success: (text: string) => emit(text, 'success'),
  danger: (text: string) => emit(text, 'danger'),
});

export function onNotice(listener: (notice: Notice) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<Notice>).detail);
  bus.addEventListener(EVENT, handler);
  return () => bus.removeEventListener(EVENT, handler);
}
