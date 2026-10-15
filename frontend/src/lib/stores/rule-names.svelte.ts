// The rules known by name, for evidence lines ("rule: Rewe", patterns §4.3), shared by the unit
// panel and the review queue. `names.loaded` means the list is FRESH: fetched after the unit or
// queue in view was loaded, and not invalidated since. Only then does a rule it lacks read "rule
// deleted"; otherwise such a key reads just "rule" (a rule list that is old, or still on its way,
// proves nothing). `refresh` asks again (a cheap list), `invalidate` marks what is held old.
import { listRules } from '#lib/api/index.js';
import { rulesNamed, type RuleNames } from '#lib/units/evidence.js';

const NONE: RuleNames = { loaded: false, name: () => undefined };

export class RuleNamesStore {
	names = $state.raw<RuleNames>(NONE);
	#requested = false;
	#generation = 0;

	/** Load the rules once; a failure is quiet and tried again at the next call. */
	async ensure(): Promise<void> {
		if (this.#requested) return;
		return this.refresh();
	}

	/** Ask for the rules again. Names held stay usable; the list is not fresh until it arrives. */
	async refresh(): Promise<void> {
		this.#requested = true;
		const generation = ++this.#generation;
		this.#stale();
		try {
			const rules = await listRules();
			if (generation !== this.#generation) return;
			this.names = rulesNamed(rules);
		} catch {
			if (generation === this.#generation) this.#requested = false;
		}
	}

	/** A rule was created, changed or deleted: what is held is old (names still show, nothing is "deleted"). */
	invalidate(): void {
		this.#generation++;
		this.#requested = false;
		this.#stale();
	}

	#stale(): void {
		if (this.names.loaded) this.names = { loaded: false, name: this.names.name };
	}

	/** Forget the list (tests, sign-out). */
	reset(): void {
		this.#generation++;
		this.names = NONE;
		this.#requested = false;
	}
}

export const ruleNames = new RuleNamesStore();
