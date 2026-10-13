// The two previewed operations categories and payees share (decision B5, B6): merging into another
// one and deleting. Both ask the server with `dry_run` first, show the consequence list, and write
// only on an explicit confirm. The merge's real run carries the preview's `entry_count`; when it
// has moved the flow re-previews and says so (patterns §7). No domain computation here.
import {
	describeFailure,
	needsReload,
	type DimensionFailure,
	type Outcome,
	type Subject
} from './errors.js';

type Counted = { entry_count: number };

export type MergeHost<Out extends Counted> = {
	subject: Subject;
	preview: (sourceId: number, into: number) => Promise<Outcome<Out>>;
	commit: (sourceId: number, into: number, expectedCount: number) => Promise<Outcome<Out>>;
	/** the merge happened */
	done: (sourceId: number, out: Out) => void;
	/** the lists are out of date (a stale reference, a vanished row) */
	reload: () => void | Promise<void>;
};

export type MergeStatus = 'choosing' | 'previewing' | 'ready' | 'merging';

export class MergeFlow<Out extends Counted> {
	readonly #host: MergeHost<Out>;
	open = $state(false);
	sourceId = $state<number | null>(null);
	targetId = $state<number | null>(null);
	status = $state<MergeStatus>('choosing');
	preview = $state.raw<Out | null>(null);
	failure = $state.raw<DimensionFailure | null>(null);
	/** said after the result moved under the user: the new number, to be confirmed again */
	moved = $state<string | null>(null);

	readonly canConfirm = $derived(this.status === 'ready' && this.preview !== null);
	readonly message = $derived.by(() =>
		this.failure ? describeFailure(this.failure, this.#host.subject) : null
	);

	#generation = 0;

	constructor(host: MergeHost<Out>) {
		this.#host = host;
	}

	start(sourceId: number): void {
		this.#generation++;
		this.sourceId = sourceId;
		this.targetId = null;
		this.preview = null;
		this.failure = null;
		this.moved = null;
		this.status = 'choosing';
		this.open = true;
	}

	/** Back to the target list, keeping nothing of the preview. */
	rechoose(): void {
		if (this.status === 'merging') return;
		this.#generation++;
		this.targetId = null;
		this.preview = null;
		this.failure = null;
		this.moved = null;
		this.status = 'choosing';
	}

	close(): void {
		if (this.status === 'merging') return;
		this.#generation++;
		this.open = false;
	}

	/** Choose the target and ask the server what the merge would do. */
	async choose(targetId: number): Promise<void> {
		if (this.sourceId === null) return;
		this.targetId = targetId;
		this.moved = null;
		await this.#preview(this.sourceId, targetId);
	}

	async #preview(sourceId: number, targetId: number): Promise<boolean> {
		const generation = ++this.#generation;
		this.status = 'previewing';
		this.preview = null;
		this.failure = null;
		const result = await this.#host.preview(sourceId, targetId);
		if (generation !== this.#generation) return false;
		if (result.ok) {
			this.preview = result.value;
			this.status = 'ready';
			return true;
		}
		this.#fail(result.failure);
		return false;
	}

	#fail(failure: DimensionFailure): void {
		this.failure = failure;
		this.status =
			failure.kind === 'stale' || failure.kind === 'not_found' ? 'choosing' : 'choosing';
		if (failure.kind === 'stale' || failure.kind === 'not_found') this.targetId = null;
		if (needsReload(failure)) void this.#host.reload();
	}

	async confirm(): Promise<void> {
		const { sourceId, targetId, preview } = this;
		if (!this.canConfirm || sourceId === null || targetId === null || preview === null) return;
		const generation = ++this.#generation;
		this.status = 'merging';
		const result = await this.#host.commit(sourceId, targetId, preview.entry_count);
		if (generation !== this.#generation) return;
		if (result.ok) {
			this.open = false;
			this.status = 'choosing';
			this.#host.done(sourceId, result.value);
			return;
		}
		if (result.failure.kind === 'count_changed') {
			const before = preview.entry_count;
			if (await this.#preview(sourceId, targetId)) {
				const now = this.preview?.entry_count ?? before;
				this.moved = `The result changed since the preview: it now repoints ${now} ${now === 1 ? 'entry' : 'entries'} (was ${before}). Check it and try again.`;
			}
			return;
		}
		this.#fail(result.failure);
		if (this.targetId !== null) this.status = 'ready';
	}
}

type Deletable = { deletable: boolean };

export type DeleteHost<Out extends Deletable> = {
	subject: Subject;
	preview: (id: number) => Promise<Outcome<Out>>;
	commit: (id: number) => Promise<Outcome<Out>>;
	done: (id: number, out: Out) => void;
	reload: () => void | Promise<void>;
};

export type DeleteStatus = 'previewing' | 'ready' | 'deleting';

export class DeleteFlow<Out extends Deletable> {
	readonly #host: DeleteHost<Out>;
	open = $state(false);
	id = $state<number | null>(null);
	status = $state<DeleteStatus>('previewing');
	preview = $state.raw<Out | null>(null);
	failure = $state.raw<DimensionFailure | null>(null);

	readonly canConfirm = $derived(
		this.status === 'ready' && this.preview !== null && this.preview.deletable
	);
	readonly message = $derived.by(() =>
		this.failure ? describeFailure(this.failure, this.#host.subject) : null
	);

	#generation = 0;

	constructor(host: DeleteHost<Out>) {
		this.#host = host;
	}

	/** Open the dialog and ask the server what stands in the way. */
	async start(id: number): Promise<void> {
		this.id = id;
		this.open = true;
		this.failure = null;
		await this.#preview(id);
	}

	close(): void {
		if (this.status === 'deleting') return;
		this.#generation++;
		this.open = false;
	}

	async #preview(id: number): Promise<void> {
		const generation = ++this.#generation;
		this.status = 'previewing';
		this.preview = null;
		const result = await this.#host.preview(id);
		if (generation !== this.#generation) return;
		if (result.ok) {
			this.preview = result.value;
			this.status = 'ready';
			return;
		}
		this.failure = result.failure;
		this.status = 'ready';
		if (needsReload(result.failure)) void this.#host.reload();
	}

	async confirm(): Promise<void> {
		const id = this.id;
		if (!this.canConfirm || id === null) return;
		const generation = ++this.#generation;
		this.status = 'deleting';
		const result = await this.#host.commit(id);
		if (generation !== this.#generation) return;
		if (result.ok) {
			this.open = false;
			this.status = 'ready';
			this.#host.done(id, result.value);
			return;
		}
		this.status = 'ready';
		const failure = result.failure;
		// it became in use meanwhile: show what holds it now
		if (failure.kind === 'in_use') await this.#preview(id);
		this.failure = failure;
		if (needsReload(failure)) void this.#host.reload();
	}
}
