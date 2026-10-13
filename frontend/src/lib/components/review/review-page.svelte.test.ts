import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { queue, unit } from '#lib/units/fixtures.js';
import Page from '../../../routes/review/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getQueue: vi.fn(),
	getNewUnitCount: vi.fn(),
	listRules: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn(),
	listTags: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getQueue, getNewUnitCount, listAccounts, listCategories, listPayees, listTags } = api;
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: { open: vi.fn() } }));

const plain = (id: number, text: string) =>
	unit({
		anchor_entry_id: id,
		entries: [entry({ id, unit_key: id, display_text: text, derivation: {} })]
	});

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
	ruleNames.reset();
	vi.mocked(listAccounts).mockResolvedValue([]);
	vi.mocked(listCategories).mockResolvedValue([]);
	vi.mocked(listPayees).mockResolvedValue([]);
	vi.mocked(listTags).mockResolvedValue([]);
});

describe('the review page', () => {
	it('has a title, a one-sentence description and the queue', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));

		render(Page);

		expect(screen.getByRole('heading', { level: 1, name: 'Review' })).toBeInTheDocument();
		expect(screen.getByText(/Units waiting for a decision/)).toBeInTheDocument();
		expect(await screen.findByText('REWE Markt')).toBeInTheDocument();
	});

	it('says how many units are new when the window gets focus, and refetches only on Refresh', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));
		vi.mocked(getNewUnitCount).mockResolvedValue({ new_count: 12, snapshot: 'snap-2' });
		render(Page);
		await screen.findByText('REWE Markt');
		expect(screen.queryByText(/new$/)).toBeNull();

		window.dispatchEvent(new Event('focus'));

		expect(await screen.findByText('12 new')).toBeInTheDocument();
		expect(getQueue).toHaveBeenCalledTimes(1);
		expect(getNewUnitCount).toHaveBeenCalledWith('snap-1', expect.any(AbortSignal));

		vi.mocked(getQueue).mockResolvedValue(
			queue({ pending_review: [plain(1, 'REWE Markt'), plain(2, 'Edeka')] })
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));

		expect(await screen.findByText('Edeka')).toBeInTheDocument();
		await waitFor(() => expect(screen.queryByText('12 new')).toBeNull());
	});

	it('polls every minute', async () => {
		vi.useFakeTimers();
		try {
			vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));
			vi.mocked(getNewUnitCount).mockResolvedValue({ new_count: 0, snapshot: 'snap-1' });
			render(Page);
			await vi.advanceTimersByTimeAsync(0);
			expect(getQueue).toHaveBeenCalled();

			await vi.advanceTimersByTimeAsync(60_000);

			expect(getNewUnitCount).toHaveBeenCalledTimes(1);
		} finally {
			vi.useRealTimers();
		}
	});
});
