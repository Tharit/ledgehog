import { describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { AccountController } from './controller.svelte.js';

describe('AccountController', () => {
	it('opens with the options given and closes', () => {
		const controller = new AccountController();

		controller.openAdd({ currency: 'USD', kind: 'cash' });

		expect(controller.adding).toBe(true);
		expect(controller.options).toMatchObject({ currency: 'USD', kind: 'cash' });
		controller.close();
		expect(controller.adding).toBe(false);
	});

	it('closes and tells the caller when an account was added', () => {
		const controller = new AccountController();
		const onadded = vi.fn();
		controller.openAdd({ onadded });
		const added = account({ id: 8 });

		controller.added(added);

		expect(controller.adding).toBe(false);
		expect(onadded).toHaveBeenCalledWith(added);
	});

	it('remembers where focus goes back to', () => {
		const controller = new AccountController();
		const button = document.createElement('button');

		controller.openAdd({ returnFocus: button });

		expect(controller.opener).toBe(button);
	});
});
