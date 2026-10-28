<script lang="ts">
	import Segmented from '#lib/components/common/segmented.svelte';
	import DateChip from '#lib/components/ledger/date-chip.svelte';
	import OptionsChip, { type ChipOption } from '#lib/components/ledger/options-chip.svelte';
	import { formatDateRange } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import {
		defaultRange,
		STEPS,
		type ReportId,
		type ReportParams,
		type TimeMode
	} from '#lib/reports/params.js';
	import type { Kind, Step } from '#lib/reports/shapes.js';
	import { resolveAccount, resolveTag } from '#lib/theme/resolve.js';

	// The controls shared by the reports (reports.md): the period (the ledger's date chip with its
	// presets), the ledger's own account and tag filters, and what belongs to one report: the kind,
	// the step, the mode. None keeps a state: each change goes up and comes back through the address.
	let {
		report,
		params,
		lookups,
		today,
		locale = 'en',
		filters = true,
		kind = false,
		step = false,
		mode = false,
		onchange
	}: {
		report: ReportId;
		params: ReportParams;
		lookups: Lookups;
		today: string;
		locale?: string;
		/** the account and tag filters (not on Balances: it is of every account) */
		filters?: boolean;
		/** Expense or Income */
		kind?: boolean;
		step?: boolean;
		mode?: boolean;
		onchange: (patch: Partial<ReportParams>) => void;
	} = $props();

	const accountOptions = $derived<ChipOption<number>[]>(
		[...lookups.accounts.values()]
			.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
			.map((a) => ({ value: a.id, label: a.name, ...resolveAccount(a) }))
	);
	const tagOptions = $derived<ChipOption<number>[]>(
		[...lookups.tags.values()]
			.sort((a, b) => a.name.localeCompare(b.name))
			.map((t) => ({ value: t.id, label: t.name, tag: true, color: resolveTag(t).color }))
	);

	function named(
		ids: readonly number[],
		names: ReadonlyMap<number, { name: string }>,
		all: string,
		many: string
	) {
		if (ids.length === 0) return all;
		if (ids.length === 1) return names.get(ids[0])?.name ?? all;
		return `${ids.length} ${many}`;
	}

	const KINDS: { value: Kind; label: string }[] = [
		{ value: 'expense', label: 'Expense' },
		{ value: 'income', label: 'Income' }
	];
	const MODES: { value: TimeMode; label: string }[] = [
		{ value: 'income-expense', label: 'Income and expense' },
		{ value: 'category', label: 'By category' }
	];
</script>

<div class="flex flex-wrap items-center gap-3" role="group" aria-label="Report controls">
	<DateChip
		label={formatDateRange(params.from, params.to, locale)}
		from={params.from}
		to={params.to}
		{today}
		{locale}
		onchange={(from, to) => {
			// a cleared period is the report's own default
			const fallback = defaultRange(report, today);
			onchange({ from: from ?? fallback.from, to: to ?? fallback.to });
		}}
	/>
	{#if filters}
		<OptionsChip
			label={named(params.accountIds, lookups.accounts, 'All accounts', 'accounts')}
			heading="Accounts"
			options={accountOptions}
			selected={params.accountIds}
			emptyText="No accounts yet"
			onchange={(accountIds) => onchange({ accountIds })}
		/>
		<OptionsChip
			label={named(params.tagIds, lookups.tags, 'Tags', 'tags')}
			heading="Tags"
			options={tagOptions}
			selected={params.tagIds}
			emptyText="No tags yet"
			onchange={(tagIds) => onchange({ tagIds })}
		/>
	{/if}
	{#if mode}
		<Segmented
			label="Mode"
			options={MODES}
			value={params.mode}
			onchange={(value) => onchange({ mode: value })}
		/>
	{/if}
	{#if kind}
		<Segmented
			label="Kind"
			options={KINDS}
			value={params.kind}
			onchange={(value) => onchange({ kind: value })}
		/>
	{/if}
	{#if step}
		<Segmented
			label="Step"
			options={STEPS.map((s) => ({ value: s.step, label: s.label }))}
			value={params.step}
			onchange={(value: Step) => onchange({ step: value })}
		/>
	{/if}
</div>
