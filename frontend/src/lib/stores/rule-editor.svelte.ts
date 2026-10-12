// State of the rule editor (one rule, new or stored): the form, and the PREVIEW the server gives
// for it. The preview is the write endpoint called with `dry_run`, debounced after every edit
// (spec §5.9, D202). Only a preview of exactly the form as it stands enables the save, and the
// save carries that preview's `matches.total` as `expected_count`. The client never matches
// anything: counts and rows are the server's (architecture §6.3). Page-scoped.

import {
	classifyRuleError,
	createRule,
	findEntry,
	getRule,
	listRules,
	updateRule,
	type Rule,
	type RuleError,
	type RuleFields,
	type RulePreview,
	type RulePreviewRow,
	type RuleWriteControls,
	type RuleWriteOut
} from '#lib/api/index.js';
import { emptyLookups, type Lookups } from '#lib/ledger/lookups.js';
import {
	emptyForm,
	formFromRule,
	formKey,
	isDirty,
	isPreviewable,
	previewMatchesForm,
	saveBlock,
	takesPayeeCondition,
	toFields,
	type RuleForm
} from '#lib/rules/form.js';
import { describeRuleError, fieldErrors } from '#lib/rules/messages.js';
import {
	formFromEntry,
	suggestionsFromEntry,
	type FromEntry,
	type Suggestion
} from '#lib/rules/prefill.js';
import { loadRuleLookups } from './rule-lookups.js';
import { session } from './session.svelte.js';

/** the rows of each list one request returns */
export const PREVIEW_PAGE = 50;
/** the pause after the last edit before the preview is asked for */
export const PREVIEW_DEBOUNCE_MS = 400;

export type PreviewListName = 'matches' | 'different_value' | 'lost_key';
export type EditorLoad = 'loading' | 'ready' | 'error' | 'missing';
export type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';
export type EditorNotice = { text: string; error: boolean };
export type SaveResult = { rule: Rule; touched: number; settleFailed: boolean };

export type RuleEditorOptions = {
	/** the rule to change; null for a new one */
	ruleId: number | null;
	/** a new rule starting from this entry */
	from?: FromEntry | null;
	debounceMs?: number;
};

const NO_EXTRA: Record<PreviewListName, RulePreviewRow[]> = {
	matches: [],
	different_value: [],
	lost_key: []
};

export class RuleEditorStore {
	readonly ruleId: number | null;
	#initialKey = $state(formKey(emptyForm()));
	#seq = 0;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#controller: AbortController | null = null;
	readonly #from: FromEntry | null;
	readonly #debounce: number;

	loadStatus = $state<EditorLoad>('loading');
	loadError = $state.raw<RuleError | null>(null);
	/** the stored rule, when editing one */
	rule = $state.raw<Rule | null>(null);
	form = $state.raw<RuleForm>(emptyForm());
	/** the entry's text, offered as conditions to tick */
	suggestions = $state.raw<Suggestion[]>([]);
	lookups = $state.raw<Lookups>(emptyLookups());
	lookupsFailed = $state.raw<string[]>([]);
	/** every rule, for the names of the ones that take precedence */
	rules = $state.raw<Rule[]>([]);

	preview = $state.raw<RulePreview | null>(null);
	/** the key of the form the held preview was asked for */
	previewedKey = $state.raw<string | null>(null);
	previewStatus = $state<PreviewStatus>('idle');
	/** rows fetched by "show more", per list, after the ones the preview came with */
	extra = $state.raw<Record<PreviewListName, RulePreviewRow[]>>(NO_EXTRA);
	moreBusy = $state<PreviewListName | null>(null);
	/** the last failure of a preview or a save */
	error = $state.raw<RuleError | null>(null);
	notice = $state.raw<EditorNotice | null>(null);
	saving = $state(false);

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly fieldErrors = $derived(fieldErrors(this.error));
	/** a preview of exactly this form has arrived */
	readonly previewCurrent = $derived(
		this.previewStatus === 'ready' &&
			this.preview !== null &&
			previewMatchesForm(this.previewedKey, this.form)
	);
	readonly dirty = $derived(isDirty(this.form, this.#initialKey));
	readonly saveBlocked = $derived(
		saveBlock(this.form, {
			previewCurrent: this.previewCurrent,
			previewFailed: this.previewStatus === 'error',
			saving: this.saving,
			unchanged: this.editing && !this.dirty
		})
	);
	readonly canSave = $derived(this.saveBlocked === null);

	constructor({ ruleId, from = null, debounceMs = PREVIEW_DEBOUNCE_MS }: RuleEditorOptions) {
		this.ruleId = ruleId;
		this.#from = from;
		this.#debounce = debounceMs;
	}

	/** Is this the editor of a stored rule (and not of a new one)? */
	get editing(): boolean {
		return this.ruleId !== null;
	}

	/** The name of a rule, for "Rule X takes precedence"; undefined for one that is not loaded. */
	ruleName(id: number): string | undefined {
		return this.rules.find((r) => r.id === id)?.name;
	}

	/** The rows of one preview list: the page the preview came with, then what "show more" added. */
	rowsOf(name: PreviewListName): RulePreviewRow[] {
		return this.preview ? [...this.preview[name].rows, ...this.extra[name]] : [];
	}

	/** Load what the editor needs; for a new rule from an entry, that entry's text. */
	async init(): Promise<void> {
		this.loadStatus = 'loading';
		this.loadError = null;
		const stored = this.ruleId === null ? null : getRule(this.ruleId);
		const [lookups, rules, rule, entry] = await Promise.allSettled([
			loadRuleLookups(),
			listRules(),
			stored ?? Promise.resolve(null),
			this.#from ? findEntry(this.#from.id, this.#from) : Promise.resolve(null)
		]);

		if (lookups.status === 'fulfilled') {
			this.lookups = lookups.value.lookups;
			this.lookupsFailed = lookups.value.failed;
		}
		if (rules.status === 'fulfilled') this.rules = rules.value;

		if (this.ruleId !== null) {
			if (rule.status === 'rejected') {
				const failure = classifyRuleError(rule.reason);
				this.loadError = failure;
				this.loadStatus = failure.kind === 'not_found' ? 'missing' : 'error';
				return;
			}
			const loaded = rule.value as Rule;
			this.rule = loaded;
			this.form = formFromRule(loaded);
		} else if (this.#from) {
			if (entry.status === 'fulfilled' && entry.value) {
				this.form = formFromEntry(entry.value);
				this.suggestions = suggestionsFromEntry(entry.value);
			} else {
				this.notice = {
					text:
						entry.status === 'rejected'
							? 'The entry could not be loaded; start from scratch.'
							: 'That entry was not found; start from scratch.',
					error: false
				};
			}
		}
		this.#initialKey = formKey(this.form);
		this.loadStatus = 'ready';
		this.#schedule(true);
	}

	/** Change the form. A new preview follows, after a pause unless `now`. */
	edit(patch: Partial<RuleForm>, now = false): void {
		const before = this.form;
		const next = { ...before, ...patch };
		if (patch.sets !== undefined && patch.sets !== before.sets) {
			// what a rule sets is not a condition: a target of another kind does not carry over
			next.target = null;
			if (!takesPayeeCondition(next.sets)) next.condition_payee_id = null;
		}
		this.form = next;
		this.error = null;
		this.notice = null;
		if (formKey(next) !== formKey(before)) this.#schedule(now);
	}

	/** Ask for the preview now, discarding whatever is pending. */
	refreshPreview(): void {
		this.#schedule(true);
	}

	#schedule(now: boolean): void {
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		this.#controller?.abort();
		const seq = ++this.#seq;
		if (!isPreviewable(this.form)) {
			this.previewStatus = 'idle';
			this.preview = null;
			this.previewedKey = null;
			this.extra = NO_EXTRA;
			return;
		}
		// the preview held stays on screen, marked as out of date, until the new one arrives
		this.previewStatus = 'loading';
		if (now) void this.#run(seq);
		else this.#timer = setTimeout(() => void this.#run(seq), this.#debounce);
	}

	#write(form: RuleForm, controls: RuleWriteControls): Promise<RuleWriteOut> {
		const fields: RuleFields = toFields(form, { forPreview: controls.dryRun });
		return this.ruleId === null
			? createRule(fields, controls)
			: updateRule(this.ruleId, fields, controls);
	}

	async #run(seq: number): Promise<void> {
		this.#timer = null;
		const form = this.form;
		const key = formKey(form);
		const controller = new AbortController();
		this.#controller = controller;
		try {
			const out = await this.#write(form, {
				dryRun: true,
				limit: PREVIEW_PAGE,
				signal: controller.signal
			});
			if (seq !== this.#seq) return; // a newer edit superseded this answer
			this.preview = out.preview;
			this.previewedKey = key;
			this.extra = NO_EXTRA;
			this.error = null;
			this.previewStatus = 'ready';
		} catch (error) {
			if (seq !== this.#seq) return;
			this.#fail(classifyRuleError(error));
		}
	}

	/** A preview or save was refused: no preview stands for the form any more. */
	#fail(failure: RuleError): void {
		this.preview = null;
		this.previewedKey = null;
		this.extra = NO_EXTRA;
		this.error = failure;
		this.previewStatus = 'error';
		if (failure.kind === 'not_found' && this.editing) this.loadStatus = 'missing';
		const generic = Object.keys(fieldErrors(failure)).length === 0;
		if (generic) this.notice = { text: describeRuleError(failure, this.locale), error: true };
	}

	/** Fetch the next page of one preview list (the offset is what is held), in place. */
	async more(name: PreviewListName): Promise<void> {
		const held = this.preview;
		if (!held || this.moreBusy !== null || !this.previewCurrent) return;
		const seq = this.#seq;
		const form = this.form;
		const offset = held[name].rows.length + this.extra[name].length;
		this.moreBusy = name;
		try {
			const out = await this.#write(form, { dryRun: true, limit: PREVIEW_PAGE, offset });
			if (seq !== this.#seq) return;
			if (out.preview[name].total !== held[name].total) {
				// the numbers moved under us: start over rather than mix two answers
				this.notice = { text: 'The result changed; the preview was refreshed.', error: false };
				this.#schedule(true);
				return;
			}
			this.extra = { ...this.extra, [name]: [...this.extra[name], ...out.preview[name].rows] };
		} catch (error) {
			if (seq !== this.#seq) return;
			this.notice = { text: describeRuleError(classifyRuleError(error), this.locale), error: true };
		} finally {
			this.moreBusy = null;
		}
	}

	/** Write the rule as previewed. Null when it was not saved (the reason is in `notice`/`error`). */
	async save(): Promise<SaveResult | null> {
		const held = this.preview;
		if (!this.canSave || !held) return null;
		const form = this.form;
		this.saving = true;
		this.notice = null;
		try {
			const out = await this.#write(form, { expectedCount: held.matches.total, limit: 1 });
			if (!out.rule) return null;
			return {
				rule: out.rule,
				touched: out.settle?.touched_entry_ids.length ?? 0,
				settleFailed: !!out.settle?.error
			};
		} catch (error) {
			await this.#recover(classifyRuleError(error));
			return null;
		} finally {
			this.saving = false;
		}
	}

	async #recover(failure: RuleError): Promise<void> {
		switch (failure.kind) {
			case 'filter_result_changed':
				// nothing was written: show what the rule does now and ask again
				this.notice = { text: describeRuleError(failure, this.locale), error: false };
				this.#schedule(true);
				return;
			case 'stale_reference': {
				const { lookups, failed } = await loadRuleLookups();
				this.lookups = lookups;
				this.lookupsFailed = failed;
				const form = this.form;
				const gone =
					form.target !== null && !this.#exists(form.sets, form.target, lookups)
						? { target: null }
						: {};
				const payeeGone =
					form.condition_payee_id !== null && !lookups.payees.has(form.condition_payee_id)
						? { condition_payee_id: null }
						: {};
				this.form = { ...form, ...gone, ...payeeGone };
				this.error = failure;
				this.#schedule(false);
				this.notice = { text: describeRuleError(failure, this.locale), error: false };
				return;
			}
			case 'network':
			case 'other':
			case 'unauthenticated':
				// nothing says the rule is wrong: keep the preview, so pressing save again retries
				this.notice = { text: describeRuleError(failure, this.locale), error: true };
				return;
			default:
				this.#fail(failure);
		}
	}

	#exists(sets: RuleForm['sets'], id: number, lookups: Lookups): boolean {
		if (sets === 'counter_account') return lookups.accounts.has(id);
		return (sets === 'payee' ? lookups.payees : lookups.categories).has(id);
	}

	/** The page is going away: nothing more may land in the store. */
	dispose(): void {
		this.#seq++;
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		this.#controller?.abort();
		this.#controller = null;
	}
}
