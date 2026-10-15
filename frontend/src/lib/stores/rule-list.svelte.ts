// State of the rules list page: the rules in evaluation order and the lists their targets resolve
// against. Page-scoped; a delete patches the list in place (patterns §7).

import { classifyRuleError, listRules, type Rule, type RuleError } from '#lib/api/index.js';
import { emptyLookups, type Lookups } from '#lib/ledger/lookups.js';
import { doneText, type RuleDone } from '#lib/rules/messages.js';
import { loadRuleLookups } from './rule-lookups.js';
import { RuleDeleteFlow } from './rule-delete.svelte.js';
import { session } from './session.svelte.js';

export type RuleListStatus = 'loading' | 'ready' | 'error';

export class RuleListStore {
	status = $state<RuleListStatus>('loading');
	error = $state.raw<RuleError | null>(null);
	rules = $state.raw<Rule[]>([]);
	lookups = $state.raw<Lookups>(emptyLookups());
	lookupsFailed = $state.raw<string[]>([]);
	/** what the last write said (from the editor, or a delete here) */
	notice = $state<string | null>(null);

	readonly locale = $derived(session.config?.locale ?? 'en');

	readonly remove = new RuleDeleteFlow({
		locale: () => this.locale,
		deleted: (rule, breakdown, settleFailed) => {
			this.rules = this.rules.filter((r) => r.id !== rule.id);
			this.say({ action: 'deleted', name: rule.name, breakdown, settleFailed });
		},
		gone: (rule) => {
			this.rules = this.rules.filter((r) => r.id !== rule.id);
			this.notice = `Rule “${rule.name}” was already deleted.`;
		}
	});

	#generation = 0;

	say(done: RuleDone): void {
		this.notice = doneText(done, this.locale);
	}

	async load(): Promise<void> {
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		const [rules, lookups] = await Promise.allSettled([listRules(), loadRuleLookups()]);
		if (generation !== this.#generation) return;
		if (rules.status === 'rejected') {
			this.error = classifyRuleError(rules.reason);
			this.status = 'error';
			return;
		}
		this.rules = rules.value;
		if (lookups.status === 'fulfilled') {
			this.lookups = lookups.value.lookups;
			this.lookupsFailed = lookups.value.failed;
		}
		this.status = 'ready';
	}

	dispose(): void {
		this.#generation++;
		this.remove.close();
	}
}
