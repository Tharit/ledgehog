import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
// the test stubs the API at its boundary (the one place a component test may name it)
// eslint-disable-next-line no-restricted-imports
import { ApiError, applyTag, createTag, tagEntry } from '#lib/api/index.js';
import { account, applyOut, entry, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter } from '#lib/ledger/filter.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { TagAllFlow } from '#lib/stores/tag-all.svelte.js';
import type { Entry } from '#lib/types/domain.js';
import TagAll from './tag-all.svelte';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	applyTag: vi.fn(),
	createTag: vi.fn(),
	tagEntry: vi.fn()
}));

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash' })],
	tags: [tag({ id: 30, name: 'Lisbon trip' }), tag({ id: 31, name: 'Tax' })]
});

function setup(props: { reason?: string | null; marked?: Entry[] } = {}) {
	const { marked = [], ...rest } = props;
	const host = {
		filter: () => ({ ...emptyFilter(), account_id: [1] }),
		locale: () => 'en',
		addTag: vi.fn(),
		markedRows: () => marked,
		patch: vi.fn(),
		applied: vi.fn(),
		recover: vi.fn()
	};
	const flow = new TagAllFlow(host);
	render(TagAll, { props: { flow, lookups, reason: null, ...rest } });
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
	it('shows no count: the list may be a snapshot', () => {
		setup();

		expect(screen.getByRole('button', { name: 'Tag all…' })).toBeEnabled();
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

	it('reopens the chooser with a notice when the tag no longer exists', async () => {
		vi.mocked(applyTag)
			.mockRejectedValueOnce(new ApiError(404, 'not_found', 'x'))
			.mockResolvedValueOnce(applyOut());
		const { host } = setup();

		await openAndChoose();

		expect(await screen.findByRole('alert')).toHaveTextContent(
			'This tag no longer exists — the tag list was refreshed.'
		);
		expect(host.recover).toHaveBeenCalled();
		expect(confirm()).toBeDisabled();
		expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
		expect(screen.getByLabelText('Search tags')).toBeInTheDocument();
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

describe('TagAll: the headline', () => {
	it('is generic while the preview loads, then uses the number the server previewed', async () => {
		let resolve!: (value: ReturnType<typeof applyOut>) => void;
		vi.mocked(applyTag).mockReturnValue(new Promise((res) => (resolve = res)));
		setup();

		await fireEvent.click(screen.getByRole('button', { name: /Tag all/ }));
		expect(await screen.findByRole('heading', { name: 'Tag all matching entries' })).toBeVisible();
		await fireEvent.click(await screen.findByRole('option', { name: /Lisbon trip/ }));
		expect(screen.getByRole('heading', { name: 'Tag all matching entries' })).toBeVisible();

		resolve(applyOut({ selected: 5, newly_tagged: 0, already_tagged: 5 }));

		expect(await screen.findByRole('heading', { name: 'Tag all 5 entries' })).toBeVisible();
	});
});

describe('TagAll: rows the user changed', () => {
	const marked = [entry({ id: 7, tag_ids: [] }), entry({ id: 8, tag_ids: [31] })];
	const noneNew = () => vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 0 }));

	it('says nothing about them when there are none', async () => {
		noneNew();
		setup();

		await openAndChoose();
		await screen.findByText('Nothing to tag');

		expect(screen.queryByText(/changed by you/)).toBeNull();
		expect(screen.queryByRole('checkbox')).toBeNull();
	});

	it('explains how many are shown but not part of the filter result', async () => {
		noneNew();
		setup({ marked });

		await fireEvent.click(screen.getByRole('button', { name: /Tag all/ }));

		expect(
			await screen.findByText(
				'2 rows still shown were changed by you and no longer match this filter, so the filter does not include them.'
			)
		).toBeInTheDocument();
	});

	it('offers an unchecked box that counts the rows the chosen tag would change', async () => {
		noneNew();
		setup({ marked });

		await openAndChoose('Lisbon trip');
		const box = await screen.findByRole('checkbox', {
			name: 'Also tag the 2 rows you changed that are still shown'
		});
		expect(box).not.toBeChecked();

		await fireEvent.click(screen.getByRole('button', { name: 'Change tag' }));
		await fireEvent.click(await screen.findByRole('option', { name: /Tax/ }));

		expect(
			await screen.findByRole('checkbox', {
				name: 'Also tag the 1 row you changed that is still shown'
			})
		).not.toBeChecked();
	});

	it('offers no box when every marked row carries the tag or is derived', async () => {
		noneNew();
		setup({ marked: [entry({ id: 8, tag_ids: [30] }), entry({ id: 9, type: 'opening' })] });

		await openAndChoose('Lisbon trip');

		await screen.findByText('Nothing to tag');
		expect(screen.queryByRole('checkbox')).toBeNull();
		expect(screen.getByText(/2 rows still shown/)).toBeInTheDocument();
	});

	it('keeps Confirm off with the box unchecked and Nothing to tag, and enables it when checked', async () => {
		noneNew();
		setup({ marked });
		await openAndChoose('Lisbon trip');

		expect(await screen.findByText('Nothing to tag')).toBeInTheDocument();
		expect(confirm()).toBeDisabled();

		await fireEvent.click(screen.getByRole('checkbox'));

		expect(screen.queryByText('Nothing to tag')).toBeNull();
		expect(screen.getByText('2 rows you changed')).toBeInTheDocument();
		expect(confirm()).toBeEnabled();
	});

	it('adds "plus N rows you changed" to a filter result that tags something', async () => {
		vi.mocked(applyTag).mockResolvedValue(applyOut({ newly_tagged: 3 }));
		setup({ marked });
		await openAndChoose('Lisbon trip');
		await screen.findByText(/3 entries will be tagged/);
		expect(confirm()).toBeEnabled();

		await fireEvent.click(screen.getByRole('checkbox'));

		expect(screen.getByText('plus 2 rows you changed')).toBeInTheDocument();
	});

	it('tags only the rows, with no apply request, when the filter has nothing new', async () => {
		noneNew();
		vi.mocked(tagEntry).mockImplementation(async (id) => ({
			changed: true,
			entry: { id, tag_ids: [30] },
			settle: { error: null, touched_entry_ids: [] }
		}));
		const { host } = setup({ marked });
		await openAndChoose('Lisbon trip');
		await fireEvent.click(await screen.findByRole('checkbox'));

		await fireEvent.click(confirm());

		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(applyTag).toHaveBeenCalledOnce();
		expect(
			vi
				.mocked(tagEntry)
				.mock.calls.map((c) => c[0])
				.sort()
		).toEqual([7, 8]);
		expect(host.applied).toHaveBeenCalledWith(
			expect.arrayContaining([{ id: 7, tag_ids: [30] }]),
			'Tagged 2 rows you changed with "Lisbon trip"'
		);
	});

	it('keeps the dialog open on a partial failure and says what went through', async () => {
		vi.mocked(applyTag)
			.mockResolvedValueOnce(applyOut({ newly_tagged: 3 }))
			.mockResolvedValueOnce(applyOut({ dry_run: false, newly_tagged: 3 }))
			.mockResolvedValueOnce(applyOut({ newly_tagged: 0 }));
		vi.mocked(tagEntry).mockImplementation(async (id) => {
			if (id === 8) throw new ApiError(404, 'not_found', 'x');
			return {
				changed: true,
				entry: { id, tag_ids: [30] },
				settle: { error: null, touched_entry_ids: [] }
			};
		});
		const { host } = setup({ marked });
		await openAndChoose('Lisbon trip');
		await screen.findByText(/3 entries will be tagged/);
		await fireEvent.click(screen.getByRole('checkbox'));

		await fireEvent.click(confirm());

		const report = await screen.findByRole('alert');
		expect(report).toHaveTextContent('Tagged 3 entries with "Lisbon trip"');
		expect(report).toHaveTextContent(
			'Tagged 1 of 2 of the rows you changed; 1 failed (This entry or tag no longer exists'
		);
		expect(screen.getByRole('dialog')).toBeInTheDocument();
		expect(host.applied).not.toHaveBeenCalled();
		expect(host.patch).toHaveBeenCalledWith(expect.arrayContaining([{ id: 7, tag_ids: [30] }]));
	});
});
