import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
/* eslint-disable no-restricted-imports -- the test stubs the API at its boundary */
import { ApiError, createTag, deleteTag, listTags, updateTag } from '#lib/api/index.js';
/* eslint-enable no-restricted-imports */
import { formatDate } from '#lib/format/index.js';
import { tag } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { TagsStore } from '#lib/tags/store.svelte.js';
import type { Tag } from '#lib/types/domain.js';
import TagManager from './tag-manager.svelte';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listTags: vi.fn(),
	createTag: vi.fn(),
	updateTag: vi.fn(),
	deleteTag: vi.fn()
}));

const holiday = tag({
	id: 1,
	name: 'Holiday',
	color: 'plum',
	starts_on: '2026-03-03',
	ends_on: '2026-03-09',
	entry_count: 12
});
const unused = tag({ id: 2, name: 'Unused', color: null, entry_count: 0 });
const one = tag({
	id: 3,
	name: 'Gift',
	color: null,
	starts_on: '2026-05-01',
	ends_on: '2026-05-01',
	entry_count: 1
});

async function setup(tags: Tag[] = [holiday, unused, one]) {
	vi.mocked(listTags).mockResolvedValue(tags);
	const store = new TagsStore();
	render(TagManager, { props: { store } });
	await waitFor(() => expect(store.status).toBe('ready'));
	return store;
}

const written = (t: Tag) => ({ tag: t, settle: { error: null, touched_entry_ids: [] } });

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
});

const headerAdd = () =>
	within(document.querySelector('[data-slot="page-header"]') as HTMLElement).getByRole('button', {
		name: 'Add tag'
	});

async function chooseFromMenu(name: string, item: string) {
	await fireEvent.keyDown(screen.getByRole('button', { name: `More actions for ${name}` }), {
		key: 'Enter'
	});
	const menu = await screen.findByRole('menu');
	await fireEvent.click(within(menu).getByRole('menuitem', { name: item }));
}

describe('TagManager: loading and list', () => {
	it('shows skeleton rows while loading, not a text line', () => {
		vi.mocked(listTags).mockReturnValue(new Promise(() => {}));
		render(TagManager, { props: { store: new TagsStore() } });

		const loading = document.querySelector('[data-slot="tags-loading"]') as HTMLElement;
		expect(loading).toHaveAttribute('aria-busy', 'true');
		expect(loading.children.length).toBeGreaterThan(0);
		expect(screen.queryByText(/Loading/)).toBeNull();
	});

	it('shows name, entry count and span, or "0 entries" for an unused tag', async () => {
		await setup();

		const row = document.querySelector('[data-tag-id="1"]') as HTMLElement;
		expect(within(row).getByText('Holiday')).toBeInTheDocument();
		expect(within(row).getByText('12 entries')).toBeInTheDocument();
		expect(
			within(row).getByText(`${formatDate('2026-03-03')} – ${formatDate('2026-03-09')}`)
		).toBeInTheDocument();
		const empty = document.querySelector('[data-tag-id="2"]') as HTMLElement;
		expect(within(empty).getByText('0 entries')).toBeInTheDocument();
		expect(empty.querySelector('[data-slot="span"]')).toBeNull();
		const single = document.querySelector('[data-tag-id="3"]') as HTMLElement;
		expect(within(single).getByText('1 entry')).toBeInTheDocument();
		expect(within(single).getByText(formatDate('2026-05-01'))).toBeInTheDocument();
	});

	it('hands the loaded list to the shared lookups', async () => {
		await setup();

		expect([...lookupsStore.lookups.tags.keys()]).toEqual([1, 2, 3]);
	});

	it('explains the next step and offers Add tag when empty', async () => {
		await setup([]);

		expect(screen.getByText('No tags yet')).toBeInTheDocument();
		expect(
			screen.getByText(
				'Tags mark entries across categories, for example a holiday: add one here or from the ledger.'
			)
		).toBeInTheDocument();
		const empty = document.querySelector('[data-slot="empty"]') as HTMLElement;
		expect(within(empty).getByRole('button', { name: 'Add tag' })).toBeEnabled();
	});

	it('shows Rename inline and only Delete… in the menu', async () => {
		await setup();

		const row = document.querySelector('[data-tag-id="1"]') as HTMLElement;
		expect(
			within(row)
				.getAllByRole('button')
				.map((b) => b.getAttribute('aria-label'))
				.filter((label) => label !== null && !/^Change colour/.test(label))
		).toEqual(['Rename Holiday', 'More actions for Holiday']);
		await fireEvent.keyDown(screen.getByRole('button', { name: 'More actions for Holiday' }), {
			key: 'Enter'
		});
		const menu = await screen.findByRole('menu');
		expect(
			within(menu)
				.getAllByRole('menuitem')
				.map((i) => i.textContent?.trim())
		).toEqual(['Delete…']);
	});
});

describe('TagManager: add', () => {
	it('adds a tag with an optional colour in a form dialog, then reveals its row', async () => {
		vi.mocked(createTag).mockResolvedValue(
			written(holiday) as Awaited<ReturnType<typeof createTag>>
		);
		await setup([]);
		vi.mocked(listTags).mockResolvedValue([holiday]);

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add tag' });
		expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
		await fireEvent.input(within(dialog).getByLabelText('Name'), {
			target: { value: 'Holiday' }
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'plum' }));
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() => expect(createTag).toHaveBeenCalledWith('Holiday', 'plum'));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		const row = document.querySelector('[data-tag-id="1"]') as HTMLElement;
		expect(row).toHaveAttribute('data-revealed');
		expect([...lookupsStore.lookups.tags.keys()]).toEqual([1]);
		await waitFor(() => expect(row.firstElementChild).toHaveFocus());
	});

	it('sends no colour when None stays chosen', async () => {
		vi.mocked(createTag).mockResolvedValue(
			written(unused) as Awaited<ReturnType<typeof createTag>>
		);
		await setup([]);

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add tag' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Unused' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() => expect(createTag).toHaveBeenCalledWith('Unused', null));
	});

	it('says a taken name under the name field and keeps the dialog open', async () => {
		vi.mocked(createTag).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);
		await setup();

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add tag' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), {
			target: { value: 'Holiday' }
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByRole('alert')).toHaveTextContent(
			'A tag named "Holiday" already exists.'
		);
		expect(screen.getByRole('dialog', { name: 'Add tag' })).toBeInTheDocument();
	});

	it('cancels with Esc without writing', async () => {
		await setup();

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add tag' });
		await fireEvent.keyDown(within(dialog).getByLabelText('Name'), { key: 'Escape' });

		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(createTag).not.toHaveBeenCalled();
	});
});

describe('TagManager: rename and colour', () => {
	it('renames in place with Enter and sends only the name', async () => {
		vi.mocked(updateTag).mockResolvedValue(
			written({ ...holiday, name: 'Trip' }) as Awaited<ReturnType<typeof updateTag>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Holiday' }));
		const input = screen.getByLabelText('Name of Holiday');
		await fireEvent.input(input, { target: { value: 'Trip' } });
		await fireEvent.keyDown(input, { key: 'Enter' });

		await waitFor(() => expect(updateTag).toHaveBeenCalledWith(1, { name: 'Trip' }));
		expect(listTags).toHaveBeenCalledTimes(2);
		await waitFor(() => expect(screen.queryByLabelText('Name of Holiday')).toBeNull());
	});

	it('commits a changed name on blur and drops an unchanged one', async () => {
		vi.mocked(updateTag).mockResolvedValue(
			written({ ...holiday, name: 'Trip' }) as Awaited<ReturnType<typeof updateTag>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Holiday' }));
		await fireEvent.blur(screen.getByLabelText('Name of Holiday'));
		expect(screen.queryByLabelText('Name of Holiday')).toBeNull();
		expect(updateTag).not.toHaveBeenCalled();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Holiday' }));
		const input = screen.getByLabelText('Name of Holiday');
		await fireEvent.input(input, { target: { value: 'Trip' } });
		await fireEvent.blur(input);

		await waitFor(() => expect(updateTag).toHaveBeenCalledWith(1, { name: 'Trip' }));
	});

	it('cancels with Esc', async () => {
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Holiday' }));
		const input = screen.getByLabelText('Name of Holiday');
		await fireEvent.input(input, { target: { value: 'Trip' } });
		await fireEvent.keyDown(input, { key: 'Escape' });

		expect(screen.queryByLabelText('Name of Holiday')).toBeNull();
		expect(updateTag).not.toHaveBeenCalled();
	});

	it('keeps the edit open and shows a taken name beside the field', async () => {
		vi.mocked(updateTag).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Holiday' }));
		const input = screen.getByLabelText('Name of Holiday');
		await fireEvent.input(input, { target: { value: 'Gift' } });
		await fireEvent.keyDown(input, { key: 'Enter' });

		expect(await screen.findByRole('alert')).toHaveTextContent(
			'A tag named "Gift" already exists.'
		);
		expect(screen.getByLabelText('Name of Holiday')).toBeInTheDocument();
	});

	it('changes the colour from the fixed set and can clear it with None', async () => {
		vi.mocked(updateTag).mockResolvedValue(
			written(holiday) as Awaited<ReturnType<typeof updateTag>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Change colour of Holiday' }));
		const colour = await screen.findByRole('group', { name: 'Colour' });
		expect(screen.queryByRole('group', { name: 'Icon' })).toBeNull();
		await fireEvent.click(within(colour).getByRole('button', { name: 'teal' }));
		await waitFor(() => expect(updateTag).toHaveBeenCalledWith(1, { color: 'teal' }));

		await fireEvent.click(within(colour).getByRole('button', { name: 'None' }));
		await waitFor(() => expect(updateTag).toHaveBeenLastCalledWith(1, { color: null }));
	});
});

describe('TagManager: delete', () => {
	it('names how many entries lose the tag and deletes on an explicit Delete', async () => {
		vi.mocked(deleteTag).mockResolvedValue({
			removed_memberships: 12,
			settle: { error: null, touched_entry_ids: [] }
		} as Awaited<ReturnType<typeof deleteTag>>);
		await setup();

		await chooseFromMenu('Holiday', 'Delete…');

		const dialog = await screen.findByRole('dialog', { name: 'Delete tag “Holiday”' });
		expect(within(dialog).getByText(/12 entries will lose the tag/)).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
		expect(deleteTag).not.toHaveBeenCalled();
		vi.mocked(listTags).mockResolvedValue([unused, one]);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

		await waitFor(() => expect(deleteTag).toHaveBeenCalledWith(1));
		expect(await screen.findByText('Deleted tag “Holiday” (12 entries).')).toBeInTheDocument();
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(document.querySelector('[data-tag-id="1"]')).toBeNull();
		expect([...lookupsStore.lookups.tags.keys()]).toEqual([2, 3]);
	});

	it('says so when no entry carries the tag', async () => {
		await setup();

		await chooseFromMenu('Unused', 'Delete…');

		const dialog = await screen.findByRole('dialog', { name: 'Delete tag “Unused”' });
		expect(within(dialog).getByText(/No entry carries/)).toBeInTheDocument();
	});

	it('cancels without deleting', async () => {
		await setup();

		await chooseFromMenu('Holiday', 'Delete…');
		const dialog = await screen.findByRole('dialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(deleteTag).not.toHaveBeenCalled();
	});

	it('reloads the list and says so when the tag is already gone', async () => {
		vi.mocked(deleteTag).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		await setup();

		await chooseFromMenu('Holiday', 'Delete…');
		const dialog = await screen.findByRole('dialog');
		vi.mocked(listTags).mockResolvedValue([unused, one]);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

		expect(
			await screen.findByText('This tag no longer exists. The list was reloaded.')
		).toBeInTheDocument();
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(document.querySelector('[data-tag-id="1"]')).toBeNull();
	});
});
