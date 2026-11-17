import { render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, entry } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { queue, unit } from '#lib/units/fixtures.js';
import Page from '../../../routes/review/+page.svelte';

// The review page keeps its account filter in the address and fetches the queue with it.
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
const route = vi.hoisted(() => ({
	url: new URL('http://localhost/review?account_id=1&account_id=2')
}));
vi.mock('$app/state', () => ({ page: route }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: { open: vi.fn(), unitId: null } }));

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
	ruleNames.reset();
	api.readChanges.mockResolvedValue({
		ledger: 'b:1',
		documents: 'b:1',
		accounts: {},
		active_task: null
	});
	api.listAccounts.mockResolvedValue([
		account({ id: 1, name: 'Giro' }),
		account({ id: 2, name: 'Savings' })
	]);
	api.listCategories.mockResolvedValue([]);
	api.listPayees.mockResolvedValue([]);
	api.listTags.mockResolvedValue([]);
	route.url = new URL('http://localhost/review?account_id=1&account_id=2');
});

describe('the review page account filter', () => {
	it('fetches the queue with the accounts of the address', async () => {
		api.getQueue.mockResolvedValue(
			queue({
				pending_review: [
					unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, derivation: {} })] })
				]
			})
		);
		render(Page);

		await waitFor(() =>
			expect(api.getQueue).toHaveBeenCalledWith(expect.objectContaining({ accountIds: [1, 2] }))
		);
		expect(await screen.findByRole('button', { name: '2 accounts' })).toBeInTheDocument();
		// no text box: the filter bar is the Account chip alone
		expect(screen.queryByRole('textbox', { name: 'Filter entries by text' })).toBeNull();
	});

	it('says so when the filter shows nothing, and offers Clear filters', async () => {
		api.getQueue.mockResolvedValue(queue({}));
		render(Page);

		expect(await screen.findByText('No units match these filters')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
	});
});
