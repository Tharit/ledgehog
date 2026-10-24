// The change watcher (architecture §4.2): ONE store, started at the root layout once the session is
// known. It reads `GET /api/changes` when the app starts, every 30 s (every 5 s while the model has entries or lines pending) and when the tab becomes
// visible again, and holds the current change values of the ledger, the documents and each account.
// A value is opaque: a view compares it with the one it saw and never reads it. The same read
// carries the user's active task, which goes to whoever asked (the sync store).
//
// The tab's own writes: every write's response carries the values after it (`X-Ledger-Changes`).
// The watcher takes them as current and moves the "seen" value of every watch to them, so a tab
// never announces its own change. A read that began before the tab's latest write response may
// answer with the values from before the write: it is ignored (the stale-read rule).
import {
	readChanges,
	setChangesListener,
	type ChangeRead,
	type ChangeValues
} from '#lib/api/index.js';

/** What a view watches: the ledger (list and review queue), the documents, or one account. */
export type ChangeKey = 'ledger' | 'documents' | { account: number };

/** A watch as the watcher sees it: it can take the current value, or fill one it never had. */
export type Watching = { take(): void; fill(): void };

export const POLL_MS = 30_000;
/** while the model still has entries to look at, its answers are waited for: a read every 5 s */
export const MODEL_POLL_MS = 5_000;

export class ChangeWatcher {
	/** the current values; null until the first read (or an own write) has answered */
	ledger = $state<string | null>(null);
	documents = $state<string | null>(null);
	accounts = $state.raw<Record<string, string>>({});
	/** how many entries the model still has to look at; 0 until read, and without a model */
	modelPending = $state(0);
	/** how many document lines the model still has to look at; likewise */
	modelPendingLines = $state(0);

	// watches are held weakly: a page's store that is dropped needs no unregistering
	#watches: WeakRef<Watching>[] = [];
	#onActiveTask: ((task: string | null) => void) | undefined;
	#timer: ReturnType<typeof setInterval> | null = null;
	#every = 0;
	#running = false;
	/** one counter numbers the reads and the write responses, so their order is known */
	#seq = 0;
	#lastWrite = 0;
	#applied = 0;

	/** The current value of a key, or null while there is none (not yet read, or an account never seen). */
	valueOf(key: ChangeKey): string | null {
		if (key === 'ledger') return this.ledger;
		if (key === 'documents') return this.documents;
		return this.accounts[String(key.account)] ?? null;
	}

	/** Register a watch: from now on it moves with the tab's own writes. */
	register(watch: Watching): void {
		this.#watches.push(new WeakRef(watch));
	}

	/**
	 * Begin reading: now, every 30 s, and whenever the tab becomes visible. `onActiveTask` is told the
	 * user's active task (or null) after every read that is taken.
	 */
	start(onActiveTask?: (task: string | null) => void): void {
		if (this.#running) return;
		this.#running = true;
		this.#onActiveTask = onActiveTask;
		setChangesListener((values) => this.#adopt(values));
		this.#every = 0;
		this.#pace();
		document.addEventListener('visibilitychange', this.#onVisible);
		void this.read();
	}

	/** The session ended: stop reading and forget the values. */
	stop(): void {
		this.#running = false;
		if (this.#timer !== null) clearInterval(this.#timer);
		this.#timer = null;
		this.#every = 0;
		document.removeEventListener('visibilitychange', this.#onVisible);
		setChangesListener(null);
		this.#onActiveTask = undefined;
		this.ledger = null;
		this.documents = null;
		this.accounts = {};
		this.modelPending = 0;
		this.modelPendingLines = 0;
		this.#seq = this.#lastWrite = this.#applied = 0;
	}

	/** One read of the change values. A failed read is no news; the next one tries again. */
	async read(): Promise<void> {
		const n = ++this.#seq;
		let out: ChangeRead;
		try {
			out = await readChanges();
		} catch {
			return;
		}
		// began before the tab's latest write response, or before a read already taken: out of date
		if (!this.#running || n < this.#lastWrite || n < this.#applied) return;
		this.#applied = n;
		this.#set(out);
		this.modelPending = out.model_pending;
		this.modelPendingLines = out.model_pending_lines;
		this.#pace();
		for (const watch of this.#live()) watch.fill();
		this.#onActiveTask?.(out.active_task);
	}

	/** The one cadence rule: every 5 s while the model has entries or lines pending, otherwise every 30 s. */
	#pace(): void {
		const every = this.modelPending > 0 || this.modelPendingLines > 0 ? MODEL_POLL_MS : POLL_MS;
		if (every === this.#every && this.#timer !== null) return;
		if (this.#timer !== null) clearInterval(this.#timer);
		this.#every = every;
		this.#timer = setInterval(() => void this.read(), every);
	}

	readonly #onVisible = () => {
		if (document.visibilityState === 'visible') void this.read();
	};

	/** The values after this tab's own write: current now, and what every watch has seen. */
	#adopt(values: ChangeValues): void {
		this.#lastWrite = ++this.#seq;
		this.#set(values);
		for (const watch of this.#live()) watch.take();
	}

	#set(values: ChangeValues): void {
		this.ledger = values.ledger;
		this.documents = values.documents;
		this.accounts = { ...this.accounts, ...values.accounts };
	}

	#live(): Watching[] {
		const live: Watching[] = [];
		this.#watches = this.#watches.filter((ref) => {
			const watch = ref.deref();
			if (watch) live.push(watch);
			return watch !== undefined;
		});
		return live;
	}
}

/** The one watcher of the app. */
export const changes = new ChangeWatcher();
