import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
/* eslint-disable no-restricted-imports -- the test stubs the API at its boundary */
import {
	ApiError,
	deleteCategory,
	listCategories,
	mergeCategory,
	updateCategory,
	createCategory
} from '#lib/api/index.js';
/* eslint-enable no-restricted-imports */
import { CategoriesStore } from '#lib/categories/store.svelte.js';
import { category } from '#lib/ledger/fixtures.js';
import type { Category, CategoryDeleteOut, CategoryMergeOut } from '#lib/types/domain.js';
import CategoryManager from './category-manager.svelte';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listCategories: vi.fn(),
	createCategory: vi.fn(),
	updateCategory: vi.fn(),
	deleteCategory: vi.fn(),
	mergeCategory: vi.fn()
}));

const food = category({ id: 1, name: 'Food', icon: 'utensils', color: 'sage', sort_order: 1 });
const groceries = category({
	id: 2,
	name: 'Groceries',
	parent_id: 1,
	icon: null,
	color: null,
	sort_order: 0
});
const fruit = category({ id: 3, name: 'Fruit', parent_id: 2, icon: null, color: null });
const travel = category({ id: 4, name: 'Travel', icon: 'plane', color: 'slate', sort_order: 0 });
const salary = category({ id: 5, name: 'Salary', kind: 'income', icon: 'banknote', color: 'teal' });
const tree = [food, groceries, fruit, travel, salary];

async function setup(categories: Category[] = tree) {
	vi.mocked(listCategories).mockResolvedValue(categories);
	const store = new CategoriesStore();
	render(CategoryManager, { props: { store } });
	await waitFor(() => expect(store.status).toBe('ready'));
	return store;
}

const write = (category: Category) => ({
	category,
	settle: { error: null, touched_entry_ids: [] }
});

beforeEach(() => {
	vi.resetAllMocks();
});

const headerAdd = () =>
	within(document.querySelector('[data-slot="page-header"]') as HTMLElement).getByRole('button', {
		name: 'Add category'
	});

/** open the ⋯ menu of a row (by keyboard: the menu opens on Enter) and return it */
async function openMenu(name: string) {
	await fireEvent.keyDown(screen.getByRole('button', { name: `More actions for ${name}` }), {
		key: 'Enter'
	});
	return screen.findByRole('menu');
}

async function chooseFromMenu(name: string, item: string) {
	const menu = await openMenu(name);
	await fireEvent.click(within(menu).getByRole('menuitem', { name: item }));
}

describe('CategoryManager: the tree', () => {
	it('shows Income and Expense as headings, with the categories below as indented rows', async () => {
		await setup();

		expect(screen.getByRole('heading', { name: 'Expense' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Income' })).toBeInTheDocument();
		const expense = screen.getByRole('list', { name: 'Expense categories' });
		const rows = within(expense).getAllByRole('listitem');
		expect(rows.map((r) => r.getAttribute('data-category-id'))).toEqual(['4', '1', '2', '3']);
		const income = screen.getByRole('list', { name: 'Income categories' });
		expect(within(income).getAllByRole('listitem')).toHaveLength(1);
	});

	it('says where an unset icon and colour come from', async () => {
		await setup();

		const row = document.querySelector('[data-category-id="2"]') as HTMLElement;
		expect(within(row).getByText('icon and colour inherited from Food')).toBeInTheDocument();
		const own = document.querySelector('[data-category-id="1"]') as HTMLElement;
		expect(own.querySelector('[data-slot="look-hint"]')).toBeNull();
	});

	it('folds the subcategories away', async () => {
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Collapse Food' }));

		expect(document.querySelector('[data-category-id="2"]')).toBeNull();
		expect(screen.getByRole('button', { name: 'Expand Food' })).toBeInTheDocument();
	});

	it('disables moving the first row up, in the menu', async () => {
		await setup();

		const menu = await openMenu('Travel');

		expect(within(menu).getByRole('menuitem', { name: 'Move up' })).toHaveAttribute(
			'aria-disabled',
			'true'
		);
		expect(within(menu).getByRole('menuitem', { name: 'Move down' })).not.toHaveAttribute(
			'aria-disabled',
			'true'
		);
	});

	it('disables moving the last row down, in the menu', async () => {
		await setup();

		const menu = await openMenu('Food');

		expect(within(menu).getByRole('menuitem', { name: 'Move down' })).toHaveAttribute(
			'aria-disabled',
			'true'
		);
	});

	it('shows Rename and Add subcategory inline and the rest in the menu, Delete last', async () => {
		await setup();

		const row = document.querySelector('[data-category-id="4"]') as HTMLElement;
		expect(
			within(row)
				.getAllByRole('button')
				.map((b) => b.getAttribute('aria-label'))
				.filter((label) => label !== null && !/^Change icon/.test(label))
		).toEqual(['Rename Travel', 'Add subcategory to Travel', 'More actions for Travel']);
		const menu = await openMenu('Travel');
		expect(
			within(menu)
				.getAllByRole('menuitem')
				.map((i) => i.textContent?.trim())
		).toEqual(['Move up', 'Move down', 'Move to…', 'Merge…', 'Delete…']);
	});
});

describe('CategoryManager: empty', () => {
	it('explains the next step and offers Add category, with no starter tree', async () => {
		await setup([]);

		const empty = document.querySelector('[data-slot="empty"]') as HTMLElement;
		expect(within(empty).getByText('No categories yet')).toBeInTheDocument();
		expect(within(empty).getByRole('button', { name: 'Add category' })).toBeEnabled();
		expect(headerAdd()).toBeEnabled();
		expect(document.querySelectorAll('[data-slot="category-row"]')).toHaveLength(0);
	});
});

describe('CategoryManager: add', () => {
	it('adds a top-level category of the chosen kind in a form dialog, then reveals its row', async () => {
		vi.mocked(createCategory).mockResolvedValue(
			write(food) as Awaited<ReturnType<typeof createCategory>>
		);
		await setup([]);
		vi.mocked(listCategories).mockResolvedValue([food]);

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add category' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Food' } });
		await fireEvent.click(within(dialog).getByRole('radio', { name: 'Income' }));
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() =>
			expect(createCategory).toHaveBeenCalledWith({ name: 'Food', kind: 'income', sort_order: 0 })
		);
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		const row = document.querySelector('[data-category-id="1"]') as HTMLElement;
		expect(row).toHaveAttribute('data-revealed');
		await waitFor(() => expect(row.firstElementChild).toHaveFocus());
	});

	it('has no inline form: the name field lives in the dialog and Add needs a name', async () => {
		await setup();

		await fireEvent.click(headerAdd());

		const dialog = await screen.findByRole('dialog', { name: 'Add category' });
		expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
		expect(within(dialog).getByText(/The kind cannot be changed later/)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Create' })).toBeNull();
	});

	it('adds a subcategory under its parent from the row, titled with the parent', async () => {
		vi.mocked(createCategory).mockResolvedValue(
			write(fruit) as Awaited<ReturnType<typeof createCategory>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Add subcategory to Food' }));
		const dialog = await screen.findByRole('dialog', { name: 'Add subcategory to Food' });
		expect(within(dialog).queryByRole('radio')).toBeNull();
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Snacks' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		await waitFor(() =>
			expect(createCategory).toHaveBeenCalledWith({ name: 'Snacks', parent_id: 1, sort_order: 1 })
		);
	});

	it('shows a taken name under the name field and keeps the dialog open', async () => {
		vi.mocked(createCategory).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);
		await setup();

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add category' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Food' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByRole('alert')).toHaveTextContent(
			'A category named "Food" already exists at this level.'
		);
		expect(within(dialog).getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
	});

	it('shows any other refusal in the dialog', async () => {
		vi.mocked(createCategory).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		await setup();

		await fireEvent.click(headerAdd());
		const dialog = await screen.findByRole('dialog', { name: 'Add category' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Food' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

		expect(await within(dialog).findByRole('alert')).toHaveTextContent('could not be reached');
		expect(within(dialog).getByLabelText('Name')).not.toHaveAttribute('aria-invalid', 'true');
	});

	it('cancels without writing, and starts empty the next time', async () => {
		await setup();

		await fireEvent.click(headerAdd());
		let dialog = await screen.findByRole('dialog', { name: 'Add category' });
		await fireEvent.input(within(dialog).getByLabelText('Name'), { target: { value: 'Food' } });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(createCategory).not.toHaveBeenCalled();

		await fireEvent.click(headerAdd());
		dialog = await screen.findByRole('dialog', { name: 'Add category' });
		expect(within(dialog).getByLabelText('Name')).toHaveValue('');
	});
});

describe('CategoryManager: rename, order, look', () => {
	it('renames in place and sends only the name', async () => {
		vi.mocked(updateCategory).mockResolvedValue(
			write({ ...food, name: 'Eating' }) as Awaited<ReturnType<typeof updateCategory>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		const input = screen.getByLabelText('Name of Food');
		await fireEvent.input(input, { target: { value: 'Eating' } });
		await fireEvent.keyDown(input, { key: 'Enter' });

		await waitFor(() => expect(updateCategory).toHaveBeenCalledWith(1, { name: 'Eating' }));
		expect(listCategories).toHaveBeenCalledTimes(2);
	});

	it('commits a changed name on blur and drops an unchanged one', async () => {
		vi.mocked(updateCategory).mockResolvedValue(
			write({ ...food, name: 'Eating' }) as Awaited<ReturnType<typeof updateCategory>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		await fireEvent.blur(screen.getByLabelText('Name of Food'));
		expect(screen.queryByLabelText('Name of Food')).toBeNull();
		expect(updateCategory).not.toHaveBeenCalled();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		const input = screen.getByLabelText('Name of Food');
		await fireEvent.input(input, { target: { value: 'Eating' } });
		await fireEvent.blur(input);

		await waitFor(() => expect(updateCategory).toHaveBeenCalledWith(1, { name: 'Eating' }));
	});

	it('cancels a rename with Esc', async () => {
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		const input = screen.getByLabelText('Name of Food');
		await fireEvent.input(input, { target: { value: 'Eating' } });
		await fireEvent.keyDown(input, { key: 'Escape' });

		expect(screen.queryByLabelText('Name of Food')).toBeNull();
		expect(updateCategory).not.toHaveBeenCalled();
	});

	it('shows a taken name beside the field and reloads the list', async () => {
		vi.mocked(updateCategory).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		const input = screen.getByLabelText('Name of Food');
		await fireEvent.input(input, { target: { value: 'Travel' } });
		await fireEvent.keyDown(input, { key: 'Enter' });

		expect(await screen.findByRole('alert')).toHaveTextContent(
			'A category named "Travel" already exists'
		);
		expect(screen.getByLabelText('Name of Food')).toBeInTheDocument();
	});

	it('moves down by numbering the siblings, as the server stores sort_order', async () => {
		vi.mocked(updateCategory).mockImplementation(
			async () => write(food) as Awaited<ReturnType<typeof updateCategory>>
		);
		await setup();

		// Travel (0) is above Food (1): moving it down numbers Food 0 and Travel 1
		await chooseFromMenu('Travel', 'Move down');

		await waitFor(() => expect(updateCategory).toHaveBeenCalled());
		const calls = vi.mocked(updateCategory).mock.calls.map(([id, body]) => [id, body]);
		expect(calls).toContainEqual([4, { sort_order: 1 }]);
	});

	it('changes the icon from the fixed set and sends only the icon', async () => {
		vi.mocked(updateCategory).mockResolvedValue(
			write({ ...groceries, icon: 'car' }) as Awaited<ReturnType<typeof updateCategory>>
		);
		await setup();

		await fireEvent.click(
			screen.getByRole('button', { name: 'Change icon and colour of Groceries' })
		);
		await fireEvent.click(await screen.findByRole('button', { name: 'car' }));

		await waitFor(() => expect(updateCategory).toHaveBeenCalledWith(2, { icon: 'car' }));
	});

	it('clears the colour with Inherit', async () => {
		vi.mocked(updateCategory).mockResolvedValue(
			write({ ...food, color: null }) as Awaited<ReturnType<typeof updateCategory>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Change icon and colour of Food' }));
		const colour = await screen.findByRole('group', { name: 'Colour' });
		await fireEvent.click(within(colour).getByRole('button', { name: 'Inherit' }));

		await waitFor(() => expect(updateCategory).toHaveBeenCalledWith(1, { color: null }));
	});
});

describe('CategoryManager: move to', () => {
	it('disables the category itself, its descendants and its current parent', async () => {
		await setup();

		await chooseFromMenu('Groceries', 'Move to…');

		const dialog = await screen.findByRole('dialog');
		const option = (label: string) =>
			within(dialog)
				.getAllByRole('option')
				.find((o) => o.querySelector('span.truncate')?.textContent === label)!;
		expect(option('Food › Groceries')).toHaveAttribute('aria-disabled', 'true');
		expect(option('Food › Groceries › Fruit')).toHaveAttribute('aria-disabled', 'true');
		expect(option('Food')).toHaveAttribute('aria-disabled', 'true');
		expect(option('Travel')).not.toHaveAttribute('aria-disabled', 'true');
		expect(within(dialog).queryByRole('option', { name: /Salary/ })).toBeNull();
	});

	it('sends the new parent and shows a cycle refusal from the server', async () => {
		vi.mocked(updateCategory).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'cycle' })
		);
		await setup();

		await chooseFromMenu('Groceries', 'Move to…');
		const dialog = await screen.findByRole('dialog');
		await fireEvent.click(within(dialog).getByRole('option', { name: /^Travel$/ }));

		await waitFor(() =>
			expect(updateCategory).toHaveBeenCalledWith(2, { parent_id: 4, sort_order: 0 })
		);
		expect(await within(dialog).findByRole('alert')).toHaveTextContent(
			'cannot be moved under itself'
		);
	});
});

const deleteOut = (over: Partial<CategoryDeleteOut> = {}): CategoryDeleteOut => ({
	dry_run: true,
	category: travel,
	deletable: true,
	held: { entries: 0, rules: 0, children: 0 },
	deleted: false,
	settle: null,
	...over
});

describe('CategoryManager: delete', () => {
	it('asks the server first and confirms explicitly when it is deletable', async () => {
		vi.mocked(deleteCategory).mockImplementation(async (_id, options) =>
			options?.dryRun ? deleteOut() : deleteOut({ dry_run: false, deleted: true })
		);
		await setup();

		await chooseFromMenu('Travel', 'Delete…');

		const dialog = await screen.findByRole('dialog');
		await within(dialog).findByText(/Nothing uses Travel/);
		expect(deleteCategory).toHaveBeenCalledWith(4, { dryRun: true });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

		await waitFor(() => expect(deleteCategory).toHaveBeenCalledWith(4));
		expect(await screen.findByText('Deleted Travel.')).toBeInTheDocument();
	});

	it('refuses with the held counts and offers Merge instead', async () => {
		vi.mocked(deleteCategory).mockResolvedValue(
			deleteOut({ deletable: false, held: { entries: 12, rules: 1, children: 0 } })
		);
		vi.mocked(mergeCategory).mockResolvedValue(mergeOut());
		await setup();

		await chooseFromMenu('Travel', 'Delete…');

		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText(/it holds 12 entries, 1 rule/)).toBeInTheDocument();
		expect(within(dialog).queryByRole('button', { name: 'Delete' })).toBeNull();
		expect(deleteCategory).toHaveBeenCalledTimes(1);

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Merge instead…' }));
		expect(await screen.findByText('Merge Travel into…')).toBeInTheDocument();
	});
});

function mergeOut(over: Partial<CategoryMergeOut> = {}): CategoryMergeOut {
	return {
		dry_run: true,
		source_id: 2,
		target_id: 4,
		pairs: [
			{
				source_id: 3,
				source_name: 'Fruit',
				target_id: 9,
				target_name: 'Fruit',
				entries: 2,
				rules: 0
			},
			{
				source_id: 2,
				source_name: 'Groceries',
				target_id: 4,
				target_name: 'Travel',
				entries: 10,
				rules: 1
			}
		],
		moved_children: [{ id: 7, name: 'Snacks', from_id: 2, to_id: 4 }],
		entry_count: 12,
		entry_ids: [],
		rule_ids: [11],
		settle: null,
		...over
	};
}

async function openMergeInto(target: RegExp) {
	await chooseFromMenu('Groceries', 'Merge…');
	const dialog = await screen.findByRole('dialog');
	await fireEvent.click(within(dialog).getByRole('option', { name: target }));
	return dialog;
}

describe('CategoryManager: merge', () => {
	it('lists what the dry run says and offers an explicit Merge', async () => {
		vi.mocked(mergeCategory).mockResolvedValue(mergeOut());
		await setup();

		const dialog = await openMergeInto(/^Travel$/);

		expect(await within(dialog).findByText('Merges 2 categories')).toBeInTheDocument();
		expect(within(dialog).getByText('Fruit into Fruit (2 entries, 0 rules)')).toBeInTheDocument();
		expect(within(dialog).getByText('Snacks moves under Travel')).toBeInTheDocument();
		expect(within(dialog).getByText('Repoints 12 entries and 1 rule.')).toBeInTheDocument();
		expect(within(dialog).getByText('Nothing returns to review.')).toBeInTheDocument();
		expect(within(dialog).getByText('Travel keeps its own icon and colour.')).toBeInTheDocument();
		expect(mergeCategory).toHaveBeenCalledTimes(1);
		expect(mergeCategory).toHaveBeenCalledWith(2, 4, { dryRun: true });
	});

	it('does not offer the source or its descendants as a target', async () => {
		vi.mocked(mergeCategory).mockResolvedValue(mergeOut());
		await setup();

		await chooseFromMenu('Groceries', 'Merge…');

		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).queryByRole('option', { name: /Groceries/ })).toBeNull();
		expect(within(dialog).queryByRole('option', { name: /Fruit/ })).toBeNull();
		expect(within(dialog).getByRole('option', { name: /^Food$/ })).toBeInTheDocument();
		expect(within(dialog).queryByRole('option', { name: /Salary/ })).toBeNull();
	});

	it('merges with the previewed count and says what was merged', async () => {
		vi.mocked(mergeCategory).mockImplementation(async (_id, _into, options) =>
			options?.dryRun ? mergeOut() : mergeOut({ dry_run: false })
		);
		await setup();
		const dialog = await openMergeInto(/^Travel$/);
		await within(dialog).findByText('Merges 2 categories');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Merge' }));

		await waitFor(() => expect(mergeCategory).toHaveBeenCalledWith(2, 4, { expectedCount: 12 }));
		expect(
			await screen.findByText('Merged Groceries into Travel (12 entries, 1 rule).')
		).toBeInTheDocument();
		expect(screen.queryByRole('dialog')).toBeNull();
		expect(listCategories).toHaveBeenCalledTimes(2);
	});

	it('cannot merge before there is a preview', async () => {
		vi.mocked(mergeCategory).mockResolvedValue(mergeOut());
		await setup();

		await chooseFromMenu('Groceries', 'Merge…');

		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).getByRole('button', { name: 'Merge' })).toBeDisabled();
	});

	it('re-runs the preview and says so when the count moved', async () => {
		let previews = 0;
		vi.mocked(mergeCategory).mockImplementation(async (_id, _into, options) => {
			if (options?.dryRun) return mergeOut({ entry_count: previews++ === 0 ? 12 : 13 });
			throw new ApiError(409, 'conflict', 'x', {
				reason: 'filter_result_changed',
				expected: 12,
				actual: 13
			});
		});
		await setup();
		const dialog = await openMergeInto(/^Travel$/);
		await within(dialog).findByText('Repoints 12 entries and 1 rule.');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Merge' }));

		expect(
			await within(dialog).findByText(/it now repoints 13 entries \(was 12\)/)
		).toBeInTheDocument();
		expect(within(dialog).getByText('Repoints 13 entries and 1 rule.')).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Merge' })).toBeEnabled();
	});

	it('shows a refusal into a descendant and keeps the dialog open', async () => {
		vi.mocked(mergeCategory).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'into_descendant' })
		);
		await setup();

		const dialog = await openMergeInto(/^Travel$/);

		expect(await within(dialog).findByRole('alert')).toHaveTextContent(
			'into one of its own subcategories'
		);
		expect(within(dialog).getByRole('button', { name: 'Merge' })).toBeDisabled();
	});

	it('reloads the list and asks again when the target vanished (stale_reference)', async () => {
		vi.mocked(mergeCategory).mockRejectedValue(
			new ApiError(409, 'stale_reference', 'x', { field: 'into', entity: 'category', id: 4 })
		);
		await setup();

		const dialog = await openMergeInto(/^Travel$/);

		expect(await within(dialog).findByRole('alert')).toHaveTextContent(
			'The merge target no longer exists'
		);
		await waitFor(() => expect(listCategories).toHaveBeenCalledTimes(2));
	});
});
