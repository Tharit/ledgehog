import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { changes } from '#lib/stores/changes.svelte.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { queue, unit } from '#lib/units/fixtures.js';
import Page from '../../../routes/review/+page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getQueue: vi.fn(),
	readChanges: vi.fn(),
	setChangesListener: vi.fn(),
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
const {
	getQueue,
	readChanges,
	setChangesListener,
	listAccounts,
	listCategories,
	listPayees,
	listTags
} = api;
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: { open: vi.fn() } }));

const plain = (id: number, text: string) =>
	unit({
		anchor_entry_id: id,
		entries: [entry({ id, unit_key: id, description: text, display_text: text, derivation: {} })]
	});

/** a poll of the change watcher that finds the ledger at this value */
async function pollLedger(ledger: string): Promise<void> {
	readChanges.mockResolvedValue({ ledger, documents: 'b:1', accounts: {}, active_task: null });
	await changes.read();
}

beforeEach(async () => {
	vi.resetAllMocks();
	lookupsStore.reset();
	ruleNames.reset();
	readChanges.mockResolvedValue({
		ledger: 'b:1',
		documents: 'b:1',
		accounts: {},
		active_task: null
	});
	changes.start();
	await changes.read();
	vi.mocked(listAccounts).mockResolvedValue([]);
	vi.mocked(listCategories).mockResolvedValue([]);
	vi.mocked(listPayees).mockResolvedValue([]);
	vi.mocked(listTags).mockResolvedValue([]);
});

afterEach(() => changes.stop());

describe('the review page', () => {
	it('has a title, a one-sentence description and the queue', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));

		render(Page);

		expect(screen.getByRole('heading', { level: 1, name: 'Review' })).toBeInTheDocument();
		expect(screen.getByText(/Units waiting for a decision/)).toBeInTheDocument();
		expect(await screen.findByText('REWE Markt')).toBeInTheDocument();
	});

	it('says that there is new data, uncounted, when the ledger moved, and refetches only on Refresh', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));
		render(Page);
		await screen.findByText('REWE Markt');
		expect(screen.queryByText(/New data/)).toBeNull();

		await pollLedger('b:2');

		expect(await screen.findByText('New data —')).toBeInTheDocument();
		expect(getQueue).toHaveBeenCalledTimes(1);

		vi.mocked(getQueue).mockResolvedValue(
			queue({ pending_review: [plain(1, 'REWE Markt'), plain(2, 'Edeka')] })
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));

		expect(await screen.findByText('Edeka')).toBeInTheDocument();
		await waitFor(() => expect(screen.queryByText(/New data/)).toBeNull());
	});

	it("shows no notice for the tab's own write, and Refresh clears one that came from elsewhere", async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));
		render(Page);
		await screen.findByText('REWE Markt');

		// a write of this tab: its response header carries the values after it
		setChangesListener.mock.calls.at(-1)![0]({
			ledger: 'b:2',
			documents: 'b:1',
			accounts: {}
		});
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(screen.queryByText(/New data/)).toBeNull();

		await pollLedger('b:3');
		expect(await screen.findByText('New data —')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
		await waitFor(() => expect(screen.queryByText(/New data/)).toBeNull());
		expect(getQueue).toHaveBeenCalledTimes(2);
	});

	it('never refetches itself because the ledger moved or the shared lists were refreshed, and keeps the notice until Refresh', async () => {
		vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));
		render(Page);
		await screen.findByText('REWE Markt');

		await pollLedger('b:2');
		expect(await screen.findByText('New data —')).toBeInTheDocument();
		await lookupsStore.reload();
		lookupsStore.setAccounts([]);
		await new Promise((resolve) => setTimeout(resolve, 20));

		expect(getQueue).toHaveBeenCalledTimes(1);
		expect(screen.getByText('New data —')).toBeInTheDocument();
	});

	it('does not poll for new units of its own: the change watcher is the only poll', async () => {
		vi.useFakeTimers();
		try {
			vi.mocked(getQueue).mockResolvedValue(queue({ pending_review: [plain(1, 'REWE Markt')] }));
			render(Page);
			await vi.advanceTimersByTimeAsync(0);
			expect(getQueue).toHaveBeenCalledTimes(1);

			await vi.advanceTimersByTimeAsync(120_000);

			expect(getQueue).toHaveBeenCalledTimes(1);
		} finally {
			vi.useRealTimers();
		}
	});
});
