import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { category } from '#lib/ledger/fixtures.js';
import { byCategory, line, overview, span } from '#lib/reports/fixtures.js';
import NetWorthCard from './net-worth-card.svelte';
import ReviewCard from './review-card.svelte';
import SavingsCard from './savings-card.svelte';
import SpendCard from './spend-card.svelte';
import TopCategoriesCard from './top-categories-card.svelte';

const usd = (amount: number, count: number) => ({ amount: { amount, currency: 'USD' }, count });

/** the card named so, and a way to find one of its quiet rows by its label */
function card(name: string) {
	const region = screen.getByRole('region', { name });
	const row = (label: string) => {
		const found = [...region.querySelectorAll<HTMLElement>('[data-slot="card-row"]')].find((r) =>
			r.textContent?.trim().startsWith(label)
		);
		if (!found) throw new Error(`no row "${label}" in ${name}`);
		return within(found);
	};
	return { region, row, queryRows: () => region.querySelectorAll('[data-slot="card-row"]') };
}

describe('the Net worth card', () => {
	it('shows the net worth with its currency code and the change since the end of last month', () => {
		render(NetWorthCard, { props: { netWorth: overview().net_worth } });

		const { region, row, queryRows } = card('Net worth');
		expect(within(region).getByText('128,450.00 EUR')).toBeInTheDocument();
		expect(queryRows()).toHaveLength(1);
		expect(row('Since Sep 30, 2026').getByText('+1,200.00 EUR')).toBeInTheDocument();
	});

	it('says what is owed to the household and what it owes, with the accounts, each linking to Accounts and above the change', () => {
		const group = (kind: 'receivable' | 'debt', accounts: number, amount: number) => ({
			kind,
			accounts,
			net_worth: { total: { amount, currency: 'EUR' }, unvalued: [] }
		});
		render(NetWorthCard, {
			props: {
				netWorth: {
					...overview().net_worth,
					owed_to_you: group('receivable', 1, 20000),
					you_owe: group('debt', 2, -12000000)
				}
			}
		});

		const { region, row, queryRows } = card('Net worth');
		expect(queryRows()).toHaveLength(3);
		expect(row('Owed to you, 1 account').getByText('200.00 EUR')).toBeInTheDocument();
		expect(row('You owe, 2 accounts').getByText('−120,000.00 EUR')).toBeInTheDocument();
		const rows = [...queryRows()];
		expect(rows[0]).toHaveAttribute('href', '/accounts');
		expect(rows[1]).toHaveAttribute('href', '/accounts');
		expect(rows[2].textContent).toContain('Since');
		expect(region).toBeInTheDocument();
	});

	it('says "unvalued" for a debt that could not be valued', () => {
		render(NetWorthCard, {
			props: {
				netWorth: {
					...overview().net_worth,
					you_owe: {
						kind: 'debt',
						accounts: 1,
						net_worth: {
							total: null,
							unvalued: [{ amount: { amount: -900, currency: 'USD' }, accounts: 1 }]
						}
					}
				}
			}
		});

		expect(card('Net worth').row('You owe, 1 account').getByText('unvalued')).toBeInTheDocument();
	});

	it('has no row for a change that does not exist (nothing was there at that date)', () => {
		render(NetWorthCard, {
			props: { netWorth: { ...overview().net_worth, since: null } }
		});

		expect(card('Net worth').queryRows()).toHaveLength(0);
	});

	it('names what could not be valued, per currency, with the number of accounts', () => {
		render(NetWorthCard, {
			props: {
				netWorth: {
					...overview().net_worth,
					unvalued: [
						{ amount: { amount: 120000, currency: 'USD' }, accounts: 2 },
						{ amount: { amount: -5000, currency: 'CHF' }, accounts: 1 }
					]
				}
			}
		});

		const { row } = card('Net worth');
		expect(row('Unvalued, 2 accounts').getByText('1,200.00 USD')).toBeInTheDocument();
		expect(row('Unvalued, 1 account').getByText('−50.00 CHF')).toBeInTheDocument();
	});

	it('lists the unpaired transfers with their count, linking to the legs that wait or have no partner', () => {
		render(NetWorthCard, {
			props: {
				netWorth: { ...overview().net_worth, unpaired_transfers: line(50000, { count: 2 }) }
			}
		});

		const link = screen.getByRole('link', { name: /2 transfers still unpaired/ });
		expect(link).toHaveAttribute(
			'href',
			'/ledger?type=transfer&flag=waiting&flag=unmatched_transfer'
		);
		expect(link).toHaveTextContent('+500.00 EUR');
	});

	it('says "1 transfer" for one, and has no row for none', () => {
		const { unmount } = render(NetWorthCard, {
			props: {
				netWorth: { ...overview().net_worth, unpaired_transfers: line(-2000, { count: 1 }) }
			}
		});
		expect(screen.getByRole('link', { name: /1 transfer still unpaired/ })).toBeInTheDocument();
		unmount();

		render(NetWorthCard, { props: { netWorth: overview().net_worth } });
		expect(screen.queryByRole('link')).toBeNull();
	});

	it('says "unvalued", not zero, when no balance could be valued', () => {
		render(NetWorthCard, {
			props: {
				netWorth: {
					...overview().net_worth,
					total: null,
					unvalued: [{ amount: { amount: 100, currency: 'USD' }, accounts: 1 }]
				}
			}
		});

		const { region } = card('Net worth');
		expect(within(region).getByText('unvalued')).toBeInTheDocument();
		expect(within(region).queryByText(/^0\.00/)).toBeNull();
	});

	it('is a skeleton until the first answer', () => {
		render(NetWorthCard, { props: { netWorth: null } });

		const { region } = card('Net worth');
		expect(region.querySelector('[data-slot="figure-skeleton"]')).not.toBeNull();
		expect(region).toHaveAttribute('aria-busy', 'true');
	});
});

describe('the Savings rate card', () => {
	it('shows the 12-month rate in whole percent, with the months it covers', () => {
		render(SavingsCard, { props: { savings: overview().savings } });

		const { region } = card('Savings rate');
		expect(region).toHaveTextContent('Last 12 months, Oct 2025 – Sep 2026');
		expect(within(region).getByRole('heading', { level: 2 }).textContent?.trim()).toBe(
			'Savings rate'
		);
		expect(region.querySelector('.text-\\[28px\\]')).toHaveTextContent('42%');
	});

	it('shows last month, this month so far and what was kept of the income', () => {
		render(SavingsCard, { props: { savings: overview().savings } });

		const { region, row } = card('Savings rate');
		expect(row('Last month').getByText('35%')).toBeInTheDocument();
		expect(row('This month so far').getByText('60%')).toBeInTheDocument();
		expect(region).toHaveTextContent(/Kept\s*1,800\.00 EUR\s*of\s*3,000\.00 EUR\s*income/);
	});

	it('writes a dash when income is not positive, and no marker when nothing is incomplete', () => {
		const base = overview().savings;
		render(SavingsCard, {
			props: { savings: { ...base, last_12: span({ rate_bp: null }) } }
		});

		const { region } = card('Savings rate');
		expect(region.querySelector('.text-\\[28px\\]')).toHaveTextContent('—');
		expect(region.querySelector('[data-slot="incomplete-marker"]')).toBeNull();
	});

	it('marks the period that has unclassified entries, reconciliations or unvalued amounts', () => {
		const base = overview().savings;
		render(SavingsCard, {
			props: {
				savings: {
					...base,
					last_12: span({ incomplete: true }),
					this_month: span({ rate_bp: null, incomplete: true })
				}
			}
		});

		const { region, row } = card('Savings rate');
		const figure = region.querySelector<HTMLElement>('.text-\\[28px\\]')!;
		const marker = within(figure).getByRole('img');
		expect(marker).toHaveAttribute('title', expect.stringContaining('may be incomplete'));
		const thisMonth = row('This month so far');
		expect(thisMonth.getByText('—')).toBeInTheDocument();
		expect(thisMonth.getByRole('img')).toBeInTheDocument();
		expect(row('Last month').queryByRole('img')).toBeNull();
	});

	it('has no "Kept" row without income', () => {
		const base = overview().savings;
		render(SavingsCard, {
			props: {
				savings: { ...base, last_12: span({ income: line(0), savings: line(0), rate_bp: null }) }
			}
		});

		expect(card('Savings rate').region).not.toHaveTextContent('Kept');
	});

	it('is a skeleton until the first answer', () => {
		render(SavingsCard, { props: { savings: null } });

		expect(
			card('Savings rate').region.querySelector('[data-slot="figure-skeleton"]')
		).not.toBeNull();
	});
});

describe('the Spend card', () => {
	const FROM = '2026-10-01';
	const TO = '2026-10-20';

	it('shows this month so far, signed, linking to By category for the month', () => {
		render(SpendCard, { props: { spend: overview().spend } });

		const link = screen.getByRole('link', { name: /^−1,240\.00\s+EUR$/ });
		expect(link).toHaveAttribute('href', `/reports/by-category?from=${FROM}&to=${TO}`);
		expect(card('Spend').region).toHaveTextContent('October so far');
	});

	it('has no unclassified or reconciliation row when there is nothing of either', () => {
		render(SpendCard, { props: { spend: overview().spend } });

		const { region } = card('Spend');
		expect(region).not.toHaveTextContent('Plus unclassified');
		expect(region).not.toHaveTextContent('Plus reconciliations');
		expect(region.querySelector('[data-slot="spend-beside"]')).toBeNull();
	});

	it('puts the unclassified amount out and the reconciliations first among the rows, each linking to the ledger', () => {
		const base = overview().spend;
		render(SpendCard, {
			props: {
				spend: {
					...base,
					this_month: {
						...base.this_month,
						unclassified_out: line(-31000, { count: 4 }),
						reconciliations: line(-4200, { count: 1 })
					}
				}
			}
		});

		const { region, row } = card('Spend');
		expect(row('Plus unclassified').getByText('−310.00 EUR')).toBeInTheDocument();
		expect(row('Plus reconciliations').getByText('−42.00 EUR')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Plus unclassified/ })).toHaveAttribute(
			'href',
			`/ledger?from=${FROM}&to=${TO}&uncategorised=true&direction=out`
		);
		expect(screen.getByRole('link', { name: /Plus reconciliations/ })).toHaveAttribute(
			'href',
			`/ledger?from=${FROM}&to=${TO}&type=reconciliation`
		);
		const labels = [...region.querySelectorAll('[data-slot="card-row"]')].map((r) =>
			r.textContent?.trim()
		);
		expect(labels[0]).toMatch(/^Plus unclassified/);
		expect(labels[1]).toMatch(/^Plus reconciliations/);
		expect(labels[2]).toMatch(/^Last month/);
	});

	it('has a row only for the part that has entries', () => {
		const base = overview().spend;
		render(SpendCard, {
			props: {
				spend: {
					...base,
					this_month: { ...base.this_month, reconciliations: line(-4200, { count: 1 }) }
				}
			}
		});

		const { region, row } = card('Spend');
		expect(row('Plus reconciliations').getByText('−42.00 EUR')).toBeInTheDocument();
		expect(region).not.toHaveTextContent('Plus unclassified');
	});

	it('compares with last month in full and to the same day, each linking to its range', () => {
		render(SpendCard, { props: { spend: overview().spend } });

		const full = screen.getByRole('link', { name: /^Last month\s*−2,615\.00\s+EUR$/ });
		expect(full).toHaveAttribute('href', '/reports/by-category?from=2026-09-01&to=2026-09-30');
		const same = screen.getByRole('link', {
			name: /^Last month to Sep 20, 2026\s*−1,800\.00\s+EUR$/
		});
		expect(same).toHaveAttribute('href', '/reports/by-category?from=2026-09-01&to=2026-09-20');
	});

	it('says "unvalued", not zero, for a month whose spend could not be valued', () => {
		const base = overview().spend;
		render(SpendCard, {
			props: {
				spend: {
					...base,
					this_month: {
						...base.this_month,
						spend: line(null, { count: 2, unvalued: [usd(-9000, 2)] })
					}
				}
			}
		});

		expect(within(card('Spend').region).getAllByText('unvalued')[0]).toBeInTheDocument();
		expect(screen.queryByText('0.00 EUR')).toBeNull();
	});

	it('is a skeleton until the first answer', () => {
		render(SpendCard, { props: { spend: null } });

		expect(card('Spend').region.querySelector('[data-slot="figure-skeleton"]')).not.toBeNull();
	});
});

describe('the To review card', () => {
	it('shows the count linking to the queue, with a row per part', () => {
		render(ReviewCard, { props: { counts: { pendingReview: 11, needsAccount: 3 } } });

		const { region, row, queryRows } = card('To review');
		expect(screen.getByRole('link', { name: '14' })).toHaveAttribute('href', '/review');
		expect(screen.getAllByRole('link')).toHaveLength(1);
		expect(queryRows()).toHaveLength(2);
		expect(row('Ready to review').getByText('11')).toBeInTheDocument();
		expect(row('Needs an account').getByText('3')).toBeInTheDocument();
		expect(region.querySelector('.text-\\[28px\\] svg')).toBeNull();
	});

	it('leaves out a part that is zero', () => {
		const { unmount } = render(ReviewCard, {
			props: { counts: { pendingReview: 0, needsAccount: 1 } }
		});
		expect(card('To review').region).toHaveTextContent('Needs an account');
		expect(card('To review').region).not.toHaveTextContent('Ready to review');
		unmount();

		render(ReviewCard, { props: { counts: { pendingReview: 2, needsAccount: 0 } } });
		expect(card('To review').region).toHaveTextContent('Ready to review');
		expect(card('To review').region).not.toHaveTextContent('Needs an account');
	});

	it('says "All reviewed" at zero, with no link and no rows', () => {
		render(ReviewCard, { props: { counts: { pendingReview: 0, needsAccount: 0 } } });

		const { region, queryRows } = card('To review');
		expect(region).toHaveTextContent('All reviewed');
		expect(screen.queryByRole('link')).toBeNull();
		expect(queryRows()).toHaveLength(0);
	});

	it('is a skeleton until the count is known, not a false "All reviewed"', () => {
		render(ReviewCard, { props: { counts: null } });

		const { region } = card('To review');
		expect(region.querySelector('[data-slot="figure-skeleton"]')).not.toBeNull();
		expect(region).not.toHaveTextContent('All reviewed');
	});
});

describe('the four figure cards', () => {
	it('each carry an icon beside the title and a one-line subtitle, so that their rows align', () => {
		render(NetWorthCard, { props: { netWorth: overview().net_worth } });
		render(SavingsCard, { props: { savings: overview().savings } });
		render(SpendCard, { props: { spend: overview().spend } });
		render(ReviewCard, { props: { counts: { pendingReview: 11, needsAccount: 3 } } });

		for (const name of ['Net worth', 'Savings rate', 'Spend', 'To review']) {
			const { region } = card(name);
			const heading = within(region).getByRole('heading', { level: 2 });
			expect(heading.querySelector('svg'), `${name} icon`).not.toBeNull();
			const caption = region.querySelector('header > p');
			expect(caption?.textContent?.trim(), `${name} subtitle`).toBeTruthy();
		}
	});

	it('hold the subtitle line while loading, so that the skeletons align', () => {
		render(SpendCard, { props: { spend: null } });

		expect(card('Spend').region.querySelector('[data-slot="caption-skeleton"]')).not.toBeNull();
	});
});

describe('the Top expense categories card', () => {
	const FROM = '2026-10-01';
	const TO = '2026-10-20';
	const housing = category({ id: 10, name: 'Housing', color: 'forest', icon: 'house' });
	const food = category({ id: 11, name: 'Food', color: 'ochre', icon: 'utensils' });
	const categories = new Map([housing, food].map((c) => [c.id, c]));

	const report = (over = {}) =>
		byCategory({
			slices: [
				{ category_id: 10, total: line(-98000) },
				{ category_id: 11, total: line(-49000) }
			],
			other: line(-13500, { count: 3 }),
			unclassified_out: line(-31000, { count: 4 }),
			...over
		});

	const barOf = (key: string) =>
		document.querySelector<HTMLElement>(`[data-category="${key}"] .rounded-full`)!;

	it('names the month, and its header opens By category for it', () => {
		render(TopCategoriesCard, { props: { report: report(), status: 'ready', categories } });

		expect(
			screen.getByRole('heading', { name: 'Top expense categories, October so far' })
		).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /By category/ })).toHaveAttribute(
			'href',
			`/reports/by-category?from=${FROM}&to=${TO}`
		);
	});

	it('draws a signed amount and a bar per category, in the category colour, scaled to the largest', () => {
		render(TopCategoriesCard, { props: { report: report(), status: 'ready', categories } });

		const row = within(document.querySelector<HTMLElement>('[data-category="10"]')!);
		expect(row.getByText('Housing')).toBeInTheDocument();
		expect(row.getByText('−980.00 EUR')).toBeInTheDocument();
		expect(barOf('10').style.width).toBe('100%');
		expect(barOf('11').style.width).toBe('50%');

		expect(barOf('10')).toHaveAttribute('data-color', 'forest');
		expect(barOf('11')).toHaveAttribute('data-color', 'ochre');
	});

	it('opens the ledger filtered by the category and the month from a row', () => {
		render(TopCategoriesCard, { props: { report: report(), status: 'ready', categories } });

		expect(screen.getByRole('link', { name: /Housing/ })).toHaveAttribute(
			'href',
			`/ledger?from=${FROM}&to=${TO}&category_id=10`
		);
	});

	it('shows "Other" in stone, as no link, and the unclassified amount out beneath', () => {
		render(TopCategoriesCard, { props: { report: report(), status: 'ready', categories } });

		const other = document.querySelector<HTMLElement>('[data-category="other"]')!;
		expect(other).toHaveTextContent('Other');
		expect(other).toHaveTextContent('−135.00 EUR');
		expect(other.querySelector('a')).toBeNull();
		expect(barOf('other')).toHaveAttribute('data-color', 'stone');

		const unclassified = document.querySelector<HTMLElement>('[data-slot="unclassified-out"]')!;
		expect(unclassified).toHaveTextContent('Unclassified');
		expect(unclassified).toHaveTextContent('−310.00 EUR');
		expect(unclassified).toHaveAttribute(
			'href',
			`/ledger?from=${FROM}&to=${TO}&uncategorised=true&direction=out`
		);
		const list = document.querySelector('[data-slot="category-bars"]')!;
		expect(
			list.compareDocumentPosition(unclassified) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
	});

	it('has no "Other" row without one, and no unclassified row without entries', () => {
		render(TopCategoriesCard, {
			props: {
				report: report({ other: null, unclassified_out: line(0) }),
				status: 'ready',
				categories
			}
		});

		expect(document.querySelector('[data-category="other"]')).toBeNull();
		expect(document.querySelector('[data-slot="unclassified-out"]')).toBeNull();
	});

	it('draws no bar for an amount that cannot be valued, and says "unvalued"', () => {
		render(TopCategoriesCard, {
			props: {
				report: report({
					slices: [
						{ category_id: 10, total: line(-98000) },
						{ category_id: 11, total: line(null, { count: 2, unvalued: [usd(-4000, 2)] }) }
					]
				}),
				status: 'ready',
				categories
			}
		});

		expect(barOf('11').style.width).toBe('0%');
		expect(
			within(document.querySelector<HTMLElement>('[data-category="11"]')!).getByText('unvalued')
		).toBeInTheDocument();
	});

	it('names a category the lists do not hold yet "Category"', () => {
		render(TopCategoriesCard, {
			props: { report: report(), status: 'ready', categories: new Map() }
		});

		expect(
			within(document.querySelector<HTMLElement>('[data-category="10"]')!).getByText('Category')
		).toBeInTheDocument();
	});

	it('says so when nothing was spent', () => {
		render(TopCategoriesCard, {
			props: {
				report: byCategory({ slices: [], other: null }),
				status: 'ready',
				categories
			}
		});

		expect(screen.getByText('Nothing spent this month yet.')).toBeInTheDocument();
	});

	it('is a skeleton until the first answer', () => {
		render(TopCategoriesCard, { props: { report: null, status: 'loading', categories } });

		expect(document.querySelector('[data-slot="categories-skeleton"]')).not.toBeNull();
	});

	it('says when the first read failed and offers to try again', async () => {
		const onretry = vi.fn();
		render(TopCategoriesCard, {
			props: { report: null, status: 'error', categories, onretry }
		});

		expect(screen.getByText(/The categories could not be loaded/)).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalledOnce();
	});
});
