import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, deleteDocument } from '#lib/api/index.js';
import { DeleteDocumentFlow } from './delete-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	deleteDocument: vi.fn()
}));

beforeEach(() => vi.resetAllMocks());

describe('DeleteDocumentFlow', () => {
	it('deletes the document it was started for', async () => {
		vi.mocked(deleteDocument).mockResolvedValue({ settle: { touched_entry_ids: [], error: null } });
		const flow = new DeleteDocumentFlow();
		flow.start(7);
		await expect(flow.confirm()).resolves.toBe(true);
		expect(deleteDocument).toHaveBeenCalledWith(7);
		expect(flow.failure).toBeNull();
	});

	it('keeps a refusal in failure', async () => {
		vi.mocked(deleteDocument).mockRejectedValue(new ApiError(404, 'not_found', 'gone'));
		const flow = new DeleteDocumentFlow();
		flow.start(7);
		await expect(flow.confirm()).resolves.toBe(false);
		expect(flow.failure?.text).toMatch(/no longer exists/);
		expect(flow.busy).toBe(false);
	});

	it('does nothing before it is started', async () => {
		await expect(new DeleteDocumentFlow().confirm()).resolves.toBe(false);
		expect(deleteDocument).not.toHaveBeenCalled();
	});
});
