// The edit form's state: the account is fixed, amount, date and purpose change. The static §5.6
// warning above Save is the confirmation (D214); a debounced dry run says what the edit would do
// and supplies the versions the real save carries. Nothing is saved before a dry run has answered
// for the values as they stand.
import { ApiError, updateSource, type SourceChanges } from '#lib/api/index.js';
import type { SourceEditEffects } from '#lib/api/types.js';
import { session } from '#lib/stores/session.svelte.js';
import { amountText, signOf, type Sign } from './amount.js';
import { entryForm, type EditTarget } from './controller.svelte.js';
import { summarizeEdit } from './effects.js';
import { classifyEntryError } from './errors.js';
import { validateEntry, type FieldErrors } from './validate.js';
import type { FlowFeedback } from './add-flow.svelte.js';

export const DRY_RUN_DELAY_MS = 300;

export type PreviewStatus = 'idle' | 'checking' | 'ready' | 'error';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class EditFlow {
	target = $state.raw<EditTarget | null>(null);
	date = $state('');
	amountText = $state('');
	sign = $state<Sign>('expense');
	purpose = $state('');

	errors = $state.raw<FieldErrors>({});
	feedback = $state.raw<FlowFeedback | null>(null);
	busy = $state(false);
	status = $state<PreviewStatus>('idle');
	/** what the edit would do, one line each; empty: nothing to report */
	lines = $state.raw<string[]>([]);
	/** the row is gone: nothing can be saved */
	gone = $state(false);

	#effects: SourceEditEffects | null = null;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#generation = 0;
	#controller: AbortController | null = null;
	#initial = { date: '', amountText: '', sign: 'expense' as Sign, purpose: '', minor: 0 };

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly currency = $derived(this.target?.entry.amount.currency ?? 'EUR');
	/** every field, as one value to watch: a change schedules the dry run */
	readonly fingerprint = $derived(
		JSON.stringify([this.date, this.amountText, this.sign, this.purpose])
	);
	readonly canSave = $derived(this.status === 'ready' && !this.busy && !this.gone);

	start(target: EditTarget): void {
		this.#cancel();
		this.target = target;
		const { entry, sourceMinor } = target;
		const locale = this.locale;
		this.date = entry.booked_on;
		this.amountText = amountText(sourceMinor, entry.amount.currency, locale);
		this.sign = signOf(sourceMinor);
		this.purpose = entry.source?.purpose ?? '';
		this.#initial = {
			date: this.date,
			amountText: this.amountText,
			sign: this.sign,
			purpose: this.purpose.trim(),
			minor: sourceMinor
		};
		this.errors = {};
		this.feedback = null;
		this.busy = false;
		this.status = 'idle';
		this.lines = [];
		this.gone = false;
		this.#effects = null;
	}

	/** Stop everything under way (the dialog closed). */
	stop(): void {
		this.#cancel();
	}

	#cancel(): void {
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = null;
		this.#controller?.abort();
		this.#controller = null;
		this.#generation++;
	}

	/** The fields changed: check again after a pause. */
	schedule(): void {
		if (!this.target) return;
		this.#cancel();
		this.#effects = null;
		this.lines = [];
		this.feedback = null;
		const changes = this.#changes();
		this.errors = changes.errors;
		if (changes.input === null || changes.diff === null) {
			this.status = 'idle';
			return;
		}
		this.status = 'checking';
		this.#timer = setTimeout(() => void this.#dryRun(), DRY_RUN_DELAY_MS);
	}

	/** "Try again" after a dry run that could not be had. */
	retry(): void {
		this.feedback = null;
		this.#cancel();
		this.status = 'checking';
		void this.#dryRun();
	}

	/** What differs from the row as opened, validated; `diff` null when nothing differs or it is invalid. */
	#changes(): {
		errors: FieldErrors;
		input: { amount: number } | null;
		diff: SourceChanges | null;
	} {
		const target = this.target!;
		const checked = validateEntry(
			{
				accountId: target.entry.account_id,
				currency: this.currency,
				date: this.date,
				amountText: this.amountText,
				sign: this.sign,
				purpose: this.purpose
			},
			this.locale
		);
		if (checked.input === null) return { errors: checked.errors, input: null, diff: null };
		const diff: SourceChanges = {};
		if (checked.input.amount !== this.#initial.minor) diff.amount = checked.input.amount;
		if (checked.input.booked_on !== this.#initial.date) diff.booked_on = checked.input.booked_on;
		if ((checked.input.purpose ?? '') !== this.#initial.purpose)
			diff.purpose = checked.input.purpose;
		return {
			errors: checked.errors,
			input: checked.input,
			diff: Object.keys(diff).length === 0 ? null : diff
		};
	}

	async #dryRun(): Promise<void> {
		const target = this.target;
		const changes = this.#changes();
		if (!target || changes.diff === null) return;
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		try {
			const out = await updateSource(target.entry.source_transaction_id!, changes.diff, {
				dryRun: true,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.#effects = out.effects;
			this.lines = summarizeEdit(out.effects);
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.status = 'error';
			this.#reject(asApiError(error));
		}
	}

	/** The real save, with the versions the last dry run reported. True when it was saved. */
	async save(): Promise<boolean> {
		const target = this.target;
		const effects = this.#effects;
		if (!target || !effects || !this.canSave) return false;
		const changes = this.#changes();
		if (changes.diff === null) return false;
		const versions = Object.fromEntries(effects.versions.map((v) => [v.entry_id, v.version]));
		this.busy = true;
		this.feedback = null;
		try {
			const out = await updateSource(target.entry.source_transaction_id!, changes.diff, {
				versions
			});
			this.busy = false;
			entryForm.edited(out);
			return true;
		} catch (error) {
			this.busy = false;
			const failure = classifyEntryError(asApiError(error));
			if (failure.kind === 'conflict') {
				// the world moved: read the unit again and check the consequences anew
				entryForm.refreshPanel();
				this.feedback = { kind: 'conflict', text: failure.text };
				this.#cancel();
				this.status = 'checking';
				void this.#dryRun();
				return false;
			}
			this.#reject(asApiError(error));
			return false;
		}
	}

	#reject(error: ApiError): void {
		const failure = classifyEntryError(error);
		switch (failure.kind) {
			case 'field':
				this.errors = { [failure.field]: failure.text };
				break;
			case 'gone':
				this.gone = true;
				this.feedback = { kind: 'error', text: failure.text };
				break;
			case 'error':
				this.feedback = { kind: 'error', text: failure.text, retryable: failure.retryable };
				break;
			default:
				this.feedback = { kind: 'error', text: failure.text };
		}
	}
}
