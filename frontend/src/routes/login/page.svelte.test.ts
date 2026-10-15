import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Page from './+page.svelte';

describe('login page', () => {
	it('shows the decorative mascot above the login form', () => {
		const { container } = render(Page);

		const img = container.querySelector('img');
		expect(img).toHaveAttribute('src', '/brand/mascot.png');
		expect(img).toHaveAttribute('alt', '');
		expect(img).toHaveAttribute('width', '128');
		expect(img).toHaveAttribute('height', '135');

		const heading = screen.getByRole('heading', { name: 'Ledgehog' });
		expect(img!.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});
});
