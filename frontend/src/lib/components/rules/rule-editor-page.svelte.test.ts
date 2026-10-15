import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry } from '#lib/ledger/fixtures.js';
import { preview, previewList, previewRow, rule, source } from '#lib/rules/fixtures.js';
import RuleEditorPage from './rule-editor-page.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	createRule: vi.fn(),
	updateRule: vi.fn(),
	getRule: vi.fn(),
	listRules: vi.fn(),
	getEntry: vi.fn(),
	listEntries: vi.fn(),
	listAccounts: vi.fn(),
	listCategories: vi.fn(),
	listPayees: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

type Navigation = { cancel: () => void; to: { url: URL } | null; willUnload: boolean };
const nav = vi.hoisted(() => ({
	callback: null as null | ((n: Navigation) => void),
	goto: vi.fn()
}));
vi.mock('$app/navigation', () => ({
	beforeNavigate: (callback: (n: Navigation) => void) => {
		nav.callback = callback;
	},
	goto: nav.goto
}));

function navigate() {
	const cancel = vi.fn();
	nav.callback!({
		cancel,
		to: { url: new URL('http://localhost/settings/rules') },
		willUnload: false
	});
	return cancel;
}

const example = entry({
	id: 42,
	booked_on: '2026-10-09',
	source: source({ counterparty_name: 'REWE Markt', purpose: 'Einkauf', booking_text: 'KARTE' })
});

const out = (p = preview({ matches: previewList([previewRow()], 1) }), over = {}) => ({
	dry_run: true,
	rule: null,
	preview: p,
	settle: null,
	settle_breakdown: null,
	...over
});

async function settle() {
	await vi.advanceTimersByTimeAsync(500);
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
	nav.callback = null;
	vi.mocked(api.listAccounts).mockResolvedValue([account({ id: 1, name: 'Giro' })]);
	vi.mocked(api.listCategories).mockResolvedValue([category({ id: 10, name: 'Groceries' })]);
	vi.mocked(api.listPayees).mockResolvedValue([]);
	vi.mocked(api.listRules).mockResolvedValue([]);
});

afterEach(() => {
	vi.useRealTimers();
});

describe('the rule editor page: adding', () => {
	it('is titled "Add rule" and starts with one empty condition row and an example find box', async () => {
		render(RuleEditorPage, { props: { onleave: vi.fn() } });
		await settle();

		expect(screen.getByRole('heading', { name: 'Add rule' })).toBeInTheDocument();
		expect(screen.getByLabelText('Condition 1: value')).toHaveValue('');
		expect(screen.getAllByLabelText(/Condition \d+: value/)).toHaveLength(1);
		expect(screen.getByRole('combobox', { name: 'Find an entry' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save rule' })).toBeDisabled();
	});

	it('opens with the example it came with and fills in nothing from it', async () => {
		vi.mocked(api.getEntry).mockResolvedValue(example);
		render(RuleEditorPage, { props: { exampleId: 42, onleave: vi.fn() } });
		await settle();

		expect(api.getEntry).toHaveBeenCalledWith(42);
		expect(screen.getByRole('table', { name: 'The example entry' })).toHaveTextContent(
			'REWE Markt'
		);
		expect(screen.getByLabelText('Condition 1: value')).toHaveValue('');
		expect(screen.getByLabelText('Name')).toHaveValue('');
		expect(api.listRules).toHaveBeenCalled();
		expect(screen.getByText(/Choose what the rule sets and add a condition/)).toBeInTheDocument();
	});

	it('reports the example the user picks, for the address, and does not make the form dirty', async () => {
		vi.mocked(api.listEntries).mockResolvedValue({
			entries: [example],
			total: 1,
			limit: 8,
			offset: 0
		});
		const onexample = vi.fn();
		render(RuleEditorPage, { props: { onleave: vi.fn(), onexample } });
		await settle();

		const box = screen.getByRole('combobox', { name: 'Find an entry' });
		await fireEvent.input(box, { target: { value: 'rewe' } });
		await settle();
		await fireEvent.keyDown(box, { key: 'Enter' });

		expect(onexample).toHaveBeenCalledWith(42);
		expect(navigate()).not.toHaveBeenCalled();
	});

	it('asks before leaving a form with changes, not before leaving a clean one', async () => {
		render(RuleEditorPage, { props: { onleave: vi.fn() } });
		await settle();
		expect(navigate()).not.toHaveBeenCalled();

		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Rent' } });

		expect(navigate()).toHaveBeenCalledOnce();
		expect(await screen.findByText('Discard changes?')).toBeInTheDocument();
	});

	it('does not count a blank condition row or a changed example as a change', async () => {
		render(RuleEditorPage, { props: { onleave: vi.fn() } });
		await settle();

		await fireEvent.click(screen.getByRole('button', { name: 'Add condition' }));

		expect(screen.getAllByLabelText(/Condition \d+: value/)).toHaveLength(2);
		expect(navigate()).not.toHaveBeenCalled();
	});

	it('shows the Add rule and Cancel buttons as the proposal words them, with no icon on them', async () => {
		render(RuleEditorPage, { props: { onleave: vi.fn() } });
		await settle();

		const save = screen.getByRole('button', { name: 'Save rule' });
		const cancel = screen.getByRole('link', { name: 'Cancel' });
		expect(save.querySelector('svg')).toBeNull();
		expect(cancel.querySelector('svg')).toBeNull();
		expect(screen.getByRole('button', { name: 'Add condition' }).querySelector('svg')).toBeNull();
	});
});

describe('the rule editor page: changing a rule', () => {
	async function opened(onleave = vi.fn()) {
		vi.mocked(api.getRule).mockResolvedValue(rule({ id: 5, name: 'Landlord' }));
		vi.mocked(api.updateRule).mockResolvedValue(out());
		render(RuleEditorPage, { props: { ruleId: 5, onleave } });
		await settle();
		return onleave;
	}

	it('shows the stored conditions as rows and the preview with its headers', async () => {
		await opened();

		expect(screen.getByRole('heading', { name: 'Landlord' })).toBeInTheDocument();
		expect(screen.getByLabelText('Condition 1: field')).toHaveValue('counterparty_name');
		expect(screen.getByLabelText('Condition 1: operator')).toHaveValue('starts_with');
		expect(screen.getByLabelText('Condition 1: value')).toHaveValue('Landlord');
		const table = screen.getByRole('table', { name: 'Matched entries' });
		expect(within(table).getByRole('columnheader', { name: 'Currently' })).toBeInTheDocument();
		expect(screen.queryByRole('link', { name: /ledger/i })).toBeNull();
	});

	it('is not dirty as loaded, and asks once a condition changes', async () => {
		await opened();
		expect(navigate()).not.toHaveBeenCalled();

		await fireEvent.input(screen.getByLabelText('Condition 1: value'), {
			target: { value: 'Landlords' }
		});

		expect(navigate()).toHaveBeenCalledOnce();
	});

	it('saves with the previewed count, leaves, and is not stopped by its own guard', async () => {
		const onleave = await opened();
		await fireEvent.input(screen.getByLabelText('Condition 1: value'), {
			target: { value: 'Landlords' }
		});
		await settle();
		vi.mocked(api.updateRule).mockResolvedValue(
			out(preview(), { dry_run: false, rule: rule({ id: 5, name: 'Landlord' }) })
		);

		await fireEvent.click(screen.getByRole('button', { name: 'Save rule' }));
		await vi.advanceTimersByTimeAsync(0);

		expect(vi.mocked(api.updateRule).mock.calls.at(-1)![2]).toMatchObject({ expectedCount: 1 });
		expect(onleave).toHaveBeenCalledOnce();
		expect(String(onleave.mock.calls[0][0])).toContain('done=saved');
		expect(navigate()).not.toHaveBeenCalled();
	});
});
