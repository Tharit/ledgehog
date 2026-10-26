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

/** Picks a value in a choice select: opens it by its name and clicks the option. */
async function choose(name: string, option: string) {
	await fireEvent.click(screen.getByRole('button', { name }));
	await fireEvent.click(await screen.findByRole('option', { name: option }));
}

/** The options a choice select offers, read by opening it. */
async function optionsOf(name: string) {
	await fireEvent.click(screen.getByRole('button', { name }));
	const labels = (await screen.findAllByRole('option')).map((o) => o.textContent?.trim());
	await fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
	return labels;
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
		expect(screen.getByRole('button', { name: 'Sets' })).toHaveTextContent('Category');
		expect(screen.getByRole('button', { name: 'The category this rule sets' })).toHaveTextContent(
			'Rent'
		);
		expect(screen.getByRole('button', { name: 'Condition 1: field' })).toHaveTextContent(
			'Counterparty name'
		);
		expect(screen.getByRole('button', { name: 'Condition 1: operator' })).toHaveTextContent(
			'starts with'
		);
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

	const payeeRow = (value: string) => newConditionRow({ field: 'payee', op: 'is', value });
	const fieldOptions = () => optionsOf('Condition 1: field');

	it('offers the payee as a condition field on a category rule only', async () => {
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
		expect(await fieldOptions()).toContain('Payee');
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
		expect(await fieldOptions()).not.toContain('Payee');
	});

	it('chooses the payee field through the condition callback', async () => {
		const { oncondition } = setup();

		await choose('Condition 1: field', 'Payee');

		expect(oncondition).toHaveBeenCalledWith(0, { field: 'payee' });
	});

	it('shows a payee row with a fixed operator, the picker and its helper', async () => {
		const { oncondition } = setup({ form: form({ conditions: [payeeRow('20')] }) });

		const op = screen.getByRole('button', { name: 'Condition 1: operator' });
		expect(op).toBeDisabled();
		expect(op).toHaveTextContent('is');
		const picker = screen.getByRole('button', { name: 'Condition 1: payee' });
		expect(picker).toHaveTextContent('REWE');
		expect(
			screen.getByText(
				'Uses the payee found for the entry, even a suggested one you have not confirmed.'
			)
		).toBeInTheDocument();
		expect(screen.queryByText('Payee deleted')).toBeNull();
		expect(screen.queryByLabelText('Condition 1: value')).toBeNull();

		await fireEvent.click(picker);
		await fireEvent.click(await screen.findByRole('option', { name: /REWE/ }));
		expect(oncondition).toHaveBeenCalledWith(0, { value: '20' });
	});

	it('offers the source text and the account on every rule, in the entry group', async () => {
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

		const labels = await fieldOptions();
		expect(labels).toContain('Source text');
		expect(labels).toContain('Account');
	});

	it('shows a source text row like any text condition', () => {
		setup({
			form: form({
				conditions: [newConditionRow({ field: 'source_text', op: 'contains', value: 'cable' })]
			})
		});

		expect(screen.getByRole('button', { name: 'Condition 1: field' })).toHaveTextContent(
			'Source text'
		);
		expect(screen.getByLabelText('Condition 1: value')).toHaveValue('cable');
		expect(screen.getByRole('button', { name: 'Condition 1: operator' })).not.toBeDisabled();
	});

	it('shows an account row with a fixed operator and an account picker, and says a deleted account', async () => {
		const { oncondition } = setup({
			form: form({ conditions: [newConditionRow({ field: 'account', op: 'is', value: '2' })] })
		});

		const op = screen.getByRole('button', { name: 'Condition 1: operator' });
		expect(op).toBeDisabled();
		expect(op).toHaveTextContent('is');
		const picker = screen.getByRole('button', { name: 'Condition 1: account' });
		expect(picker).toHaveTextContent('Cash');
		expect(screen.queryByLabelText('Condition 1: value')).toBeNull();
		expect(screen.queryByText('Account deleted')).toBeNull();

		await fireEvent.click(picker);
		await fireEvent.click(await screen.findByRole('option', { name: /Giro/ }));
		expect(oncondition).toHaveBeenCalledWith(0, { value: '1' });
	});

	it('says "Account deleted" for an account that is not in the list', () => {
		setup({
			form: form({ conditions: [newConditionRow({ field: 'account', op: 'is', value: '99' })] })
		});

		expect(screen.getByText('Account deleted')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Condition 1: account' })).toHaveTextContent(
			'Choose an account'
		);
	});

	it('says "Payee deleted" for a payee that is not in the list, and lets another be picked', () => {
		setup({ form: form({ conditions: [payeeRow('99')] }) });

		const label = screen.getByText('Payee deleted');
		expect(label).toHaveAttribute(
			'title',
			'This payee no longer exists; the rule cannot match until you pick another.'
		);
		expect(screen.getByRole('button', { name: 'Condition 1: payee' })).toHaveTextContent(
			'Choose a payee'
		);
		expect(screen.getByRole('button', { name: 'Remove condition 1' })).toBeInTheDocument();
	});

	it('shows the server error on the payee row', () => {
		setup({
			form: form({ conditions: [payeeRow('99')] }),
			errors: { rows: { 0: 'This payee no longer exists.' } }
		});

		expect(screen.getByText('This payee no longer exists.')).toBeInTheDocument();
	});

	it('changes what it sets at once, with the preview to follow', async () => {
		const { onedit } = setup();

		await choose('Sets', 'Payee');

		expect(onedit).toHaveBeenCalledWith({ sets: 'payee' }, true);
	});

	it('fixes what it sets once the rule exists', () => {
		setup({ editing: true });

		expect(screen.getByRole('button', { name: 'Sets' })).toBeDisabled();
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
		const conditions = screen.getByRole('group', { name: /entry has/ });
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

		expect(screen.getByRole('button', { name: 'Condition 1: field' })).toHaveTextContent('Purpose');
		expect(screen.getByRole('button', { name: 'Condition 2: field' })).toHaveTextContent(
			'Mandate reference'
		);
		expect(screen.getByRole('button', { name: 'Condition 2: operator' })).toHaveTextContent('is');
		expect(screen.getByLabelText('Condition 2: value')).toHaveValue('M1');
	});

	it('offers the plain field and operator labels', async () => {
		setup();

		expect(await optionsOf('Condition 1: field')).toEqual([
			'Counterparty name',
			'Counterparty IBAN or reference',
			'Purpose',
			'Booking text',
			'Mandate reference',
			'Source text',
			'Account',
			'Payee'
		]);
		expect(await optionsOf('Condition 1: operator')).toEqual([
			'is',
			'starts with',
			'contains',
			'matches pattern (regex)'
		]);
	});

	it('groups the fields: the source transaction’s, then the entry’s with its text, account and payee', async () => {
		setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Condition 1: field' }));
		const source = await screen.findByRole('group', { name: 'From the source transaction' });
		const entryGroup = screen.getByRole('group', { name: 'From the entry' });

		expect(within(source).getAllByRole('option')).toHaveLength(5);
		expect(
			within(entryGroup)
				.getAllByRole('option')
				.map((o) => o.textContent?.trim())
		).toEqual(['Source text', 'Account', 'Payee']);
	});

	it('offers the payee on category rules only', async () => {
		setup({ form: form({ sets: 'payee' }) });

		expect(await optionsOf('Condition 1: field')).toEqual([
			'Counterparty name',
			'Counterparty IBAN or reference',
			'Purpose',
			'Booking text',
			'Mandate reference',
			'Source text',
			'Account'
		]);
	});

	it('reports a change of field, operator and value of one row', async () => {
		const { oncondition } = setup();

		await choose('Condition 1: field', 'Purpose');
		await choose('Condition 1: operator', 'matches pattern (regex)');
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

		// the reason is a tooltip (ActionButton), not a native title
		expect(saveButton()).toBeDisabled();
		expect(saveButton().closest('[title]')).toBeNull();
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
