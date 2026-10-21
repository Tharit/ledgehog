import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	readChanges,
	setChangesListener,
	type ChangeRead,
	type ChangeValues
} from '#lib/api/index.js';
import { ChangeWatcher, MODEL_POLL_MS, POLL_MS } from './changes.svelte.js';
import { NewDataWatch } from './new-data.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	readChanges: vi.fn(),
	setChangesListener: vi.fn()
}));

const read = (over: Partial<ChangeRead> = {}): ChangeRead => ({
	ledger: 'b:1',
	documents: 'b:1',
	accounts: { '7': 'b:1' },
	active_task: null,
	model_pending: 0,
	...over
});

/** the write response header's values, as the request layer hands them over */
function writeResponse(values: ChangeValues): void {
	const listener = vi.mocked(setChangesListener).mock.calls.at(-1)?.[0];
	listener?.(values);
}

let watcher: ChangeWatcher;

beforeEach(() => {
	vi.resetAllMocks();
	vi.useFakeTimers();
	vi.mocked(readChanges).mockResolvedValue(read());
	watcher = new ChangeWatcher();
});

afterEach(() => {
	watcher.stop();
	vi.useRealTimers();
});

describe('ChangeWatcher: when it reads', () => {
	it('reads once at start and holds the values', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(readChanges).toHaveBeenCalledTimes(1);
		expect(watcher.valueOf('ledger')).toBe('b:1');
		expect(watcher.valueOf('documents')).toBe('b:1');
		expect(watcher.valueOf({ account: 7 })).toBe('b:1');
		expect(watcher.valueOf({ account: 8 })).toBeNull();
	});

	it('reads again every 30 s', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(POLL_MS);
		expect(readChanges).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(POLL_MS);
		expect(readChanges).toHaveBeenCalledTimes(3);
	});

	it('reads every 5 s while the model has entries pending, and back every 30 s at zero', async () => {
		vi.mocked(readChanges).mockResolvedValue(read({ model_pending: 3 }));
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(watcher.modelPending).toBe(3);
		expect(readChanges).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(MODEL_POLL_MS);
		expect(readChanges).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(MODEL_POLL_MS);
		expect(readChanges).toHaveBeenCalledTimes(3);

		vi.mocked(readChanges).mockResolvedValue(read({ model_pending: 0 }));
		await vi.advanceTimersByTimeAsync(MODEL_POLL_MS); // the read that sees zero
		expect(watcher.modelPending).toBe(0);
		expect(readChanges).toHaveBeenCalledTimes(4);
		await vi.advanceTimersByTimeAsync(MODEL_POLL_MS * 5);
		expect(readChanges).toHaveBeenCalledTimes(4);
		await vi.advanceTimersByTimeAsync(POLL_MS);
		expect(readChanges).toHaveBeenCalledTimes(5);
	});

	it('speeds up when a later read finds the model pending', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(POLL_MS); // 2 reads
		vi.mocked(readChanges).mockResolvedValue(read({ model_pending: 1 }));
		await vi.advanceTimersByTimeAsync(POLL_MS); // 3rd read, pending
		expect(readChanges).toHaveBeenCalledTimes(3);
		await vi.advanceTimersByTimeAsync(MODEL_POLL_MS);
		expect(readChanges).toHaveBeenCalledTimes(4);
	});

	it('reads when the tab becomes visible, not when it is hidden', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
		document.dispatchEvent(new Event('visibilitychange'));
		expect(readChanges).toHaveBeenCalledTimes(1);

		vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
		document.dispatchEvent(new Event('visibilitychange'));
		expect(readChanges).toHaveBeenCalledTimes(2);
	});

	it('stops reading, and forgets the values, when stopped', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		watcher.stop();
		await vi.advanceTimersByTimeAsync(POLL_MS * 2);
		expect(readChanges).toHaveBeenCalledTimes(1);
		expect(watcher.valueOf('ledger')).toBeNull();
	});

	it('keeps what it holds when a read fails', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		vi.mocked(readChanges).mockRejectedValue(new Error('offline'));
		await watcher.read();
		expect(watcher.valueOf('ledger')).toBe('b:1');
	});

	it("tells the user's active task after every read", async () => {
		const onActive = vi.fn();
		vi.mocked(readChanges).mockResolvedValue(read({ active_task: 't1' }));
		watcher.start(onActive);
		await vi.advanceTimersByTimeAsync(0);
		expect(onActive).toHaveBeenLastCalledWith('t1');

		vi.mocked(readChanges).mockResolvedValue(read({ active_task: null }));
		await watcher.read();
		expect(onActive).toHaveBeenLastCalledWith(null);
		expect(onActive).toHaveBeenCalledTimes(2);
	});
});

describe('ChangeWatcher: the stale-read rule', () => {
	it('ignores a read that began before the latest write response and answered after it', async () => {
		let answerOld!: (value: ChangeRead) => void;
		vi.mocked(readChanges).mockImplementationOnce(
			() => new Promise((resolve) => (answerOld = resolve))
		);
		const onActive = vi.fn();
		watcher.start(onActive); // the first read is in flight
		const news = new NewDataWatch('ledger', watcher);

		// the tab writes meanwhile: its response carries the values after the write
		writeResponse({ ledger: 'b:2', documents: 'b:1', accounts: {} });
		expect(watcher.valueOf('ledger')).toBe('b:2');

		// the read that began before the write answers, with the values from before it
		answerOld(read({ ledger: 'b:1' }));
		await vi.advanceTimersByTimeAsync(0);

		expect(watcher.valueOf('ledger')).toBe('b:2');
		expect(news.stale).toBe(false);
		expect(onActive).not.toHaveBeenCalled();
	});

	it('takes a read that began after the write response', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		writeResponse({ ledger: 'b:2', documents: 'b:1', accounts: {} });

		vi.mocked(readChanges).mockResolvedValue(read({ ledger: 'b:3' }));
		await watcher.read();
		expect(watcher.valueOf('ledger')).toBe('b:3');
	});

	it('ignores a read that answers after a later read already did', async () => {
		let answerFirst!: (value: ChangeRead) => void;
		vi.mocked(readChanges)
			.mockImplementationOnce(() => new Promise((resolve) => (answerFirst = resolve)))
			.mockResolvedValueOnce(read({ ledger: 'b:5' }));
		watcher.start();
		await watcher.read();
		expect(watcher.valueOf('ledger')).toBe('b:5');

		answerFirst(read({ ledger: 'b:4' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(watcher.valueOf('ledger')).toBe('b:5');
	});
});

describe('ChangeWatcher: what a view sees', () => {
	it("adopts the tab's own write: no notice, for any registered watch", async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		const ledger = new NewDataWatch('ledger', watcher);
		const documents = new NewDataWatch('documents', watcher);
		const account = new NewDataWatch({ account: 7 }, watcher);

		writeResponse({ ledger: 'b:2', documents: 'b:2', accounts: { '7': 'b:2' } });

		expect(ledger.stale).toBe(false);
		expect(documents.stale).toBe(false);
		expect(account.stale).toBe(false);
	});

	it('a foreign change, from a poll, makes the matching key stale and not the others', async () => {
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		const ledger = new NewDataWatch('ledger', watcher);
		const documents = new NewDataWatch('documents', watcher);
		const seven = new NewDataWatch({ account: 7 }, watcher);
		const eight = new NewDataWatch({ account: 8 }, watcher);

		vi.mocked(readChanges).mockResolvedValue(read({ accounts: { '7': 'b:2' } }));
		await watcher.read();
		expect(seven.stale).toBe(true);
		expect(ledger.stale).toBe(false);
		expect(documents.stale).toBe(false);
		expect(eight.stale).toBe(false);

		vi.mocked(readChanges).mockResolvedValue(read({ documents: 'b:2', accounts: { '7': 'b:2' } }));
		await watcher.read();
		expect(documents.stale).toBe(true);

		vi.mocked(readChanges).mockResolvedValue(
			read({ ledger: 'b:2', documents: 'b:2', accounts: { '7': 'b:2' } })
		);
		await watcher.read();
		expect(ledger.stale).toBe(true);

		// a refetch takes the current values
		ledger.take();
		expect(ledger.stale).toBe(false);
	});

	it('a view that fetched before the first read has what that read says', async () => {
		const news = new NewDataWatch('ledger', watcher); // fetched, nothing read yet
		expect(news.stale).toBe(false);

		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		expect(news.stale).toBe(false);

		vi.mocked(readChanges).mockResolvedValue(read({ ledger: 'b:2' }));
		await watcher.read();
		expect(news.stale).toBe(true);
	});

	it("a watch rekeyed to another account takes that account's value", async () => {
		vi.mocked(readChanges).mockResolvedValue(read({ accounts: { '7': 'b:1', '8': 'b:4' } }));
		watcher.start();
		await vi.advanceTimersByTimeAsync(0);
		const news = new NewDataWatch(null, watcher);
		expect(news.stale).toBe(false);

		news.rekey({ account: 8 });
		expect(news.stale).toBe(false);
		vi.mocked(readChanges).mockResolvedValue(read({ accounts: { '7': 'b:1', '8': 'b:5' } }));
		await watcher.read();
		expect(news.stale).toBe(true);
	});
});
