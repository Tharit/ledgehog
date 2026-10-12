import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
// the test stubs the API at its boundary (the one place a component test may name it)
// eslint-disable-next-line no-restricted-imports
import { ApiError, applyTag, createTag } from '#lib/api/index.js';
import { account, applyOut, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter } from '#lib/ledger/filter.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { TagAllFlow } from '#lib/stores/tag-all.svelte.js';
import TagAll from './tag-all.svelte';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	applyTag: vi.fn(),
	createTag: vi.fn()
}));

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash' })],
	tags: [tag({ id: 30, name: 'Lisbon trip' }), tag({ id: 31, name: 'Tax' })]
});

function setup(props: { reason?: string | null; total?: number } = {}) {
	const host = {
		filter: () => ({ ...emptyFilter(), account_id: [1] }),
		locale: () => 'en',
		addTag: vi.fn(),
		applied: vi.fn()
	};
	const flow = new TagAllFlow(host);
	render(TagAll, { props: { flow, lookups, total: 12, reason: null, ...props } });
	return { flow, host };
}

async function openAndChoose(name = 'Lisbon trip') {
	await fireEvent.click(screen.getByRole('button', { name: /Tag all/ }));
	await fireEvent.click(await screen.findByRole('option', { name: new RegExp(name) }));
}

const confirm = () => screen.getByRole('button', { name: /Confirm|Tagging/ });

beforeEach(() => {
	vi.resetAllMocks();
});

describe('TagAll: the button', () => {
	it('says how many entries it would cover', () => {
		setup();

		expect(screen.getByRole('button', { name: 'Tag all 12…' })).toBeEnabled();
	});

	it('is disabled with the reason as its tooltip when the filter is empty', () => {
		setup({ reason: 'Narrow the filter first' });

		const button = screen.getByRole('button', { name: /Tag all/ });
		expect(button).toBeDisabled();
		expect(button.parentElement).toHaveAttribute('title', 'Narrow the filter first');
	});
});

describe('TagAll: the dialog', () => {
	it('first asks for a tag and sends nothing', async () => {
		setup();

		await fireEvent.click(screen.getByRole('button', { name: /Tag all/ }));

		expect(await screen.findByRole('dialog')).toBeInTheDocument();
		expect(screen.getByRole('option', { name: /Lisbon trip/ })).toBeInTheDocument();
		expect(screen.getByRole('option', { name: /Tax/ })).toBeInTheDocument();
		expect(applyTag).not.toHaveBeenCalled();
		expect(confirm()).toBeDisabled();
	});

	it('previews at once: counts, derived skipped, span before to after, per account', async () => {
		vi.mocked(applyTag).mockResolvedValue(
			applyOut({
				newly_tagged: 3,
				already_tagged: 2,
				skipped_derived: 4,
				per_account: [
					{ account_id: 1, newly_tagged: 2 },
					{ account_id: 2, newly_tagged: 1 }
				],
				span_before: { starts_on: '2026-10-05', ends_on: '2026-10-06', entry_count: 2 }
			})
		);
		setup();

		await openAndChoose();

		expect(await screen.findByText(/3 entries will be tagged/)).toBeInTheDocument();
		expect(screen.getByText(/2 already carry it/)).toBeInTheDocument();
		expect(screen.getByText(/4 derived entries skipped/)).toBeInTheDocument();
		const span = screen.getByText(/Span of the tag/);
		expect(span.textContent).toMatch(/2026.*→.*2026/);
		const accounts = screen.getByRole('list', { name: 'Newly tagged by account' });
		expect(accounts).toHaveTextContent('Giro');
		expect(accounts).toHaveTextContent('Cash');
		expect(vi.mocked(applyTag).mock.calls[0][1]).toMatchObject({ dry_run: true, account_id: [1] });
		await waitFor(() => expect(confirm()).toBeEnabled());
	});

	it('leaves out the derived line when none are skipped, and says "no entries yet" for a new span', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ skipped_derived: 0 }));
		setup();

		await openAndChoose();

		await screen.findByText(/entries will be tagged/);
		expect(screen.queryByText(/derived/i, { selector: 'p' })).toBeNull();
		expect(screen.getByText(/no entries yet/)).toBeInTheDocument();
	});

	it('disables Confirm while the preview loads', async () => {
		vi.mocked(applyTag).mockReturnValue(new Promise(() => {}));
		setup();

		await openAndChoose();

		expect(await screen.findByText(/Checking/)).toBeInTheDocument();
		expect(confirm()).toBeDisabled();
	});

	it('says "Nothing to tag" and keeps Confirm disabled when everything is tagged already', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0, already_tagged: 5 }));
		setup();

		await openAndChoose();

		expect(await screen.findByText('Nothing to tag')).toBeInTheDocument();
		expect(screen.getByText(/5 already carry it/)).toBeInTheDocument();
		expect(confirm()).toBeDisabled();
	});

	it('Confirm sends the previewed count as expected_count, patches, closes and says so', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 3 }))
			.mockResolvedValueOnce(applyOut({ dry_run: false, entries: [{ id: 5, tag_ids: [30] }] }));
		const { host } = setup();
		await openAndChoose();
		await waitFor(() => expect(confirm()).toBeEnabled());

		await fireEvent.click(confirm());

		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(vi.mocked(applyTag).mock.calls[1][1]).toMatchObject({
			dry_run: false,
			expected_count: 3,
			all: false
		});
		expect(host.applied).toHaveBeenCalledWith(
			[{ id: 5, tag_ids: [30] }],
			'Tagged 3 entries with "Lisbon trip"'
		);
	});

	it('re-previews when the result changed and asks to confirm again', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 3 }))
			.mockRejectedValueOnce(
				new ApiError(409, 'conflict', 'x', {
					reason: 'filter_result_changed',
					expected: 3,
					actual: 5
				})
			)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 5 }));
		setup();
		await openAndChoose();
		await waitFor(() => expect(confirm()).toBeEnabled());

		await fireEvent.click(confirm());

		expect(
			await screen.findByText('The result changed (was 3, now 5) — please check and confirm again')
		).toBeInTheDocument();
		expect(screen.getByText(/5 entries will be tagged/)).toBeInTheDocument();
		expect(screen.getByRole('dialog')).toBeInTheDocument();
		await waitFor(() => expect(confirm()).toBeEnabled());
	});

	it('shows a failed preview inside the dialog, by its code, with a retry', async () => {
		vi.mocked(applyTag)
			.mockRejectedValueOnce(new ApiError(404, 'not_found', 'x'))
			.mockResolvedValueOnce(applyOut());
		setup();

		await openAndChoose();

		expect(await screen.findByRole('alert')).toHaveTextContent(/no longer exists/);
		expect(confirm()).toBeDisabled();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByText(/entries will be tagged/)).toBeInTheDocument();
	});

	it('shows a network failure of the write inside the dialog and stays open', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut())
			.mockRejectedValueOnce(new ApiError(0, 'network_error', 'x'));
		setup();
		await openAndChoose();
		await waitFor(() => expect(confirm()).toBeEnabled());

		await fireEvent.click(confirm());

		expect(await screen.findByRole('alert')).toHaveTextContent(/could not be reached/);
		expect(screen.getByRole('dialog')).toBeInTheDocument();
	});

	it('creates a tag in place and previews it', async () => {
		vi.mocked(createTag).mockResolvedValue({
			tag: tag({ id: 50, name: 'Holiday' }),
			settle: { error: null, touched_entry_ids: [] }
		});
		vi.mocked(applyTag).mockResolvedValue(applyOut());
		const { host } = setup();
		await fireEvent.click(screen.getByRole('button', { name: /Tag all/ }));
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.input(input, { target: { value: 'Holiday' } });
		await fireEvent.click(await screen.findByRole('option', { name: 'Create tag "Holiday"' }));

		await screen.findByText(/entries will be tagged/);
		expect(createTag).toHaveBeenCalledWith('Holiday');
		expect(host.addTag).toHaveBeenCalled();
		expect(vi.mocked(applyTag).mock.calls[0][0]).toBe(50);
	});

	it('Cancel closes without writing', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut());
		setup();
		await openAndChoose();
		await screen.findByText(/entries will be tagged/);

		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(applyTag).toHaveBeenCalledOnce();
	});
});
