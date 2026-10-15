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

/** The rules a view knows by name; `loaded`: the list is fresh, so a rule it lacks is gone. */
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

/**
 * The words for a key, or null when there is no key. `rules` names a rule; one a FRESH list
 * does not hold is "rule deleted"; when the list is old or has not arrived the line says "rule".
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
			return { text: 'own account', proposal: false };
		case 'rule': {
			const id = typeof basis?.rule_id === 'number' ? basis.rule_id : null;
			const name = id === null ? undefined : rules.name(id);
			if (name === undefined || id === null) {
				// only a fresh list can say a rule is gone; an old or pending one says nothing
				return rules.loaded || id === null
					? { text: 'rule deleted', proposal: false }
					: { text: 'rule', proposal: false };
			}
			return {
				text: `rule: ${name}`,
				proposal: false,
				href: ruleUrl(id)
			};
		}
		case 'history': {
			const detail = historyDetail(basis, locale);
			return {
				text: detail ? `history: ${detail}` : 'history',
				proposal: true
			};
		}
		case 'llm': {
			const rationale = typeof basis?.rationale === 'string' ? basis.rationale.trim() : '';
			return {
				text: 'suggested by the model',
				proposal: true,
				...(rationale ? { rationale } : {})
			};
		}
		case 'matcher_decision':
			return { text: 'matched automatically', proposal: false };
		case 'matcher_proposal':
			return {
				text: 'document matched — check the split',
				proposal: true
			};
		case 'user': {
			const nested = asKey(key.basis);
			if (!nested) return { text: 'set by you', proposal: false };
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
				proposal: false,
				...(was?.rationale ? { rationale: was.rationale } : {})
			};
		}
		default:
			return { text: key.pass, proposal: false };
	}
}
