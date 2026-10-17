import { describe, expect, it } from 'vitest';
import { ledgerKey, moveCursor } from './keys.js';

describe('ledgerKey', () => {
	it('maps the list keys', () => {
		expect(ledgerKey({ key: 'ArrowUp' })).toBe('up');
		expect(ledgerKey({ key: 'k' })).toBe('up');
		expect(ledgerKey({ key: 'ArrowDown' })).toBe('down');
		expect(ledgerKey({ key: 'j' })).toBe('down');
		expect(ledgerKey({ key: 'Enter' })).toBe('open');
		expect(ledgerKey({ key: 'Escape' })).toBe('escape');
		expect(ledgerKey({ key: '/' })).toBe('search');
		expect(ledgerKey({ key: '?' })).toBe('help');
		expect(ledgerKey({ key: 't' })).toBe('tag');
		expect(ledgerKey({ key: 'p' })).toBe('provenance');
	});

	it('ignores other keys', () => {
		expect(ledgerKey({ key: 'a' })).toBeNull();
		expect(ledgerKey({ key: 'J' })).toBeNull();
		expect(ledgerKey({ key: 'T' })).toBeNull();
		expect(ledgerKey({ key: 'R' })).toBeNull();
		expect(ledgerKey({ key: 'r' })).toBeNull();
	});

	it('ignores a key with a modifier (browser and system shortcuts)', () => {
		expect(ledgerKey({ key: 'k', ctrlKey: true })).toBeNull();
		expect(ledgerKey({ key: 'j', metaKey: true })).toBeNull();
		expect(ledgerKey({ key: '/', altKey: true })).toBeNull();
	});

	it('ignores a key somebody already handled', () => {
		expect(ledgerKey({ key: 'Escape', defaultPrevented: true })).toBeNull();
	});

	it('ignores keys typed into a field or a panel', () => {
		for (const tag of ['input', 'textarea', 'select']) {
			const field = document.createElement(tag);
			document.body.append(field);
			expect(ledgerKey({ key: 'j', target: field })).toBeNull();
			field.remove();
		}
		const dialog = document.createElement('div');
		dialog.setAttribute('role', 'dialog');
		const button = document.createElement('button');
		dialog.append(button);
		document.body.append(dialog);
		expect(ledgerKey({ key: 'j', target: button })).toBeNull();
		dialog.remove();
	});

	it('leaves ArrowDown in a text field to the field (the filter box hands over itself)', () => {
		const field = document.createElement('input');
		document.body.append(field);
		expect(ledgerKey({ key: 'ArrowDown', target: field })).toBeNull();
		field.remove();
	});

	it('handles keys on the page itself', () => {
		expect(ledgerKey({ key: 'j', target: document.body })).toBe('down');
	});
});

describe('moveCursor', () => {
	it('moves by one and stops at both ends', () => {
		expect(moveCursor(2, 1, 5)).toBe(3);
		expect(moveCursor(2, -1, 5)).toBe(1);
		expect(moveCursor(4, 1, 5)).toBe(4);
		expect(moveCursor(0, -1, 5)).toBe(0);
	});

	it('lands on the first row when there is no cursor yet, whichever way it moves', () => {
		expect(moveCursor(-1, 1, 5)).toBe(0);
		expect(moveCursor(-1, -1, 5)).toBe(0);
	});

	it('has no cursor in an empty list', () => {
		expect(moveCursor(-1, 1, 0)).toBe(-1);
		expect(moveCursor(3, 1, 0)).toBe(-1);
	});
});
