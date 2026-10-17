import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { RowAddress } from './row-address.svelte.js';

// the real history, as the page's navigation uses it: opening must be seen without a reload
const popped = () =>
	new Promise<void>((resolve) => addEventListener('popstate', () => resolve(), { once: true }));

beforeEach(() => history.replaceState(null, '', '/accounts/1'));
afterEach(() => history.replaceState(null, '', '/'));

describe('RowAddress', () => {
	it('reads the address it is given', () => {
		history.replaceState(null, '', '/accounts/1?source=7');
		const address = new RowAddress();
		address.sync();
		expect(address.id).toBe(7);
	});

	it('opens a row at once, writing it to the address, with no reload and no `page.url`', () => {
		const address = new RowAddress();
		address.sync();
		expect(address.id).toBeNull();

		address.open(5);

		expect(address.id).toBe(5);
		expect(location.search).toBe('?source=5');
	});

	it('keeps the rest of the address and opens another row as a further entry', () => {
		history.replaceState(null, '', '/accounts/1?unit=3');
		const address = new RowAddress();
		address.open(5);
		address.open(6);
		expect(location.search).toBe('?unit=3&source=6');
		expect(address.id).toBe(6);
	});

	it('closes by taking back the entries it added, and follows Back', async () => {
		const address = new RowAddress();
		const follow = () => address.sync();
		addEventListener('popstate', follow);
		address.open(5);
		address.open(6);

		const back = popped();
		address.close();
		expect(address.id).toBeNull();
		await back;

		expect(location.search).toBe('');
		expect(address.id).toBeNull();
		removeEventListener('popstate', follow);
	});

	it('follows a Back that the user pressed', async () => {
		const address = new RowAddress();
		const follow = () => address.sync();
		addEventListener('popstate', follow);
		address.open(5);

		const back = popped();
		history.back();
		await back;

		expect(address.id).toBeNull();
		removeEventListener('popstate', follow);
	});

	it('leaves at once for the panel: the parameter is replaced away', () => {
		const address = new RowAddress();
		address.open(5);
		address.leave();
		expect(address.id).toBeNull();
		expect(location.search).toBe('');
	});

	it('closes with nothing to take back by dropping the parameter', () => {
		history.replaceState(null, '', '/accounts/1?source=7');
		const address = new RowAddress();
		address.sync();
		address.close();
		expect(address.id).toBeNull();
		expect(location.search).toBe('');
	});
});
