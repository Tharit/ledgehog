import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { accountSankey } from '#lib/reports/sankey.js';
import { byAccount, byAccountLookups } from '#lib/reports/trend-fixtures.js';
import AccountSankey from './account-sankey.svelte';

const { categories, accounts } = byAccountLookups();
const scope = { from: '2026-10-01', to: '2026-10-31', accountIds: [], tagIds: [] };
const model = () => accountSankey(byAccount(), categories, accounts, scope);

// the tooltip comes and goes with a transition, which asks the element to `animate`: jsdom has none
const animate = Element.prototype.animate;
beforeAll(() => {
	Element.prototype.animate = (() => ({
		cancel() {},
		finish() {},
		pause() {},
		play() {},
		currentTime: 0,
		onfinish: null,
		finished: Promise.resolve()
	})) as unknown as typeof Element.prototype.animate;
});
afterAll(() => {
	Element.prototype.animate = animate;
});

describe('AccountSankey', () => {
	it('draws the links of the model and nothing for the layout-only connections', async () => {
		const { container } = render(AccountSankey, { props: { model: model() } });

		const links = await vi_waitFor(() => container.querySelectorAll('[data-link]'));
		expect(links).toHaveLength(model().links.length);
		expect(container.querySelectorAll('[data-link] path')).toHaveLength(model().links.length);
	});

	it('shows the tooltip of a link on pointer move, and of another on focus', async () => {
		const { container } = render(AccountSankey, { props: { model: model() } });

		const links = await vi_waitFor(() => container.querySelectorAll('[data-link]'));
		const transfer = [...links].find((l) => l.getAttribute('data-kind') === 'transfer')!;
		await fireEvent.pointerMove(transfer, { clientX: 20, clientY: 20 });
		expect(await screen.findByText(/Giro to Savings/)).toBeInTheDocument();
		expect(screen.getByText('Transfer')).toBeInTheDocument();

		// the hide path is not asserted: the tooltip leaves with a transition that never finishes
		// under the stub above, so it stays in the document here.
		const other = [...links].find((l) => l.getAttribute('data-kind') === 'other')!;
		await fireEvent.focus(other.querySelector('a')!);
		expect(await screen.findByText(/Other to Savings/)).toBeInTheDocument();
	});

	it('tells what stayed from the answer’s own figures, adding nothing', async () => {
		const { container } = render(AccountSankey, { props: { model: model() } });

		const links = await vi_waitFor(() => container.querySelectorAll('[data-link]'));
		const band = [...links].find((l) => l.getAttribute('data-link') === '1:a1>2:a1')!;
		await fireEvent.pointerMove(band, { clientX: 20, clientY: 20 });

		// 305,000 received, 103,000 transferred out, 202,000 stayed (the links beside it sum to
		// 302,000 and 100,000)
		const tip = (await screen.findByText('Transferred out')).closest(
			'[data-slot="figure-tooltip"]'
		)!;
		expect(tip).toHaveTextContent(/Received\s*\+?3,050\.00/);
		expect(tip).toHaveTextContent(/Transferred out\s*\S?1,030\.00/);
		expect(tip).toHaveTextContent(/Stayed\s*\+?2,020\.00/);
		expect(tip).not.toHaveTextContent('3,020.00');
	});
});

/** The chart lays out when its container has a size; poll for the links to appear. */
async function vi_waitFor(find: () => NodeListOf<Element>): Promise<NodeListOf<Element>> {
	for (let i = 0; i < 50; i++) {
		const found = find();
		if (found.length > 0) return found;
		await new Promise((r) => setTimeout(r, 20));
	}
	throw new Error(
		'the chart drew no links: jsdom gave its container no size, or the layout failed'
	);
}
