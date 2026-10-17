import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getProvenance } from '#lib/api/index.js';
import { provenance } from './fixtures.js';
import { RowDetail } from './row-detail.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getProvenance: vi.fn()
}));

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => (resolve = res));
	return { promise, resolve };
}

beforeEach(() => vi.resetAllMocks());

describe('RowDetail', () => {
	it('loads a row and holds it', async () => {
		vi.mocked(getProvenance).mockResolvedValue(provenance({ id: 5 }));
		const detail = new RowDetail();
		await detail.show(5);
		expect(detail.status).toBe('ready');
		expect(detail.provenance?.id).toBe(5);
	});

	it('is owned by the newest request: a superseded read never leaves it loading or wrong', async () => {
		const first = deferred<ReturnType<typeof provenance>>();
		vi.mocked(getProvenance).mockReturnValueOnce(first.promise);
		vi.mocked(getProvenance).mockResolvedValueOnce(provenance({ id: 6 }));
		const detail = new RowDetail();

		const one = detail.show(5);
		await detail.show(6);
		first.resolve(provenance({ id: 5 }));
		await one;

		expect(detail.id).toBe(6);
		expect(detail.status).toBe('ready');
		expect(detail.provenance?.id).toBe(6);
	});

	it('goes idle at once when closed while a read is out, and the late answer changes nothing', async () => {
		const pending = deferred<ReturnType<typeof provenance>>();
		vi.mocked(getProvenance).mockReturnValueOnce(pending.promise);
		const detail = new RowDetail();

		const reading = detail.show(5);
		await detail.show(null);
		pending.resolve(provenance({ id: 5 }));
		await reading;

		expect(detail.status).toBe('idle');
		expect(detail.provenance).toBeNull();
		expect(detail.id).toBeNull();
	});

	it('settles on missing or error, never stays loading', async () => {
		vi.mocked(getProvenance).mockRejectedValueOnce(new ApiError(404, 'not_found', 'x'));
		const detail = new RowDetail();
		await detail.show(5);
		expect(detail.status).toBe('missing');
		vi.mocked(getProvenance).mockRejectedValueOnce(new ApiError(500, 'internal', 'x'));
		await detail.show(6);
		expect(detail.status).toBe('error');
	});
});
