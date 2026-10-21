import { flushSync } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getQueueCounts, readChanges } from '#lib/api/index.js';
import { ChangeWatcher } from './changes.svelte.js';
import { runLiveData } from './live-data.svelte.js';
import { ReviewCount } from './review-count.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	readChanges: vi.fn(),
	getQueueCounts: vi.fn()
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const counts = (pending_review: number, needs_account: number) => ({
	count: pending_review + needs_account,
	pending_review,
	needs_account
});

const read = (ledger: string, active_task: string | null = null) => ({
	ledger,
	documents: 'b:1',
	accounts: {},
	active_task,
	model_pending: 0
});

let watcher: ChangeWatcher;
let count: ReviewCount;
const auth = $state({ in: false });
const tasks = {
	follow: vi.fn<(task: string | null) => Promise<void>>(),
	dispose: vi.fn<() => void>()
};
let stop: () => void;

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(readChanges).mockResolvedValue(read('b:1'));
	vi.mocked(getQueueCounts).mockResolvedValue(counts(3, 1));
	watcher = new ChangeWatcher();
	count = new ReviewCount();
	auth.in = false;
	stop = $effect.root(() => runLiveData({ watcher, tasks, count, signedIn: () => auth.in }));
});

afterEach(() => {
	stop();
	watcher.stop();
});

describe('what runs for the life of a session', () => {
	it('does nothing while nobody is signed in', async () => {
		flushSync();
		await flush();
		expect(readChanges).not.toHaveBeenCalled();
		expect(getQueueCounts).not.toHaveBeenCalled();
	});

	it('reads once signed in, hands the active task to the task store, and counts the Review item', async () => {
		vi.mocked(readChanges).mockResolvedValue(read('b:1', 't1'));
		auth.in = true;
		flushSync();
		await flush();
		flushSync();

		expect(readChanges).toHaveBeenCalledTimes(1);
		expect(tasks.follow).toHaveBeenCalledWith('t1');
		expect(getQueueCounts).toHaveBeenCalledTimes(1);
		expect(count.count).toBe(4);
		expect(count.pendingReview).toBe(3);
		expect(count.needsAccount).toBe(1);
		expect(count.known).toBe(true);
	});

	it('reads the count again when the ledger moves, and not for a poll that finds no change', async () => {
		auth.in = true;
		flushSync();
		await flush();
		flushSync();
		await flush();
		expect(getQueueCounts).toHaveBeenCalledTimes(1);

		await watcher.read();
		flushSync();
		await flush();
		expect(getQueueCounts).toHaveBeenCalledTimes(1);

		vi.mocked(readChanges).mockResolvedValue(read('b:2'));
		vi.mocked(getQueueCounts).mockResolvedValue(counts(5, 0));
		await watcher.read();
		flushSync();
		await flush();
		expect(getQueueCounts).toHaveBeenCalledTimes(2);
		expect(count.count).toBe(5);
	});

	it('drops everything when the session ends', async () => {
		auth.in = true;
		flushSync();
		await flush();
		flushSync();
		await flush();

		auth.in = false;
		flushSync();

		expect(tasks.dispose).toHaveBeenCalled();
		expect(count.count).toBe(0);
		expect(watcher.valueOf('ledger')).toBeNull();
	});
});

describe('ReviewCount', () => {
	it('keeps only the latest read and the number held when a read fails', async () => {
		let answerFirst!: (n: ReturnType<typeof counts>) => void;
		vi.mocked(getQueueCounts)
			.mockImplementationOnce(() => new Promise((resolve) => (answerFirst = resolve)))
			.mockResolvedValueOnce(counts(2, 0));
		const first = count.refresh();
		await count.refresh();
		answerFirst(counts(9, 0));
		await first;
		expect(count.count).toBe(2);

		vi.mocked(getQueueCounts).mockRejectedValue(new Error('offline'));
		await count.refresh();
		expect(count.count).toBe(2);
	});
});
