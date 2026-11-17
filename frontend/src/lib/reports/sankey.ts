// The chart model of *By account* (reports.md, Tab 2; design §8): the answer as nodes in four
// fixed columns and the links between them, plain data a sankey draws, so the mapping is tested
// without a chart. Nothing here is laid out: the sizes come from the layout. A link is drawn only
// if its total is valued and of its side's sign; one of the other sign is named in a note, and
// every link of the answer stays in the table beside the chart.
import { measureLook } from '#lib/theme/measures.js';
import { resolveAccount, resolveCategory } from '#lib/theme/resolve.js';
import type { Account, Category } from '#lib/types/domain.js';
import { minorOf, OTHER_COLOR, OTHER_ICON } from './charts.js';
import {
	accountCategoryHref,
	accountReconciliationsHref,
	accountUnclassifiedHref,
	transferHref,
	unpairedHref,
	type Scope
} from './links.js';
import type { Kind } from './shapes.js';
import type { AccountLink, ByAccount, Line } from './types.js';

/** Income side, receiving accounts, paying accounts, expense side. */
export type SankeyColumn = 0 | 1 | 2 | 3;

export type LinkKind =
	'category' | 'other' | 'unclassified' | 'reconciliation' | 'transfer' | 'stayed';

/** Opacity of a link's colour (design §8): a band that stayed is fainter than the links. */
export const LINK_OPACITY = 0.35;
export const STAYED_OPACITY = 0.2;

export type SankeyNode = {
	key: string;
	column: SankeyColumn;
	label: string;
	/** dimension colour name and lead tile icon name */
	color: string;
	icon: string;
	/** an account is a wider block with its icon and name; the rest are slim bars */
	account: boolean;
	/** its place in its column, top to bottom: the layout keeps it */
	order: number;
};

export type SankeyLink = {
	key: string;
	/** node keys */
	source: string;
	target: string;
	/** the magnitude drawn, in minor units */
	value: number;
	kind: LinkKind;
	/** the tooltip's title: the category, "Other", "Unclassified", "Reconciliations", "Transfer" */
	label: string;
	/** the names of its two ends, in the direction of the money */
	from: string;
	to: string;
	/** dimension colour name of the band; its opacity is by `kind` */
	color: string;
	icon: string;
	/** signed as booked; null for the band that stayed (derived) */
	line: Line | null;
	/** none for the band that stayed */
	href: string | null;
	/** the stayed band only: the answer's own figures, in minor units: what the account received
	 *  on the income side, what it transferred out (signed as booked), and what stayed */
	stayed?: { received: number; transferredOut: number };
};

/** A link not drawn since its net is of the other sign. */
export type OppositeLink = { key: string; from: string; to: string; line: Line; href: string };

export type AccountSankey = {
	currency: string;
	nodes: SankeyNode[];
	links: SankeyLink[];
	notes: {
		opposite: OppositeLink[];
		/** the transfer legs not paired yet, with their ledger filter, when there are any */
		unpaired: { line: Line; href: string } | null;
	};
	/** the most nodes in one column: the chart's height grows with it */
	fullest: number;
};

/** "Unclassified" and "Reconciliations": the neutral nodes of a side, in the measures' stone. */
const UNCLASSIFIED = { label: 'Unclassified', ...measureLook('unclassified') };
const RECONCILIATIONS = { label: 'Reconciliations', ...measureLook('reconciliations') };
const OTHER = { label: 'Other', color: OTHER_COLOR, icon: OTHER_ICON };
const TRANSFER = { label: 'Transfer', ...measureLook('transfers') };

/** The sign of a side: income and the money kept are positive, expense and transfers negative. */
const SIDE_SIGN = { income: 1, expense: -1 } as const;

function signed(line: Line, sign: 1 | -1): 'drawn' | 'opposite' | 'none' {
	const minor = minorOf(line);
	if (minor === null || minor === 0) return 'none';
	return Math.sign(minor) === sign ? 'drawn' : 'opposite';
}

/**
 * The top-level categories of a kind that "Other" holds: those the slices leave out, unless
 * their net is of the other sign (refunds beyond purchases; they are in no slice and no "Other").
 */
export function otherCategoryIds(report: ByAccount, kind: Kind): number[] {
	const side = report[kind];
	const slices = new Set(side.slices ?? side.categories.map((c) => c.category_id));
	return side.categories
		.filter((c) => {
			if (slices.has(c.category_id)) return false;
			const minor = minorOf(c.total);
			return minor === null || Math.sign(minor) !== -SIDE_SIGN[kind];
		})
		.map((c) => c.category_id)
		.sort((a, b) => a - b);
}

type Draft = Omit<SankeyLink, 'source' | 'target' | 'key'> & {
	source: {
		column: SankeyColumn;
		id: string;
		account: boolean;
		label: string;
		color: string;
		icon: string;
	};
	target: {
		column: SankeyColumn;
		id: string;
		account: boolean;
		label: string;
		color: string;
		icon: string;
	};
};

export function accountSankey(
	report: ByAccount,
	categories: ReadonlyMap<number, Category>,
	accounts: ReadonlyMap<number, Account>,
	scope: Scope
): AccountSankey {
	const drafts: Draft[] = [];
	const opposite: OppositeLink[] = [];

	const accountEnd = (id: number, column: 1 | 2) => {
		const account = accounts.get(id);
		const look = account ? resolveAccount(account) : { icon: OTHER_ICON, color: OTHER_COLOR };
		return {
			column,
			id: `a${id}`,
			account: true,
			label: account?.name ?? 'Account',
			color: look.color,
			icon: look.icon
		};
	};
	const sideEnd = (
		column: 0 | 3,
		id: string,
		look: { label: string; color: string; icon: string }
	) => ({ column, id, account: false, ...look });
	const categoryLook = (id: number) => {
		const category = categories.get(id);
		const look = resolveCategory(category, categories);
		return { label: category?.name ?? 'Category', color: look.color, icon: look.icon };
	};

	// one link of the income or expense side, between a side node and an account
	function sideLink(
		side: Kind,
		kind: Exclude<LinkKind, 'transfer' | 'stayed'>,
		node: ReturnType<typeof sideEnd>,
		link: AccountLink,
		href: string,
		// the links of a category whose net is of the other sign are in no slice and not in "Other"
		excluded = false
	) {
		const account = accountEnd(link.account_id, side === 'income' ? 1 : 2);
		const [source, target] = side === 'income' ? [node, account] : [account, node];
		let state = signed(link.line, SIDE_SIGN[side]);
		if (excluded && state !== 'none') state = 'opposite';
		if (state === 'opposite') {
			opposite.push({
				key: `${source.id}:${source.column}>${target.id}:${target.column}`,
				from: source.label,
				to: target.label,
				line: link.line,
				href
			});
		}
		if (state !== 'drawn') return;
		drafts.push({
			source,
			target,
			value: Math.abs(minorOf(link.line) ?? 0),
			kind,
			label: node.label,
			from: source.label,
			to: target.label,
			color: node.color,
			icon: node.icon,
			line: link.line,
			href
		});
	}

	for (const side of ['income', 'expense'] as const) {
		const column = side === 'income' ? 0 : 3;
		const kinds = report[side];
		const byCategory = new Map(kinds.categories.map((c) => [c.category_id, c]));
		// without `top`, every category is a slice
		const slices = kinds.slices ?? kinds.categories.map((c) => c.category_id);
		for (const id of slices) {
			const row = byCategory.get(id);
			if (!row) continue;
			const node = sideEnd(column, `c${id}`, categoryLook(id));
			for (const link of row.accounts) {
				sideLink(side, 'category', node, link, accountCategoryHref(scope, link.account_id, [id]));
			}
		}
		const other = otherCategoryIds(report, side);
		const held = new Set([...slices, ...other]);
		for (const row of kinds.categories) {
			if (held.has(row.category_id)) continue;
			const node = sideEnd(column, `c${row.category_id}`, categoryLook(row.category_id));
			for (const link of row.accounts) {
				const href = accountCategoryHref(scope, link.account_id, [row.category_id]);
				sideLink(side, 'category', node, link, href, true);
			}
		}
		for (const link of kinds.other ?? []) {
			sideLink(
				side,
				'other',
				sideEnd(column, 'other', OTHER),
				link,
				accountCategoryHref(scope, link.account_id, other)
			);
		}
	}
	for (const link of report.unclassified_in.accounts) {
		sideLink(
			'income',
			'unclassified',
			sideEnd(0, 'unclassified', UNCLASSIFIED),
			link,
			accountUnclassifiedHref(scope, link.account_id, 'in')
		);
	}
	for (const link of report.unclassified_out.accounts) {
		sideLink(
			'expense',
			'unclassified',
			sideEnd(3, 'unclassified', UNCLASSIFIED),
			link,
			accountUnclassifiedHref(scope, link.account_id, 'out')
		);
	}
	// the net of an account's reconciliations is on the side of its sign: no link is of the other
	for (const link of report.reconciliations.accounts) {
		const side = (minorOf(link.line) ?? 0) < 0 ? 'expense' : 'income';
		sideLink(
			side,
			'reconciliation',
			sideEnd(side === 'income' ? 0 : 3, 'reconciliation', RECONCILIATIONS),
			link,
			accountReconciliationsHref(scope, link.account_id)
		);
	}

	// between the account columns: a transfer is a link between two accounts at its booked amount
	for (const transfer of report.transfers.flatMap((g) =>
		g.to.map((t) => ({
			from_account_id: g.from_account_id,
			to_account_id: t.account_id,
			line: t.line
		}))
	)) {
		if (transfer.from_account_id === transfer.to_account_id) continue;
		const from = accountEnd(transfer.from_account_id, 1);
		const to = accountEnd(transfer.to_account_id, 2);
		const href = transferHref(scope, transfer.from_account_id, transfer.to_account_id);
		const state = signed(transfer.line, -1);
		if (state === 'opposite') {
			opposite.push({
				key: `${from.id}:1>${to.id}:2`,
				from: from.label,
				to: to.label,
				line: transfer.line,
				href
			});
		}
		if (state !== 'drawn') continue;
		drafts.push({
			source: from,
			target: to,
			value: Math.abs(minorOf(transfer.line) ?? 0),
			kind: 'transfer',
			label: TRANSFER.label,
			from: from.label,
			to: to.label,
			color: OTHER_COLOR,
			icon: TRANSFER.icon,
			line: transfer.line,
			href
		});
	}

	// the income that stayed: the answer's `stayed`, whose tooltip has its components from the answer
	for (const stayed of report.stayed) {
		const from = accountEnd(stayed.account_id, 1);
		const to = accountEnd(stayed.account_id, 2);
		drafts.push({
			source: from,
			target: to,
			value: stayed.amount.amount,
			kind: 'stayed',
			label: `Stayed in ${from.label}`,
			from: from.label,
			to: to.label,
			color: OTHER_COLOR,
			icon: TRANSFER.icon,
			line: null,
			href: null,
			stayed: { received: stayed.received.amount, transferredOut: stayed.transferred_out.amount }
		});
	}

	// the nodes: the side columns in the order the answer gives (categories by magnitude, then
	// "Other", "Unclassified", "Reconciliations"), the accounts by the size of what passes through
	// `order` here is the first appearance; the node's own `order` is its place in its column
	const nodes = new Map<
		string,
		Omit<SankeyNode, 'order'> & { id: string; weight: number; order: number }
	>();
	const keyOf = (end: Draft['source']) => `${end.column}:${end.id}`;
	for (const draft of drafts) {
		for (const end of [draft.source, draft.target]) {
			const key = keyOf(end);
			const node = nodes.get(key) ?? {
				key,
				column: end.column,
				label: end.label,
				color: end.color,
				icon: end.icon,
				account: end.account,
				id: end.id,
				weight: 0,
				order: nodes.size
			};
			node.weight += draft.value;
			nodes.set(key, node);
		}
	}
	// an account weighs what passes through it in both columns, so it keeps its place in each
	const through = new Map<string, number>();
	for (const n of nodes.values()) {
		if (n.account) through.set(n.id, (through.get(n.id) ?? 0) + n.weight);
	}
	const weigh = (n: { id: string; account: boolean }) => (n.account ? (through.get(n.id) ?? 0) : 0);
	const sorted = [...nodes.values()].sort(
		(a, b) => a.column - b.column || weigh(b) - weigh(a) || a.order - b.order
	);
	const seen = [0, 0, 0, 0];
	const ordered = sorted.map((n) => ({ ...n, position: seen[n.column]++ }));
	const fullest = Math.max(
		0,
		...[0, 1, 2, 3].map((c) => ordered.filter((n) => n.column === c).length)
	);

	const links = drafts.map(({ source, target, ...rest }): SankeyLink => ({
		...rest,
		key: `${keyOf(source)}>${keyOf(target)}`,
		source: keyOf(source),
		target: keyOf(target)
	}));

	return {
		currency: report.base_currency,
		nodes: ordered.map((n) => ({
			key: n.key,
			column: n.column,
			label: n.label,
			color: n.color,
			icon: n.icon,
			account: n.account,
			order: n.position
		})),
		links,
		notes: {
			opposite,
			unpaired:
				report.unpaired.count > 0 ? { line: report.unpaired, href: unpairedHref(scope) } : null
		},
		fullest
	};
}

/**
 * What the layout needs to keep the columns where they are: the layer of each column in use
 * (a column nobody stands in leaves no gap), and, when no path of links runs through every column
 * in use, a zero-valued connection between the first nodes of neighbouring columns. The layout
 * numbers its layers by the longest path, so without a path through all of them the columns after
 * a gap would fold into the one before it. A connection draws nothing.
 */
export function layerPlan(model: Pick<AccountSankey, 'nodes' | 'links'>): {
	layers: Record<number, number>;
	spine: { source: string; target: string }[];
} {
	const used = [...new Set(model.nodes.map((n) => n.column))].sort((a, b) => a - b);
	const layers = Object.fromEntries(used.map((column, i) => [column, i]));
	// links run from a lower column to a higher one: the graph has no cycle
	const next = new Map<string, string[]>();
	for (const l of model.links) next.set(l.source, [...(next.get(l.source) ?? []), l.target]);
	const memo = new Map<string, number>();
	const length = (key: string): number => {
		const known = memo.get(key);
		if (known !== undefined) return known;
		const found = 1 + Math.max(0, ...(next.get(key) ?? []).map(length));
		memo.set(key, found);
		return found;
	};
	const longest = Math.max(0, ...model.nodes.map((n) => length(n.key)));
	const spine: { source: string; target: string }[] = [];
	if (longest < used.length) {
		const first = (column: number) => model.nodes.find((n) => n.column === column)!.key;
		for (let i = 1; i < used.length; i++) {
			spine.push({ source: first(used[i - 1]), target: first(used[i]) });
		}
	}
	return { layers, spine };
}
