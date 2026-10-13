// A derivation key (spec §5.9) as text, in the one vocabulary of patterns §4.3. The rules preview
// and the review panel share this: nothing else turns a key into words. Proposals (history, model,
// matcher proposal: the non-standing keys) are marked so a view can set them apart (design §7).
import { formatMonth } from '#lib/format/index.js';
import { ruleUrl } from '#lib/rules/links.js';

/** A key as the server stores it: the pass and the basis it recorded. */
export type DerivationKey = { pass: string; basis?: unknown };

/** The passes whose value is a proposal until a user confirms it (spec §5.9). */
const PROPOSAL_PASSES: ReadonlySet<string> = new Set(['history', 'llm', 'matcher_proposal']);

export function isProposalPass(pass: string): boolean {
	return PROPOSAL_PASSES.has(pass);
}

/** The rules a view knows by name; `loaded` is false until the list has arrived. */
export type RuleNames = { loaded: boolean; name: (id: number) => string | undefined };

/** Rule names from a plain lookup (the list is known). */
export function knownRules(name: (id: number) => string | undefined): RuleNames {
	return { loaded: true, name };
}

/** Rule names from the rules list: a rule it does not hold is gone. */
export function rulesNamed(rules: readonly { id: number; name: string }[]): RuleNames {
	const byId = new Map(rules.map((r) => [r.id, r.name]));
	return knownRules((id) => byId.get(id));
}

export type Evidence = {
	/** the whole line: "history: 3 of 4 since Mar 2026" */
	text: string;
	/** the short form for a narrow column: "history 3 of 4", "rule: Rewe" */
	short: string;
	/** a proposal (non-standing key): shown italic and muted */
	proposal: boolean;
	/** where the rule is edited, for a `rule` key whose rule exists */
	href?: string;
	/** the model's rationale, shown on demand */
	rationale?: string;
};

function record(value: unknown): Record<string, unknown> | null {
	return typeof value === 'object' && value !== null && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

/** A derivation entry as a key, or null when it is not one. */
export function asKey(value: unknown): DerivationKey | null {
	const key = record(value);
	return key && typeof key.pass === 'string' ? { pass: key.pass, basis: key.basis } : null;
}

/** The key of one field of an entry's `derivation` (`category`, `payee`, `type`…), or null. */
export function keyOf(derivation: unknown, field: string): DerivationKey | null {
	return asKey(record(derivation)?.[field]);
}

function historyDetail(basis: Record<string, unknown> | null, locale: string): string | null {
	if (!basis) return null;
	const { agree, of, since } = basis;
	if (typeof agree !== 'number' || typeof of !== 'number') return null;
	let detail = `${agree} of ${of}`;
	if (typeof since === 'string') {
		try {
			detail += ` since ${formatMonth(since, locale)}`;
		} catch {
			// an unreadable date: the counts stand alone
		}
	}
	return detail;
}

function shortHistory(basis: Record<string, unknown> | null): string {
	const agree = basis?.agree;
	const of = basis?.of;
	return typeof agree === 'number' && typeof of === 'number'
		? `history ${agree} of ${of}`
		: 'history';
}

/**
 * The words for a key, or null when there is no key. `rules` names a rule; one the (loaded) list
 * does not hold is "rule deleted"; before the list has arrived the line says only "rule".
 */
export function describeKey(
	key: DerivationKey | null | undefined,
	rules: RuleNames,
	locale = 'en'
): Evidence | null {
	if (!key) return null;
	const basis = record(key.basis);
	switch (key.pass) {
		case 'own_account':
			return { text: 'own account', short: 'own account', proposal: false };
		case 'rule': {
			const id = typeof basis?.rule_id === 'number' ? basis.rule_id : null;
			if (!rules.loaded && id !== null) return { text: 'rule', short: 'rule', proposal: false };
			const name = id === null ? undefined : rules.name(id);
			if (name === undefined || id === null) {
				return { text: 'rule deleted', short: 'rule deleted', proposal: false };
			}
			return {
				text: `rule: ${name}`,
				short: `rule: ${name}`,
				proposal: false,
				href: ruleUrl(id)
			};
		}
		case 'history': {
			const detail = historyDetail(basis, locale);
			return {
				text: detail ? `history: ${detail}` : 'history',
				short: shortHistory(basis),
				proposal: true
			};
		}
		case 'llm': {
			const rationale = typeof basis?.rationale === 'string' ? basis.rationale.trim() : '';
			return {
				text: 'suggested by the model',
				short: 'model',
				proposal: true,
				...(rationale ? { rationale } : {})
			};
		}
		case 'matcher_decision':
			return { text: 'matched automatically', short: 'matched', proposal: false };
		case 'matcher_proposal':
			return {
				text: 'document matched — check the split',
				short: 'document matched',
				proposal: true
			};
		case 'user': {
			const nested = asKey(key.basis);
			if (!nested) return { text: 'set by you', short: 'you', proposal: false };
			const was = describeKey(nested, rules, locale);
			const proposedBy = !was
				? nested.pass
				: nested.pass === 'llm'
					? 'the model'
					: nested.pass === 'matcher_proposal'
						? 'a document match'
						: was.text.replace(/^history: (.*)$/, 'history ($1)');
			return {
				text: `confirmed by you, proposed by ${proposedBy}`,
				short: 'confirmed',
				proposal: false,
				...(was?.rationale ? { rationale: was.rationale } : {})
			};
		}
		default:
			return { text: key.pass, short: key.pass, proposal: false };
	}
}

/** The fields of an entry whose key a queue row shows, most telling first, by entry type. */
const BASIS_FIELDS: Readonly<Record<string, readonly string[]>> = {
	transfer: ['counter_account', 'counterpart', 'type'],
	flow: ['category', 'payee', 'type']
};

/**
 * The one key a compact row shows in its basis column: the first key among the fields that matter
 * for the entry's type (a flow: category, then payee; a transfer: its counter-account).
 */
export function rowBasis(
	entry: { type: string | null; derivation: unknown },
	rules: RuleNames,
	locale = 'en'
): Evidence | null {
	for (const field of BASIS_FIELDS[entry.type ?? 'flow'] ?? BASIS_FIELDS.flow) {
		const evidence = describeKey(keyOf(entry.derivation, field), rules, locale);
		if (evidence) return evidence;
	}
	return null;
}
