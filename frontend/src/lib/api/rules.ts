// Rules (spec §5.9, architecture §4.1): list, get, create, change and delete. Every write is
// previewed first: `dry_run` returns what it would do and writes nothing, and the real run carries
// the preview's `matches.total` as `expected_count` (a moved number is 409 `filter_result_changed`).
import { ApiError, request } from './http.js';

type Schemas = import('../types/api.js').components['schemas'];

export type Rule = Schemas['RuleOut'];
export type RuleCreateBody = Schemas['RuleCreateBody'];
export type RuleUpdateBody = Schemas['RuleUpdateBody'];
export type RulePreview = Schemas['RulePreviewOut'];
export type RulePreviewList = Schemas['PreviewListOut'];
export type RulePreviewRow = Schemas['PreviewRowOut'];
export type RuleWriteOut = Schemas['RuleWriteOut'];
export type RuleDeleteOut = Schemas['RuleDeleteOut'];

/** What a rule sets, fixed at creation (spec §5.9). Counter-account rules are evaluated first. */
export type RuleSets = 'counter_account' | 'payee' | 'category';

/** The rule as it should be: the one target id its `sets` names, every condition, the priority. */
export type RuleFields = Omit<RuleUpdateBody, 'dry_run' | 'expected_count' | 'sets'> & {
	sets: RuleSets;
};

export type RuleWriteControls = {
	/** only preview, change nothing */
	dryRun?: boolean;
	/** the preview's `matches.total`; the server refuses a real write if the result moved since */
	expectedCount?: number;
	/** the page size of every row list of the preview, and where it starts */
	limit?: number;
	offset?: number;
	signal?: AbortSignal;
};

/** Every rule, in evaluation order (counter-account, payee, category; priority, then id). */
export function listRules(signal?: AbortSignal): Promise<Rule[]> {
	return request('GET', '/api/ledger/rules', { signal });
}

export function getRule(id: number, signal?: AbortSignal): Promise<Rule> {
	return request('GET', `/api/ledger/rules/${id}`, { signal });
}

function pageQuery({ limit, offset }: RuleWriteControls) {
	return { limit, offset: offset ? offset : undefined };
}

/** Create a rule (or preview it with `dryRun`). `sets` is fixed from now on. */
export function createRule(
	fields: RuleFields,
	controls: RuleWriteControls = {}
): Promise<RuleWriteOut> {
	return request('POST', '/api/ledger/rules', {
		body: {
			...fields,
			dry_run: controls.dryRun ?? false,
			expected_count: controls.expectedCount ?? null
		},
		query: pageQuery(controls),
		signal: controls.signal
	});
}

/** Replace a rule's name, target, conditions and priority (never `sets`); `dryRun` previews. */
export function updateRule(
	id: number,
	fields: RuleFields,
	controls: RuleWriteControls = {}
): Promise<RuleWriteOut> {
	return request('PUT', `/api/ledger/rules/${id}`, {
		body: {
			...fields,
			dry_run: controls.dryRun ?? false,
			expected_count: controls.expectedCount ?? null
		},
		query: pageQuery(controls),
		signal: controls.signal
	});
}

/** Delete a rule; keys naming it stay on the entries. `dryRun` previews. */
export function deleteRule(id: number, controls: RuleWriteControls = {}): Promise<RuleDeleteOut> {
	return request('DELETE', `/api/ledger/rules/${id}`, {
		query: {
			dry_run: controls.dryRun ? true : undefined,
			expected_count: controls.expectedCount,
			...pageQuery(controls)
		},
		signal: controls.signal
	});
}

/**
 * One place the server refused, from a 422's `details`. `field` is the location without the
 * leading `body`: `name`, `conditions`, or a condition's part as `conditions[2].value`, whether
 * the server wrote it as one string (`invalid_rule`) or as segments (`validation_error`).
 */
export type RuleFieldProblem = { field: string; message: string };

/** A failed rule request, routed by `code` and the details' shape, never by the message. */
export type RuleError =
	| { kind: 'duplicate_name' }
	| { kind: 'filter_result_changed'; expected: number; actual: number }
	| { kind: 'stale_reference'; field: string | null; entity: string | null }
	| { kind: 'invalid_rule'; field: string; message: string }
	| { kind: 'validation'; problems: RuleFieldProblem[] }
	| { kind: 'not_found' }
	| { kind: 'unauthenticated' }
	| { kind: 'network' }
	| { kind: 'other'; status: number };

/** `['body', 'conditions', 2, 'value']` and `['body', 'conditions[2].value']` are the same place. */
export function locationPath(location: readonly unknown[]): string {
	const parts = location[0] === 'body' ? location.slice(1) : location;
	return parts.reduce<string>((path, part) => {
		if (typeof part === 'number') return `${path}[${part}]`;
		return path === '' ? String(part) : `${path}.${String(part)}`;
	}, '');
}

function problemsOf(details: unknown): RuleFieldProblem[] {
	if (!Array.isArray(details)) return [];
	return details.flatMap((item) => {
		const location = (item as { location?: unknown } | null)?.location;
		const message = (item as { message?: unknown } | null)?.message;
		if (!Array.isArray(location) || location.length === 0) return [];
		const field = locationPath(location);
		return field === '' ? [] : [{ field, message: String(message ?? '') }];
	});
}

function text(value: unknown): string | null {
	return typeof value === 'string' ? value : null;
}

/** Sort any thrown value into the failures a rule screen distinguishes. */
export function classifyRuleError(error: unknown): RuleError {
	if (!(error instanceof ApiError)) return { kind: 'network' };
	const details = error.details as Record<string, unknown> | unknown[] | null;
	const named = (!Array.isArray(details) && details ? details : {}) as Record<string, unknown>;
	switch (error.code) {
		case 'network_error':
			return { kind: 'network' };
		case 'unauthenticated':
			return { kind: 'unauthenticated' };
		case 'not_found':
			return { kind: 'not_found' };
		case 'stale_reference':
			return { kind: 'stale_reference', field: text(named.field), entity: text(named.entity) };
		case 'conflict':
			if (named.reason === 'duplicate_name') return { kind: 'duplicate_name' };
			if (named.reason === 'filter_result_changed') {
				return {
					kind: 'filter_result_changed',
					expected: Number(named.expected ?? 0),
					actual: Number(named.actual ?? 0)
				};
			}
			return { kind: 'other', status: error.status };
		case 'invalid_rule': {
			const [first] = problemsOf(error.details);
			return { kind: 'invalid_rule', field: first?.field ?? '', message: first?.message ?? '' };
		}
		case 'validation_error':
			return { kind: 'validation', problems: problemsOf(error.details) };
		default:
			return { kind: 'other', status: error.status };
	}
}
