import { describe, expect, it, vi } from 'vitest';
import { refreshNotice, startRefresh } from './refresh.js';

describe('startRefresh', () => {
	it('starts the discovery and opens its page', async () => {
		const deps = { start: vi.fn().mockResolvedValue(null), go: vi.fn() };

		expect(await startRefresh(4, deps)).toBeNull();

		expect(deps.start).toHaveBeenCalledWith(4);
		expect(deps.go).toHaveBeenCalledWith('/settings/importers/4/accounts');
	});

	it('stays where it is when the start is refused, and returns the refusal', async () => {
		const refusal = { code: 'task_active', message: 'x' };
		const deps = { start: vi.fn().mockResolvedValue(refusal), go: vi.fn() };

		expect(await startRefresh(4, deps)).toBe(refusal);
		expect(deps.go).not.toHaveBeenCalled();
	});
});

describe('refreshNotice', () => {
	it('links a busy refusal to the running task', () => {
		expect(refreshNotice({ code: 'task_active', message: 'x' }, '/sync')).toEqual({
			text: 'A sync is already running',
			error: false,
			action: { label: 'Open the running task', path: '/sync' }
		});
	});

	it('says any other refusal as the server put it, as an error', () => {
		expect(
			refreshNotice({ code: 'instance_disabled', message: 'It is disabled.' }, '/sync')
		).toEqual({
			text: 'It is disabled.',
			error: true
		});
	});
});
