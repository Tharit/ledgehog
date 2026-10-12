import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { emptyForm, type RuleForm } from '#lib/rules/form.js';
import { suggestionsFromEntry } from '#lib/rules/prefill.js';
import RuleFormView from './rule-form.svelte';

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Cash', kind: 'cash' })],
	categories: [category({ id: 10, name: 'Groceries' }), category({ id: 11, name: 'Rent' })],
	payees: [payee({ id: 20, name: 'REWE' })]
});

function form(over: Partial<RuleForm> = {}): RuleForm {
	return { ...emptyForm(), name: 'Rent', target: 11, name_prefix: 'Landlord', ...over };
}

function setup(props: Record<string, unknown> = {}) {
	const onedit = vi.fn();
	const onsave = vi.fn();
	render(RuleFormView, {
		props: { form: form(), lookups, onedit, onsave, saveBlocked: null, ...props }
	});
	return { onedit, onsave };
}

const saveButton = () => screen.getByRole('button', { name: 'Save rule' });

describe('RuleForm: fields', () => {
	it('shows the name, what it sets, the target and the conditions', () => {
		setup();

		expect(screen.getByLabelText('Name')).toHaveValue('Rent');
		expect(screen.getByLabelText('Sets a')).toHaveValue('category');
		expect(screen.getByRole('button', { name: 'The category this rule sets' })).toHaveTextContent(
			'Rent'
		);
		expect(screen.getByLabelText('Counterparty name starts with')).toHaveValue('Landlord');
		expect(screen.getByLabelText('Counterparty reference')).toHaveValue('');
	});

	it('reports every edit and leaves the form to its owner', async () => {
		const { onedit } = setup();

		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Rent flat' } });
		await fireEvent.input(screen.getByLabelText('Booking text'), { target: { value: 'SEPA' } });

		expect(onedit).toHaveBeenNthCalledWith(1, { name: 'Rent flat' });
		expect(onedit).toHaveBeenNthCalledWith(2, { booking_text: 'SEPA' });
	});

	it('offers a payee condition on a category rule only', () => {
		const { unmount } = render(RuleFormView, {
			props: { form: form(), lookups, onedit: vi.fn(), onsave: vi.fn() }
		});
		expect(
			screen.getByRole('button', { name: 'Only entries with this payee' })
		).toBeInTheDocument();
		unmount();

		render(RuleFormView, {
			props: { form: form({ sets: 'payee' }), lookups, onedit: vi.fn(), onsave: vi.fn() }
		});
		expect(screen.queryByRole('button', { name: 'Only entries with this payee' })).toBeNull();
	});

	it('changes what it sets at once, with the preview to follow', async () => {
		const { onedit } = setup();

		await fireEvent.change(screen.getByLabelText('Sets a'), { target: { value: 'payee' } });

		expect(onedit).toHaveBeenCalledWith({ sets: 'payee' }, true);
	});

	it('fixes what it sets once the rule exists', () => {
		setup({ editing: true });

		expect(screen.getByLabelText('Sets a')).toBeDisabled();
		expect(screen.getByText(/Fixed once the rule exists/)).toBeInTheDocument();
	});

	it('keeps the priority under Advanced, open only when it is set', () => {
		const { unmount } = render(RuleFormView, {
			props: { form: form(), lookups, onedit: vi.fn(), onsave: vi.fn() }
		});
		expect(screen.getByText('Advanced').closest('details')).not.toHaveAttribute('open');
		unmount();

		render(RuleFormView, {
			props: { form: form({ priority: '20' }), lookups, onedit: vi.fn(), onsave: vi.fn() }
		});
		expect(screen.getByText('Advanced').closest('details')).toHaveAttribute('open');
		expect(screen.getByLabelText('Priority')).toHaveValue('20');
	});
});

describe('RuleForm: suggestions from an entry', () => {
	const suggestions = suggestionsFromEntry({
		id: 1,
		counterparty_name: 'PAYPAL *SEEED',
		category_id: null,
		mandate_ref: 'M-1'
	});

	it('are unchecked boxes next to the value, and fill nothing in', () => {
		setup({ form: form({ name_prefix: '' }), suggestions });

		const boxes = screen.getAllByRole('checkbox');
		expect(boxes).toHaveLength(3);
		for (const box of boxes) expect(box).not.toBeChecked();
		expect(screen.getByLabelText('Counterparty name starts with')).toHaveValue('');
		expect(screen.getAllByText('“PAYPAL *SEEED”')).toHaveLength(2);
	});

	it('put their value into the field when ticked, and take it out when unticked', async () => {
		const { onedit } = setup({ form: form({ name_prefix: '' }), suggestions });

		await fireEvent.click(screen.getAllByRole('checkbox')[1]);

		expect(onedit).toHaveBeenCalledWith({ name_prefix: 'PAYPAL *SEEED' }, true);
	});

	it('show as ticked while the field holds the value', async () => {
		const { onedit } = setup({ form: form({ name_prefix: 'PAYPAL *SEEED' }), suggestions });

		const box = screen.getAllByRole('checkbox')[1];
		expect(box).toBeChecked();
		await fireEvent.click(box);

		expect(onedit).toHaveBeenCalledWith({ name_prefix: '' }, true);
	});
});

describe('RuleForm: errors', () => {
	it('shows the server’s regex error at the regex field', () => {
		setup({ errors: { purpose_regex: 'unterminated group' } });

		const input = screen.getByLabelText('Purpose matches (regular expression)');
		expect(input).toHaveAttribute('aria-invalid', 'true');
		expect(screen.getByText('unterminated group')).toBeInTheDocument();
		expect(input.getAttribute('aria-describedby')).toBe('rule-purpose_regex-error');
	});

	it('shows a taken name at the name', () => {
		setup({ errors: { name: 'A rule with this name already exists.' } });

		expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
		expect(screen.getByText('A rule with this name already exists.')).toBeInTheDocument();
	});

	it('opens Advanced for a priority the server refused', () => {
		setup({ errors: { priority: 'not a number' } });

		expect(screen.getByText('Advanced').closest('details')).toHaveAttribute('open');
	});
});

describe('RuleForm: saving', () => {
	it('is disabled, with the reason as its tooltip, until the rule can be saved', () => {
		setup({ saveBlocked: 'Waiting for the preview of this version of the rule' });

		expect(saveButton()).toBeDisabled();
		expect(saveButton().closest('span')).toHaveAttribute(
			'title',
			'Waiting for the preview of this version of the rule'
		);
	});

	it('saves with the button', async () => {
		const { onsave } = setup();

		await fireEvent.click(saveButton());

		expect(onsave).toHaveBeenCalledOnce();
	});

	it('saves with ⌘/Ctrl + Enter, but only when it can be saved', async () => {
		const { onsave } = setup();
		const name = screen.getByLabelText('Name');

		await fireEvent.keyDown(name, { key: 'Enter', ctrlKey: true });
		await fireEvent.keyDown(name, { key: 'Enter', metaKey: true });
		await fireEvent.keyDown(name, { key: 'Enter' });

		expect(onsave).toHaveBeenCalledTimes(2);
	});

	it('does not save with the keys while it is blocked', async () => {
		const { onsave } = setup({ saveBlocked: 'Give the rule a name' });

		await fireEvent.keyDown(screen.getByLabelText('Name'), { key: 'Enter', ctrlKey: true });

		expect(onsave).not.toHaveBeenCalled();
	});

	it('offers delete only for a stored rule', async () => {
		const ondelete = vi.fn();
		setup({ editing: true, ondelete });

		await fireEvent.click(screen.getByRole('button', { name: 'Delete rule…' }));

		expect(ondelete).toHaveBeenCalledOnce();
	});

	it('has no delete for a new rule', () => {
		setup();

		expect(screen.queryByRole('button', { name: 'Delete rule…' })).toBeNull();
	});

	it('cancels to the list', () => {
		setup();

		expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/settings/rules');
	});
});
