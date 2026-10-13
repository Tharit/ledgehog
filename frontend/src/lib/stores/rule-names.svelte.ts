// The rules known by name, for evidence lines ("rule: Rewe", patterns §4.3): loaded lazily, the
// first time a view shows a rule's key, and shared by the unit panel and the review queue. Until
// the list has arrived a rule's key reads just "rule" (never "rule deleted").
import { listRules } from '#lib/api/index.js';
import { rulesNamed, type RuleNames } from '#lib/units/evidence.js';

export class RuleNamesStore {
	names = $state.raw<RuleNames>({ loaded: false, name: () => undefined });
	#requested = false;

	/** Load the rules once; a failure is quiet and tried again at the next call. */
	async ensure(): Promise<void> {
		if (this.#requested) return;
		this.#requested = true;
		try {
			const rules = await listRules();
			this.names = rulesNamed(rules);
		} catch {
			this.#requested = false;
		}
	}

	/** Forget the list (tests, sign-out). */
	reset(): void {
		this.names = { loaded: false, name: () => undefined };
		this.#requested = false;
	}
}

export const ruleNames = new RuleNamesStore();
