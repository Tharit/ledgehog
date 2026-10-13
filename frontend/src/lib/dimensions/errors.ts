// How a failed category or payee write is understood and put to the user: routed by the error's
// `code` and, for a 409 `conflict`, its `details.reason`, never by its message (architecture §4.4,
// patterns §8).

export type Subject = 'category' | 'payee';

export type DimensionFailure =
	| { kind: 'duplicate_name' }
	| { kind: 'cycle' }
	| { kind: 'into_descendant' }
	| { kind: 'in_use'; held: Record<string, number> }
	| { kind: 'count_changed'; expected: number | null; actual: number | null }
	| { kind: 'stale'; field: string | null }
	| { kind: 'validation'; message: string }
	| { kind: 'not_found' }
	| { kind: 'network' }
	| { kind: 'unauthenticated' }
	| { kind: 'other' };

/** The result of a write the screens attempt: its answer, or what went wrong. */
export type Outcome<T> = { ok: true; value: T } | { ok: false; failure: DimensionFailure };

type ErrorLike = { code: string; details?: unknown };

function record(value: unknown): Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function count(value: unknown): number | null {
	return typeof value === 'number' ? value : null;
}

function heldCounts(value: unknown): Record<string, number> {
	const held: Record<string, number> = {};
	for (const [name, n] of Object.entries(record(value))) {
		if (typeof n === 'number') held[name] = n;
	}
	return held;
}

/** The first field-level message of a 422, which is what the user can act on. */
function validationMessage(details: unknown): string {
	if (Array.isArray(details)) {
		const first = record(details[0]);
		if (typeof first.message === 'string' && first.message) return first.message;
	}
	return 'The server did not accept this. Check the value and try again.';
}

export function classifyDimensionError(error: ErrorLike): DimensionFailure {
	const details = record(error.details);
	switch (error.code) {
		case 'conflict':
			switch (details.reason) {
				case 'duplicate_name':
					return { kind: 'duplicate_name' };
				case 'cycle':
					return { kind: 'cycle' };
				case 'into_descendant':
					return { kind: 'into_descendant' };
				case 'category_in_use':
				case 'payee_in_use':
					return { kind: 'in_use', held: heldCounts(details.held) };
				case 'filter_result_changed':
					return {
						kind: 'count_changed',
						expected: count(details.expected),
						actual: count(details.actual)
					};
				default:
					return { kind: 'other' };
			}
		case 'stale_reference':
			return { kind: 'stale', field: typeof details.field === 'string' ? details.field : null };
		case 'validation_error':
			return { kind: 'validation', message: validationMessage(error.details) };
		case 'not_found':
			return { kind: 'not_found' };
		case 'network_error':
			return { kind: 'network' };
		case 'unauthenticated':
			return { kind: 'unauthenticated' };
		default:
			return { kind: 'other' };
	}
}

/** Does the app have to reload its category / payee lists because of this? (patterns §8) */
export function needsReload(failure: DimensionFailure): boolean {
	return (
		failure.kind === 'stale' ||
		failure.kind === 'not_found' ||
		failure.kind === 'duplicate_name' ||
		failure.kind === 'count_changed'
	);
}

/** Does a refused write belong under the field it came from (the name), not to the dialog as a whole? */
export function isFieldFailure(failure: DimensionFailure): boolean {
	return failure.kind === 'duplicate_name' || failure.kind === 'validation';
}

const PLURAL: Record<string, [string, string]> = {
	entries: ['entry', 'entries'],
	rules: ['rule', 'rules'],
	children: ['subcategory', 'subcategories']
};

/** "3 entries, 1 rule": the counts that stand in the way, the zero ones left out. */
export function describeHeld(held: Record<string, number>): string {
	return Object.entries(PLURAL)
		.map(([key, [one, many]]) => ({ n: held[key] ?? 0, one, many }))
		.filter(({ n }) => n > 0)
		.map(({ n, one, many }) => `${n} ${n === 1 ? one : many}`)
		.join(', ');
}

const FIELD_NAMES: Record<string, string> = {
	into: 'the merge target',
	parent_id: 'the parent',
	category_id: 'the category',
	payee_id: 'the payee'
};

/** What the user is told. `name` is the thing being written, where the sentence wants it. */
export function describeFailure(failure: DimensionFailure, subject: Subject, name = ''): string {
	const noun = subject === 'category' ? 'category' : 'payee';
	switch (failure.kind) {
		case 'duplicate_name':
			return subject === 'category'
				? `A category named "${name}" already exists at this level.`
				: `A payee named "${name}" already exists.`;
		case 'cycle':
			return 'A category cannot be moved under itself or one of its own subcategories.';
		case 'into_descendant':
			return 'A category cannot be merged into one of its own subcategories. Merge the subcategories upwards instead.';
		case 'in_use': {
			const held = describeHeld(failure.held);
			return `This ${noun} is still in use${held ? ` (${held})` : ''}. Merge it into another ${noun} instead.`;
		}
		case 'count_changed':
			return failure.actual === null
				? 'The result changed since the preview. Check it and try again.'
				: `The result changed since the preview: it now touches ${failure.actual} ${failure.actual === 1 ? 'entry' : 'entries'}. Check it and try again.`;
		case 'stale': {
			const field = failure.field ? (FIELD_NAMES[failure.field] ?? failure.field) : `a ${noun}`;
			return `${field[0].toUpperCase()}${field.slice(1)} no longer exists. The lists were reloaded; check them and try again.`;
		}
		case 'validation':
			return failure.message;
		case 'not_found':
			return `This ${noun} no longer exists. The list was reloaded.`;
		case 'network':
			return 'The server could not be reached. Check the connection and try again.';
		case 'unauthenticated':
			return 'Your session has ended. Sign in again.';
		default:
			return 'The server could not do this. Try again in a moment.';
	}
}
