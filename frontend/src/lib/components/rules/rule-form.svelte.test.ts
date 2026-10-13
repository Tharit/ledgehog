import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { newConditionRow } from '#lib/rules/conditions.js';
import { emptyForm, type RuleForm } from '#lib/rules/form.js';
import RuleFormView from './rule-form.svelte';

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Cash', kind: 'cash' })],
	categories: [category({ id: 10, name: 'Groceries' }), category({ id: 11, name: 'Rent' })],
	payees: [payee({ id: 20, name: 'REWE' })]
});

function form(over: Partial<RuleForm> = {}): RuleForm {
	return {
		...emptyForm(),
		name: 'Rent',
		target: 11,
		conditions: [
			newConditionRow({ field: 'counterparty_name', op: 'starts_with', value: 'Landlord' })
		],
		...over
	};
}

function setup(props: Record<string, unknown> = {}) {
	const handlers = {
		onedit: vi.fn(),
		oncondition: vi.fn(),
		onaddcondition: vi.fn(),
		onremovecondition: vi.fn(),
		onsave: vi.fn()
	};
	render(RuleFormView, {
		props: { form: form(), lookups, ...handlers, saveBlocked: null, ...props }
	});
	return handlers;
}

const saveButton = () => screen.getByRole('button', { name: 'Save rule' });

describe('RuleForm: fields', () => {
	it('shows the name, what it sets, the target and the conditions', () => {
		setup();

		expect(screen.getByLabelText('Name')).toHaveValue('Rent');
		expect(screen.getByLabelText('Sets')).toHaveValue('category');
		expect(screen.getByRole('button', { name: 'The category this rule sets' })).toHaveTextContent(
			'Rent'
		);
		expect(screen.getByLabelText('Condition 1: field')).toHaveValue('counterparty_name');
		expect(screen.getByLabelText('Condition 1: operator')).toHaveValue('starts_with');
		expect(screen.getByLabelText('Condition 1: value')).toHaveValue('Landlord');
	});

	it('has no placeholder in any text input', () => {
		setup();

		for (const input of screen.getAllByRole('textbox')) {
			expect(input).not.toHaveAttribute('placeholder');
		}
	});

	it('reports every edit and leaves the form to its owner', async () => {
		const { onedit } = setup();

		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Rent flat' } });

		expect(onedit).toHaveBeenCalledWith({ name: 'Rent flat' });
	});

	it('offers a payee condition on a category rule only', () => {
		const { unmount } = render(RuleFormView, {
			props: {
				form: form(),
				lookups,
				onedit: vi.fn(),
				oncondition: vi.fn(),
				onaddcondition: vi.fn(),
				onremovecondition: vi.fn(),
				onsave: vi.fn()
			}
		});
		expect(screen.getByText('Payee is')).toBeInTheDocument();
		unmount();

		render(RuleFormView, {
			props: {
				form: form({ sets: 'payee' }),
				lookups,
				onedit: vi.fn(),
				oncondition: vi.fn(),
				onaddcondition: vi.fn(),
				onremovecondition: vi.fn(),
				onsave: vi.fn()
			}
		});
		expect(screen.queryByText('Payee is')).toBeNull();
	});

	it('sets the payee condition at once, with the preview to follow', async () => {
		const { onedit } = setup({ form: form({ condition_payee_id: 20 }) });

		await fireEvent.click(screen.getByRole('button', { name: 'Clear the payee' }));

		expect(onedit).toHaveBeenCalledWith({ condition_payee_id: null }, true);
	});

	it('changes what it sets at once, with the preview to follow', async () => {
		const { onedit } = setup();

		await fireEvent.change(screen.getByLabelText('Sets'), { target: { value: 'payee' } });

		expect(onedit).toHaveBeenCalledWith({ sets: 'payee' }, true);
	});

	it('fixes what it sets once the rule exists', () => {
		setup({ editing: true });

		expect(screen.getByLabelText('Sets')).toBeDisabled();
		expect(screen.getByText(/Fixed once the rule exists/)).toBeInTheDocument();
	});

	it('keeps the priority under Advanced, open only when it is set', () => {
		const { unmount } = render(RuleFormView, {
			props: {
				form: form(),
				lookups,
				onedit: vi.fn(),
				oncondition: vi.fn(),
				onaddcondition: vi.fn(),
				onremovecondition: vi.fn(),
				onsave: vi.fn()
			}
		});
		expect(screen.getByText('Advanced').closest('details')).not.toHaveAttribute('open');
		unmount();

		render(RuleFormView, {
			props: {
				form: form({ priority: '20' }),
				lookups,
				onedit: vi.fn(),
				oncondition: vi.fn(),
				onaddcondition: vi.fn(),
				onremovecondition: vi.fn(),
				onsave: vi.fn()
			}
		});
		expect(screen.getByText('Advanced').closest('details')).toHaveAttribute('open');
		expect(screen.getByLabelText('Priority')).toHaveValue('20');
	});

	it('shows the example region above the conditions', () => {
		const example = createRawSnippet(() => ({ render: () => '<p>the example</p>' }));
		setup({ example });

		const text = screen.getByText('the example');
		const conditions = screen.getByRole('group', { name: /source transaction has/ });
		expect(
			text.compareDocumentPosition(conditions) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
	});
});

describe('RuleForm: the condition rows', () => {
	it('shows every row with its field, operator and value, and nothing prefilled', () => {
		setup({
			form: form({
				conditions: [
					newConditionRow({ field: 'purpose', op: 'contains', value: 'Markt' }),
					newConditionRow({ field: 'mandate_ref', op: 'equals', value: 'M1' })
				]
			})
		});

		expect(screen.getByLabelText('Condition 1: field')).toHaveValue('purpose');
		expect(screen.getByLabelText('Condition 2: field')).toHaveValue('mandate_ref');
		expect(screen.getByLabelText('Condition 2: operator')).toHaveValue('equals');
		expect(screen.getByLabelText('Condition 2: value')).toHaveValue('M1');
	});

	it('offers the plain field and operator labels', () => {
		setup();

		const fields = within(screen.getByLabelText('Condition 1: field'));
		expect(fields.getAllByRole('option').map((o) => o.textContent)).toEqual([
			'Counterparty name',
			'Counterparty IBAN or reference',
			'Purpose',
			'Booking text',
			'Mandate reference'
		]);
		const ops = within(screen.getByLabelText('Condition 1: operator'));
		expect(ops.getAllByRole('option').map((o) => o.textContent)).toEqual([
			'is',
			'starts with',
			'contains',
			'matches pattern (regex)'
		]);
	});

	it('reports a change of field, operator and value of one row', async () => {
		const { oncondition } = setup();

		await fireEvent.change(screen.getByLabelText('Condition 1: field'), {
			target: { value: 'purpose' }
		});
		await fireEvent.change(screen.getByLabelText('Condition 1: operator'), {
			target: { value: 'regex' }
		});
		await fireEvent.input(screen.getByLabelText('Condition 1: value'), {
			target: { value: 'a|b' }
		});

		expect(oncondition).toHaveBeenNthCalledWith(1, 0, { field: 'purpose' });
		expect(oncondition).toHaveBeenNthCalledWith(2, 0, { op: 'regex' });
		expect(oncondition).toHaveBeenNthCalledWith(3, 0, { value: 'a|b' });
	});

	it('adds a condition with a button and removes one with its own', async () => {
		const { onaddcondition, onremovecondition } = setup({
			form: form({ conditions: [newConditionRow({ value: 'A' }), newConditionRow({ value: 'B' })] })
		});

		await fireEvent.click(screen.getByRole('button', { name: 'Add condition' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Remove condition 2' }));

		expect(onaddcondition).toHaveBeenCalledOnce();
		expect(onremovecondition).toHaveBeenCalledWith(1);
	});

	it('says what the regex operator takes, for that row only', () => {
		setup({
			form: form({
				conditions: [
					newConditionRow({ op: 'contains', value: 'a' }),
					newConditionRow({ op: 'regex', value: 'b' })
				]
			})
		});

		const rows = screen.getAllByRole('listitem');
		expect(within(rows[0]).queryByText(/regular expression/)).toBeNull();
		expect(within(rows[1]).getByText(/regular expression/)).toBeInTheDocument();
	});

	it('shows the server’s word about a row at that row', () => {
		setup({
			form: form({
				conditions: [newConditionRow({ value: 'a' }), newConditionRow({ op: 'regex', value: '(' })]
			}),
			errors: { rows: { 1: 'The regex does not compile (at position 1)' } }
		});

		const rows = screen.getAllByRole('listitem');
		expect(
			within(rows[1]).getByText('The regex does not compile (at position 1)')
		).toBeInTheDocument();
		expect(screen.getByLabelText('Condition 2: value')).toHaveAttribute('aria-invalid', 'true');
		expect(screen.getByLabelText('Condition 1: value')).not.toHaveAttribute('aria-invalid');
		expect(
			screen.getByLabelText('Condition 2: value').getAttribute('aria-describedby')
		).toBeTruthy();
	});

	it('says rows without a value are left out, when there are such rows and others', () => {
		setup({ form: form({ conditions: [newConditionRow({ value: 'a' }), newConditionRow()] }) });

		expect(screen.getByText('Rows without a value are left out.')).toBeInTheDocument();
	});
});

describe('RuleForm: errors', () => {
	it('shows a taken name at the name', () => {
		setup({ errors: { name: 'A rule with this name already exists.' } });

		expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
		expect(screen.getByText('A rule with this name already exists.')).toBeInTheDocument();
	});

	it('shows a missing condition at the list', () => {
		setup({ errors: { conditions: 'a rule needs at least one condition' } });

		expect(screen.getByText('a rule needs at least one condition')).toBeInTheDocument();
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

	it('saves with ⌘/Ctrl + Enter, never with Enter alone', async () => {
		const { onsave } = setup();
		const name = screen.getByLabelText('Name');

		await fireEvent.keyDown(name, { key: 'Enter', ctrlKey: true });
		await fireEvent.keyDown(name, { key: 'Enter', metaKey: true });
		await fireEvent.keyDown(name, { key: 'Enter' });
		await fireEvent.keyDown(screen.getByLabelText('Condition 1: value'), { key: 'Enter' });

		expect(onsave).toHaveBeenCalledTimes(2);
	});

	it('does not submit the form when Enter is pressed in a field', async () => {
		setup();
		const form = screen.getByRole('form', { name: 'Rule' });
		const submitted = vi.fn((event: Event) => event.defaultPrevented);
		form.addEventListener('submit', submitted);

		await fireEvent.submit(form);

		expect(submitted).toHaveReturnedWith(true);
	});

	it('does not save with the keys while it is blocked', async () => {
		const { onsave } = setup({ saveBlocked: 'Give the rule a name' });

		await fireEvent.keyDown(screen.getByLabelText('Name'), { key: 'Enter', ctrlKey: true });

		expect(onsave).not.toHaveBeenCalled();
	});

	it('offers delete only for a stored rule', async () => {
		const ondelete = vi.fn();
		setup({ editing: true, ondelete });

		await fireEvent.click(screen.getByRole('button', { name: 'Delete…' }));

		expect(ondelete).toHaveBeenCalledOnce();
	});

	it('has no delete for a new rule', () => {
		setup();

		expect(screen.queryByRole('button', { name: 'Delete…' })).toBeNull();
	});

	it('cancels to the list, as an outline button', () => {
		setup();

		const cancel = screen.getByRole('link', { name: 'Cancel' });
		expect(cancel).toHaveAttribute('href', '/settings/rules');
		expect(cancel.className).toContain('border-border');
	});
});
