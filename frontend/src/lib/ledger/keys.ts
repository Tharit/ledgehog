// The ledger list's keyboard model (patterns §5), as pure functions so it can be tested without
// a DOM. The cursor is the selection; there is no multi-select.

export type LedgerKey = 'up' | 'down' | 'open' | 'escape' | 'search' | 'help' | 'tag' | 'rule';

type KeyEventLike = {
	key: string;
	ctrlKey?: boolean;
	metaKey?: boolean;
	altKey?: boolean;
	defaultPrevented?: boolean;
	target?: EventTarget | null;
};

// Keys typed into a field, or inside an open panel or dialog, belong to that field or panel.
const OWNS_KEYS =
	'input, textarea, select, [contenteditable], [role="dialog"], [data-slot="popover-content"]';

function inFieldOrPanel(target: EventTarget | null | undefined): boolean {
	return (
		typeof Element !== 'undefined' &&
		target instanceof Element &&
		target.closest(OWNS_KEYS) !== null
	);
}

/** The ledger action a key press stands for, or null when it is not ours. */
export function ledgerKey(event: KeyEventLike): LedgerKey | null {
	if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return null;
	if (inFieldOrPanel(event.target)) return null;
	switch (event.key) {
		case 'ArrowUp':
		case 'k':
			return 'up';
		case 'ArrowDown':
		case 'j':
			return 'down';
		case 'Enter':
			return 'open';
		case 'Escape':
			return 'escape';
		case '/':
			return 'search';
		case '?':
			return 'help';
		case 't':
			return 'tag';
		case 'r':
			return 'rule';
		default:
			return null;
	}
}

/**
 * The cursor after moving by `delta` rows (-1 = no cursor yet). It stops at both ends; moving
 * up with no cursor lands on the first row.
 */
export function moveCursor(index: number, delta: number, count: number): number {
	if (count <= 0) return -1;
	if (index < 0) return 0;
	return Math.min(count - 1, Math.max(0, index + delta));
}
