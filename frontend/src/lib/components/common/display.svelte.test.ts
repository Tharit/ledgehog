import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import AbsentValue from './absent-value.svelte';
import AccountDot from './account-dot.svelte';
import DateDisplay from './date-display.svelte';
import DimensionIcon from './dimension-icon.svelte';
import MoneyDisplay from './money-display.svelte';
import ReviewBadge from './review-badge.svelte';
import TagChip from './tag-chip.svelte';

describe('MoneyDisplay', () => {
	it('writes a true minus and colours a negative amount red', () => {
		render(MoneyDisplay, { props: { minor: -8431, currency: 'EUR' } });

		const amount = screen.getByText('−84.31');
		expect(amount).toHaveClass('text-amount-negative', 'amount');
	});

	it('writes a plus and colours a positive amount green', () => {
		render(MoneyDisplay, { props: { minor: 8000, currency: 'EUR' } });

		expect(screen.getByText('+80.00')).toHaveClass('text-amount-positive');
	});

	it('leaves zero uncoloured and unsigned', () => {
		render(MoneyDisplay, { props: { minor: 0, currency: 'EUR' } });

		const zero = screen.getByText('0.00');
		expect(zero).not.toHaveClass('text-amount-positive');
		expect(zero).not.toHaveClass('text-amount-negative');
	});

	it('shows the currency code on request, and follows the locale', () => {
		const { container } = render(MoneyDisplay, {
			props: { minor: -123456, currency: 'EUR', locale: 'de', showCurrency: true }
		});

		// a no-break space precedes the code, which the text matchers would normalise away
		expect(container.textContent).toBe('\u22121.234,56\u00a0EUR');
	});

	it('uses the currency’s own minor units', () => {
		render(MoneyDisplay, { props: { minor: -500, currency: 'JPY' } });

		expect(screen.getByText('−500')).toBeInTheDocument();
	});
});

describe('DateDisplay', () => {
	it('formats a calendar date without moving it', () => {
		render(DateDisplay, { props: { date: '2026-10-11', locale: 'en' } });

		const time = screen.getByText('Oct 11, 2026');
		expect(time.tagName).toBe('TIME');
		expect(time).toHaveAttribute('datetime', '2026-10-11');
	});
});

describe('AbsentValue', () => {
	it('shows the label with its explanation as a tooltip', () => {
		render(AbsentValue, { props: { label: 'Unclassified', explanation: 'No category yet' } });

		expect(screen.getByText('Unclassified')).toHaveAttribute('title', 'No category yet');
		expect(screen.getByText('Unclassified')).toHaveClass('decoration-dotted');
	});
});

describe('ReviewBadge', () => {
	it.each([
		['unconfirmed', 'Values are proposals'],
		['unclassified', 'Type or category missing'],
		['waiting', 'Partner still expected'],
		['unmatched_transfer', 'Transfer leg without a partner']
	])('%s carries its sentence as a tooltip', (flag, sentence) => {
		render(ReviewBadge, { props: { flag } });

		expect(screen.getByTitle(sentence)).toHaveAttribute('data-flag', flag);
	});

	it('says a transfer leg without a partner is waiting for its partner', () => {
		render(ReviewBadge, {
			props: { flag: 'waiting', entry: { type: 'transfer', counterpart_entry_id: null } }
		});

		expect(screen.getByTitle('Its partner has probably not been imported yet')).toBeInTheDocument();
	});

	it.each([
		{ type: 'transfer', counterpart_entry_id: 5 },
		{ type: 'flow', counterpart_entry_id: null }
	])('keeps the general words of the clock for %o', (entry) => {
		render(ReviewBadge, { props: { flag: 'waiting', entry } });

		expect(screen.getByTitle('Partner still expected')).toBeInTheDocument();
	});

	it('renders nothing for a token it does not know', () => {
		const { container } = render(ReviewBadge, { props: { flag: 'mystery' } });

		expect(container.querySelector('[data-flag]')).toBeNull();
	});
});

describe('AccountDot', () => {
	it('shows the name after a dot in the account colour', () => {
		const { container } = render(AccountDot, { props: { name: 'Giro', color: 'forest' } });

		expect(screen.getByText('Giro')).toBeInTheDocument();
		expect(container.querySelector('[data-slot="account-dot"]')?.getAttribute('style')).toContain(
			'--dot: var(--dim-forest)'
		);
	});

	it('falls back to stone for an unknown colour', () => {
		const { container } = render(AccountDot, { props: { name: 'X', color: 'neon' } });

		expect(container.querySelector('[data-slot="account-dot"]')?.getAttribute('style')).toContain(
			'var(--dim-stone)'
		);
	});
});

describe('TagChip', () => {
	it('shows the name in its colour and tint', () => {
		render(TagChip, { props: { name: 'Lisbon trip', color: 'lavender' } });

		const chip = screen.getByTitle('Lisbon trip');
		expect(chip).toHaveTextContent('Lisbon trip');
		expect(chip.getAttribute('style')).toContain('--chip-bg: var(--dim-lavender-tint)');
		expect(chip.getAttribute('style')).toContain('--chip-fg: var(--dim-lavender)');
	});

	it('has no remove X unless it is given onremove', () => {
		render(TagChip, { props: { name: 'Lisbon trip' } });

		expect(screen.queryByRole('button')).toBeNull();
	});

	it('with onremove shows a labelled X that calls it, on click and on Backspace or Delete', async () => {
		const onremove = vi.fn();
		render(TagChip, { props: { name: 'Lisbon trip', onremove } });

		const remove = screen.getByRole('button', { name: 'Remove tag Lisbon trip' });
		expect(remove).toHaveClass('opacity-0');
		await fireEvent.click(remove);
		await fireEvent.keyDown(remove, { key: 'Backspace' });
		await fireEvent.keyDown(remove, { key: 'Delete' });
		await fireEvent.keyDown(remove, { key: 'a' });

		expect(onremove).toHaveBeenCalledTimes(3);
	});
});

describe('DimensionIcon', () => {
	it('is decorative without a label', () => {
		const { container } = render(DimensionIcon, { props: { icon: 'car', color: 'slate' } });

		const tile = container.firstElementChild as HTMLElement;
		expect(tile).toHaveAttribute('aria-hidden', 'true');
		expect(tile.getAttribute('style')).toContain('--tile-bg: var(--dim-slate-tint)');
		expect(tile.querySelector('svg')).not.toBeNull();
	});

	it('is an image with a label', () => {
		render(DimensionIcon, { props: { icon: 'car', label: 'Transport' } });

		expect(screen.getByRole('img', { name: 'Transport' })).toBeInTheDocument();
	});

	it('shows the initial instead of an icon', () => {
		const { container } = render(DimensionIcon, { props: { initial: 'R', color: 'plum' } });

		expect(container).toHaveTextContent('R');
		expect(container.querySelector('svg')).toBeNull();
	});

	it('is 24px compact and 32px comfortable', () => {
		const compact = render(DimensionIcon, { props: { icon: 'car' } });
		expect(compact.container.firstElementChild).toHaveClass('size-6');
		const comfortable = render(DimensionIcon, { props: { icon: 'car', size: 'comfortable' } });
		expect(comfortable.container.firstElementChild).toHaveClass('size-8');
	});
});
