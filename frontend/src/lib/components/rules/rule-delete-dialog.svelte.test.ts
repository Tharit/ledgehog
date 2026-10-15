import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
// the test stubs the API at its boundary (the one place a component test may name it)
// eslint-disable-next-line no-restricted-imports
import { ApiError, deleteRule } from '#lib/api/index.js';
import { preview, previewList, previewRow, rule } from '#lib/rules/fixtures.js';
import { RuleDeleteFlow } from '#lib/stores/rule-delete.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { rulesNamed } from '#lib/units/evidence.js';
import RuleDeleteDialog from './rule-delete-dialog.svelte';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	deleteRule: vi.fn()
}));

function dry(matches: number, keyed: number) {
	return {
		dry_run: true,
		rule: rule(),
		deleted: false,
		settle: null,
		settle_breakdown: null,
		preview: preview({
			matches: previewList([previewRow()], matches),
			lost_key: previewList([previewRow()], keyed)
		})
	};
}

function setup() {
	const host = { deleted: vi.fn(), gone: vi.fn(), locale: () => 'en' };
	const flow = new RuleDeleteFlow(host);
	render(RuleDeleteDialog, { props: { flow } });
	return { flow, host };
}

const verb = () => screen.getByRole('button', { name: /^Delete(ing…)?$/ });

beforeEach(() => {
	vi.resetAllMocks();
});

describe('RuleDeleteDialog', () => {
	it('names the counts of the dry run before it asks', async () => {
		vi.mocked(deleteRule).mockResolvedValue(dry(14, 9));
		const { flow } = setup();

		await flow.start(rule({ id: 4, name: 'Landlord' }));

		expect(await screen.findByText(/Delete the rule “Landlord”\?/)).toBeInTheDocument();
		expect(await screen.findByText('14 entries')).toBeInTheDocument();
		expect(screen.getByText('9 entries')).toBeInTheDocument();
		expect(deleteRule).toHaveBeenCalledWith(4, { dryRun: true, limit: 1 });
	});

	it('cannot be confirmed before the counts have arrived', async () => {
		vi.mocked(deleteRule).mockReturnValue(new Promise(() => {}));
		const { flow } = setup();

		void flow.start(rule());

		await waitFor(() => expect(verb()).toBeDisabled());
	});

	it('deletes with the previewed count and says what settled', async () => {
		vi.mocked(deleteRule).mockResolvedValueOnce(dry(14, 9));
		const { flow, host } = setup();
		await flow.start(rule({ id: 4 }));
		await waitFor(() => expect(verb()).toBeEnabled());
		vi.mocked(deleteRule).mockResolvedValueOnce({
			...dry(14, 9),
			dry_run: false,
			deleted: true,
			settle: { touched_entry_ids: [1, 2], error: null },
			settle_breakdown: { total: 2, this_rule: 0, history: 0, other_rules: 2, other: 0 }
		});

		await fireEvent.click(verb());

		await waitFor(() => expect(host.deleted).toHaveBeenCalledOnce());
		expect(vi.mocked(deleteRule).mock.calls.at(-1)).toEqual([4, { expectedCount: 14, limit: 1 }]);
		expect(host.deleted.mock.calls[0][1]).toEqual({
			total: 2,
			thisRule: 0,
			history: 0,
			otherRules: 2,
			other: 0
		});
		expect(flow.open).toBe(false);
	});

	it('marks the rule names held as old once the rule is deleted', async () => {
		vi.mocked(deleteRule).mockResolvedValueOnce(dry(14, 9));
		const { flow } = setup();
		await flow.start(rule({ id: 4 }));
		await waitFor(() => expect(verb()).toBeEnabled());
		ruleNames.names = rulesNamed([{ id: 4, name: 'Rewe' }]);
		vi.mocked(deleteRule).mockResolvedValueOnce({ ...dry(14, 9), dry_run: false, deleted: true });

		await fireEvent.click(verb());

		await waitFor(() => expect(flow.open).toBe(false));
		expect(ruleNames.names.loaded).toBe(false);
		ruleNames.reset();
	});

	it('shows the new counts and asks again when the result moved', async () => {
		vi.mocked(deleteRule).mockResolvedValueOnce(dry(14, 9));
		const { flow, host } = setup();
		await flow.start(rule({ id: 4 }));
		await waitFor(() => expect(verb()).toBeEnabled());
		vi.mocked(deleteRule)
			.mockRejectedValueOnce(
				new ApiError(409, 'conflict', 'x', {
					reason: 'filter_result_changed',
					expected: 14,
					actual: 16
				})
			)
			.mockResolvedValueOnce(dry(16, 9));

		await fireEvent.click(verb());

		expect(await screen.findByText('16 entries')).toBeInTheDocument();
		expect(screen.getByText(/14 entries before, 16 now/)).toBeInTheDocument();
		expect(host.deleted).not.toHaveBeenCalled();
		expect(flow.open).toBe(true);
	});

	it('Cancel closes without deleting', async () => {
		vi.mocked(deleteRule).mockResolvedValue(dry(1, 0));
		const { flow, host } = setup();
		await flow.start(rule());
		await waitFor(() => expect(verb()).toBeEnabled());

		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

		expect(flow.open).toBe(false);
		expect(host.deleted).not.toHaveBeenCalled();
		expect(deleteRule).toHaveBeenCalledTimes(1);
	});

	it('closes and says the rule was gone when it already is', async () => {
		vi.mocked(deleteRule).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		const { flow, host } = setup();

		await flow.start(rule());

		expect(host.gone).toHaveBeenCalledOnce();
		expect(flow.open).toBe(false);
	});
});
