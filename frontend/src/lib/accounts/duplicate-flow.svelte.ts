// "Mark as duplicate of…" (spec §5.6, ux/views/account.md): pick the original from the account's
// other imported rows of the same amount, preview both directions (what marking this row would
// remove, what marking the other would) as dry runs, and mark the one the user chooses, the newer
// preselected. The confirming call carries the versions its own preview reported. Nothing of the
// consequences is computed here: the server's answer is what is shown.
import { getEntry, getStatement, markDuplicate } from '#lib/api/index.js';
import type { MarkDuplicateOut, Provenance } from '#lib/api/types.js';
import type { Entry, StatementSource } from '#lib/types/domain.js';
import { isNewer, originalCandidates } from './duplicate.js';
import { classifyWriteError, type WriteFailure } from './errors.js';

/** which of the two rows becomes the duplicate */
export type Direction = 'this' | 'other';

export type Preview =
	| { status: 'checking' }
	| { status: 'ready'; out: MarkDuplicateOut; removed: Entry[] }
	| { status: 'error'; failure: WriteFailure };

/** what a confirmed marking answered: the row marked, the row it duplicates, and what the call touched */
export type MarkResult = { marked: number; of: number; out: MarkDuplicateOut };

/** the most removed entries shown as rows; the count says the rest */
const SHOWN_REMOVED = 20;

export class DuplicateFlow {
	/** the row whose detail was open */
	row = $state.raw<Provenance | null>(null);
	candidates = $state.raw<StatementSource[]>([]);
	candidatesStatus = $state<'loading' | 'ready' | 'error'>('loading');
	pickedId = $state<number | null>(null);
	direction = $state<Direction>('this');
	previews = $state.raw<{ this: Preview; other: Preview } | null>(null);
	failure = $state.raw<WriteFailure | null>(null);
	busy = $state(false);

	#generation = 0;
	#controller: AbortController | null = null;

	readonly picked = $derived(this.candidates.find((c) => c.id === this.pickedId) ?? null);
	readonly canConfirm = $derived.by(() => {
		const preview = this.previews?.[this.direction];
		return this.picked !== null && preview?.status === 'ready' && !this.busy;
	});

	async start(row: Provenance): Promise<void> {
		this.stop();
		this.row = row;
		this.candidates = [];
		this.candidatesStatus = 'loading';
		this.pickedId = null;
		this.direction = 'this';
		this.previews = null;
		this.failure = null;
		this.busy = false;
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		try {
			const page = await getStatement(row.account_id, {
				amount: row.amount.amount,
				limit: 500,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			const sources = page.items.filter((i): i is StatementSource => i.kind === 'source');
			this.candidates = originalCandidates({ id: row.id, booked_on: row.booked_on }, sources);
			this.candidatesStatus = 'ready';
		} catch {
			if (generation !== this.#generation) return;
			this.candidatesStatus = 'error';
		}
	}

	stop(): void {
		this.#controller?.abort();
		this.#controller = null;
		this.#generation++;
	}

	/** Pick the original: both directions are previewed, the newer row preselected as the duplicate. */
	async pick(id: number): Promise<void> {
		const row = this.row;
		const other = this.candidates.find((c) => c.id === id);
		if (!row || !other) return;
		this.pickedId = id;
		this.direction = isNewer({ id: row.id, booked_on: row.booked_on }, other) ? 'this' : 'other';
		this.failure = null;
		await this.#preview();
	}

	choose(direction: Direction): void {
		this.direction = direction;
		this.failure = null;
	}

	async #preview(): Promise<void> {
		const row = this.row;
		const other = this.picked;
		if (!row || !other) return;
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.previews = { this: { status: 'checking' }, other: { status: 'checking' } };
		const one = async (mark: number, of: number): Promise<Preview> => {
			try {
				const out = await markDuplicate(mark, of, { dryRun: true, signal: controller.signal });
				const ids = out.removed_entry_ids.slice(0, SHOWN_REMOVED);
				const found = await Promise.allSettled(ids.map((id) => getEntry(id, controller.signal)));
				const removed = found.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));
				return { status: 'ready', out, removed };
			} catch (error) {
				return { status: 'error', failure: classifyWriteError(error) };
			}
		};
		const [mine, theirs] = await Promise.all([one(row.id, other.id), one(other.id, row.id)]);
		if (generation !== this.#generation) return;
		this.previews = { this: mine, other: theirs };
	}

	/**
	 * Mark the chosen direction. The marked row's id and the answer, or null with the refusal in
	 * `failure`; a conflict (an entry moved) previews again and asks again.
	 */
	async confirm(): Promise<MarkResult | null> {
		const row = this.row;
		const other = this.picked;
		const preview = this.previews?.[this.direction];
		if (!row || !other || preview?.status !== 'ready' || this.busy) return null;
		const marked = this.direction === 'this' ? row.id : other.id;
		const of = this.direction === 'this' ? other.id : row.id;
		const versions = Object.fromEntries(preview.out.versions.map((v) => [v.entry_id, v.version]));
		this.busy = true;
		this.failure = null;
		try {
			const out = await markDuplicate(marked, of, { versions });
			return { marked, of, out };
		} catch (error) {
			const failure = classifyWriteError(error);
			this.failure = failure;
			if (failure.kind === 'conflict') await this.#preview();
			return null;
		} finally {
			this.busy = false;
		}
	}
}
