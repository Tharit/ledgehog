// Deleting a rule: preview first (the dry run says how many entries it matches and how many carry
// its key), then an explicit confirm that carries the previewed count (patterns §6, D202). Shared
// by the rule list and the editor; the host says what happens once the rule is gone.

import { classifyRuleError, deleteRule, type Rule, type RulePreview } from '#lib/api/index.js';
import { describeRuleError } from '#lib/rules/messages.js';

export type RuleDeleteHost = {
	/** the rule is gone; `touched` entries were settled */
	deleted: (rule: Rule, touched: number, settleFailed: boolean) => void;
	/** the rule was already gone */
	gone: (rule: Rule) => void;
	locale: () => string;
};

export type RuleDeleteStatus = 'idle' | 'previewing' | 'deleting';

export class RuleDeleteFlow {
	readonly #host: RuleDeleteHost;
	open = $state(false);
	rule = $state.raw<Rule | null>(null);
	preview = $state.raw<RulePreview | null>(null);
	status = $state<RuleDeleteStatus>('idle');
	/** why the last step failed, in words */
	error = $state<string | null>(null);
	/** set when the counts moved between the preview and the confirmation */
	conflict = $state<string | null>(null);
	#token = 0;

	constructor(host: RuleDeleteHost) {
		this.#host = host;
	}

	readonly canConfirm = $derived(this.preview !== null && this.status === 'idle');

	/** Open the dialog and run the dry run. */
	async start(rule: Rule): Promise<void> {
		this.#token++;
		this.rule = rule;
		this.open = true;
		this.conflict = null;
		await this.#refresh();
	}

	async #refresh(): Promise<void> {
		const rule = this.rule;
		if (!rule) return;
		const token = this.#token;
		this.preview = null;
		this.error = null;
		this.status = 'previewing';
		try {
			// only the counts are wanted: one row is the smallest page
			const out = await deleteRule(rule.id, { dryRun: true, limit: 1 });
			if (token !== this.#token) return;
			this.preview = out.preview;
		} catch (error) {
			if (token !== this.#token) return;
			const failure = classifyRuleError(error);
			if (failure.kind === 'not_found') {
				this.close();
				this.#host.gone(rule);
				return;
			}
			this.error = describeRuleError(failure, this.#host.locale());
		}
		this.status = 'idle';
	}

	async confirm(): Promise<void> {
		const rule = this.rule;
		const preview = this.preview;
		if (!rule || !preview || this.status !== 'idle') return;
		const token = this.#token;
		this.status = 'deleting';
		this.error = null;
		this.conflict = null;
		try {
			const out = await deleteRule(rule.id, { expectedCount: preview.matches.total, limit: 1 });
			if (token !== this.#token) return;
			this.close();
			this.#host.deleted(rule, out.settle?.touched_entry_ids.length ?? 0, !!out.settle?.error);
		} catch (error) {
			if (token !== this.#token) return;
			const failure = classifyRuleError(error);
			if (failure.kind === 'not_found') {
				this.close();
				this.#host.gone(rule);
				return;
			}
			this.status = 'idle';
			if (failure.kind === 'filter_result_changed') {
				// nothing was deleted: show the new counts and ask again
				this.conflict = describeRuleError(failure, this.#host.locale());
				await this.#refresh();
				return;
			}
			this.error = describeRuleError(failure, this.#host.locale());
		}
	}

	close(): void {
		this.#token++;
		this.open = false;
		this.rule = null;
		this.preview = null;
		this.status = 'idle';
		this.error = null;
		this.conflict = null;
	}
}
