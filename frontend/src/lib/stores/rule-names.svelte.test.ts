import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listRules } from '#lib/api/index.js';
import { rule } from '#lib/rules/fixtures.js';
import { ruleNames } from './rule-names.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listRules: vi.fn()
}));

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

describe('RuleNamesStore', () => {
	it('ensure loads once; refresh asks again every time', async () => {
		await ruleNames.ensure();
		await ruleNames.ensure();
		expect(listRules).toHaveBeenCalledTimes(1);
		await ruleNames.refresh();
		expect(listRules).toHaveBeenCalledTimes(2);
	});

	it('is not fresh while a refresh is on its way, but still names what it knew', async () => {
		await ruleNames.refresh();
		expect(ruleNames.names.loaded).toBe(true);
		let finish: (rules: ReturnType<typeof rule>[]) => void = () => {};
		vi.mocked(listRules).mockReturnValue(new Promise((resolve) => (finish = resolve)));
		const pending = ruleNames.refresh();
		expect(ruleNames.names.loaded).toBe(false);
		expect(ruleNames.names.name(3)).toBe('Rewe');
		finish([]);
		await pending;
		expect(ruleNames.names.loaded).toBe(true);
		expect(ruleNames.names.name(3)).toBeUndefined();
	});

	it('invalidate makes the list old and lets ensure load again', async () => {
		await ruleNames.ensure();
		ruleNames.invalidate();
		expect(ruleNames.names.loaded).toBe(false);
		expect(ruleNames.names.name(3)).toBe('Rewe');
		await ruleNames.ensure();
		expect(listRules).toHaveBeenCalledTimes(2);
		expect(ruleNames.names.loaded).toBe(true);
	});

	it('discards an answer that a newer refresh or an invalidation overtook', async () => {
		let finish: (rules: ReturnType<typeof rule>[]) => void = () => {};
		vi.mocked(listRules).mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
		const pending = ruleNames.refresh();
		ruleNames.invalidate();
		finish([rule({ id: 3, name: 'Rewe' })]);
		await pending;
		expect(ruleNames.names.loaded).toBe(false);
	});

	it('a failed refresh stays quiet and is tried again', async () => {
		vi.mocked(listRules).mockRejectedValueOnce(new Error('down'));
		await ruleNames.ensure();
		expect(ruleNames.names.loaded).toBe(false);
		await ruleNames.ensure();
		expect(ruleNames.names.loaded).toBe(true);
	});
});
