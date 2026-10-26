// State of the payees screen: the list (by name) and the writes (create, edit, look, delete,
// merge). The list is reloaded after every write; the shared lookups take the fresh list over.
// No domain computation here.
import {
	ApiError,
	createPayee,
	deletePayee,
	listPayees,
	mergePayee,
	updatePayee
} from '#lib/api/index.js';
import { attempt } from '#lib/dimensions/attempt.js';
import { needsReload, type Outcome } from '#lib/dimensions/errors.js';
import { DeleteFlow, MergeFlow } from '#lib/dimensions/flows.svelte.js';
import { plural } from '#lib/dimensions/text.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { indexPayees } from './summary.js';
import type { Payee, PayeeDeleteOut, PayeeMergeOut } from '#lib/types/domain.js';

export type PayeesStatus = 'loading' | 'ready' | 'error';
export type PayeesNotice = { text: string; error: boolean };

/** What an edit sets: `null` clears, absent stays. */
export type PayeePatch = {
	name?: string;
	note?: string | null;
	icon?: string | null;
	color?: string | null;
};

export class PayeesStore {
	payees = $state.raw<Payee[]>([]);
	status = $state<PayeesStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	notice = $state.raw<PayeesNotice | null>(null);

	readonly byId = $derived(indexPayees(this.payees));

	readonly merge = new MergeFlow<PayeeMergeOut>({
		subject: 'payee',
		preview: (id, into) => attempt(() => mergePayee(id, into, { dryRun: true })),
		commit: (id, into, expectedCount) => attempt(() => mergePayee(id, into, { expectedCount })),
		done: (id, out) => void this.#merged(id, out),
		reload: () => this.load()
	});

	readonly remove = new DeleteFlow<PayeeDeleteOut>({
		subject: 'payee',
		preview: (id) => attempt(() => deletePayee(id, { dryRun: true })),
		commit: (id) => attempt(() => deletePayee(id)),
		done: (id, out) => void this.#deleted(out),
		reload: () => this.load()
	});

	/** Load the list. `quiet` keeps what is shown (a reload after a write). */
	async load(quiet = false): Promise<void> {
		if (!quiet) this.status = 'loading';
		try {
			this.payees = await listPayees();
			lookupsStore.setPayees(this.payees);
			this.status = 'ready';
			this.error = null;
		} catch (error) {
			if (quiet && this.status === 'ready') return;
			this.error =
				error instanceof ApiError
					? error
					: new ApiError(0, 'network_error', 'The server could not be reached.');
			this.status = 'error';
		}
	}

	notify(text: string, error = false): void {
		this.notice = { text, error };
	}

	async #after<T extends { settle?: { error: string | null } | null }>(
		outcome: Outcome<T>
	): Promise<Outcome<T>> {
		if (outcome.ok) {
			await this.load(true);
			if (outcome.value.settle?.error) this.notify(SETTLE_STALE);
		} else if (needsReload(outcome.failure)) {
			await this.load(true);
		}
		return outcome;
	}

	async create(name: string, note: string | null = null): Promise<Outcome<Payee>> {
		const outcome = await this.#after(await attempt(() => createPayee({ name, note })));
		return outcome.ok ? { ok: true, value: outcome.value.payee } : outcome;
	}

	async update(id: number, patch: PayeePatch): Promise<Outcome<Payee>> {
		const outcome = await this.#after(await attempt(() => updatePayee(id, patch)));
		return outcome.ok ? { ok: true, value: outcome.value.payee } : outcome;
	}

	async #merged(sourceId: number, out: PayeeMergeOut): Promise<void> {
		const source = this.byId.get(sourceId)?.name ?? 'the payee';
		await this.load(true);
		const text = `Merged ${source} into ${out.target.name} (${plural(out.entry_count, 'entry', 'entries')}, ${plural(out.setting_rule_ids.length + out.condition_rule_ids.length, 'rule', 'rules')}).`;
		this.notify(out.settle?.error ? `${text} ${SETTLE_STALE}` : text);
	}

	async #deleted(out: PayeeDeleteOut): Promise<void> {
		await this.load(true);
		const rules = out.deleted_rule_ids.length;
		this.notify(
			`Deleted ${out.payee.name}${rules > 0 ? ` and ${plural(rules, 'rule', 'rules')}` : ''}.`
		);
	}
}
