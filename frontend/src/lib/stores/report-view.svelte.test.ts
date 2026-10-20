import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/index.js';
import { ReportView } from './report-view.svelte.js';

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (error: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

const make = (fetch: (p: string) => Promise<string>) =>
	new ReportView<string, string>(
		(p) => fetch(p),
		(p) => p
	);

describe('ReportView', () => {
	it('shows the skeleton state until the first answer', async () => {
		const view = make(async (p) => `answer ${p}`);
		expect(view.status).toBe('loading');
		expect(view.data).toBeNull();

		await view.load('a');

		expect(view.status).toBe('ready');
		expect(view.data).toBe('answer a');
	});

	it('keeps the figures on screen while new controls are read', async () => {
		const second = deferred<string>();
		const fetch = vi.fn().mockResolvedValueOnce('first').mockReturnValueOnce(second.promise);
		const view = make(fetch);
		await view.load('a');

		const reading = view.load('b');
		expect(view.status).toBe('ready');
		expect(view.data).toBe('first');

		second.resolve('second');
		await reading;
		expect(view.data).toBe('second');
	});

	it('drops an answer that a later read overtook', async () => {
		const slow = deferred<string>();
		const fetch = vi.fn().mockReturnValueOnce(slow.promise).mockResolvedValueOnce('fast');
		const view = make(fetch);

		const first = view.load('a');
		await view.load('b');
		slow.resolve('slow');
		await first;

		expect(view.data).toBe('fast');
	});

	it('holds the figures when a read for the same controls fails', async () => {
		const fetch = vi.fn().mockResolvedValueOnce('held').mockRejectedValueOnce(new Error('down'));
		const view = make(fetch);
		await view.load('a');

		await view.reload();

		expect(view.status).toBe('ready');
		expect(view.data).toBe('held');
		expect(view.error).toBeNull();
	});

	it('says so when a read for new controls fails, and does not show the old answer', async () => {
		const fetch = vi
			.fn()
			.mockResolvedValueOnce('held')
			.mockRejectedValueOnce(new ApiError(422, 'validation_error', 'Too many periods.'));
		const view = make(fetch);
		await view.load('a');

		await view.load('b');

		expect(view.status).toBe('error');
		expect(view.data).toBeNull();
		expect(view.error?.code).toBe('validation_error');
	});

	it('reads again for the controls last read, and retry leaves the error', async () => {
		const fetch = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce('back');
		const view = make(fetch);
		await view.load('a');
		expect(view.status).toBe('error');

		const retrying = view.retry();
		expect(view.status).toBe('loading');
		await retrying;

		expect(fetch).toHaveBeenLastCalledWith('a');
		expect(view.data).toBe('back');
	});
});
