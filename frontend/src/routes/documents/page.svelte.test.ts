import { render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listDocuments } from '#lib/api/index.js';
import { changes } from '#lib/stores/changes.svelte.js';
import Page from './+page.svelte';

const route = vi.hoisted(() => ({ page: { url: new URL('http://localhost/documents') } }));
vi.mock('$app/state', () => ({ page: route.page }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listDocuments: vi.fn(),
	readChanges: vi.fn(),
	listDocumentProviders: vi.fn(async () => []),
	listAccounts: vi.fn(async () => []),
	listCategories: vi.fn(async () => []),
	listPayees: vi.fn(async () => []),
	listTags: vi.fn(async () => [])
}));

beforeEach(() => {
	vi.resetAllMocks();
	changes.modelPending = 0;
	changes.modelPendingLines = 0;
	vi.mocked(listDocuments).mockResolvedValue({ documents: [], total: 0, limit: 100, offset: 0 });
});

describe('documents page: the model is looking', () => {
	it('says how many lines, in one quiet line above the list', async () => {
		changes.modelPendingLines = 3;
		render(Page);

		const line = await screen.findByText('The model is looking at 3 lines.');
		expect(line).toHaveAttribute('data-slot', 'model-pending-line');
		expect(line).toHaveClass('text-sm', 'text-muted-foreground');
	});

	it('says "1 line" for one', async () => {
		changes.modelPendingLines = 1;
		render(Page);

		expect(await screen.findByText('The model is looking at 1 line.')).toBeInTheDocument();
	});

	it('says nothing while no line is pending, also with entries pending', async () => {
		changes.modelPending = 4;
		render(Page);

		await waitFor(() => expect(listDocuments).toHaveBeenCalled());
		expect(screen.queryByText(/The model is looking/)).toBeNull();
	});
});
