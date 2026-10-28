<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import LineFigure from '#lib/components/reports/line-figure.svelte';
	import { formatMonthName } from '#lib/format/index.js';
	import { byCategoryHref, ledgerHref } from '#lib/reports/figures.js';
	import type { ByCategory, Line } from '#lib/reports/types.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import { resolveCategory } from '#lib/theme/resolve.js';
	import type { Category } from '#lib/types/domain.js';
	import ListCard from './list-card.svelte';

	// The five largest top-level expense categories of the month so far as bars in their resolved
	// colours, then "Other" in stone, then the unclassified amount out beneath (design §8). The
	// answer is the By category report's with `top`, so the card and the report cannot disagree. A
	// row opens the ledger filtered by the category and the month; the header opens the report.
	let {
		report,
		status,
		categories,
		locale = 'en',
		onretry
	}: {
		report: ByCategory | null;
		status: 'loading' | 'ready' | 'error';
		categories: ReadonlyMap<number, Category>;
		locale?: string;
		onretry?: () => void;
	} = $props();

	type Bar = { key: string; name: string; line: Line; color: string; href?: string; icon: string };

	const bars = $derived.by((): Bar[] => {
		if (!report) return [];
		const rows: Bar[] = (report.slices ?? []).map((slice) => {
			const category = categories.get(slice.category_id);
			const look = resolveCategory(category, categories);
			return {
				key: String(slice.category_id),
				name: category?.name ?? 'Category',
				line: slice.total,
				color: look.color,
				icon: look.icon,
				href: ledgerHref({ category_id: [slice.category_id], from: report.from, to: report.to })
			};
		});
		if (report.other) {
			rows.push({
				key: 'other',
				name: 'Other',
				line: report.other,
				color: 'stone',
				icon: 'circle-ellipsis'
			});
		}
		return rows;
	});

	// bars are relative to the largest magnitude shown; an amount that cannot be valued has none
	const magnitude = (line: Line) => Math.abs(line.total?.amount ?? 0);
	const widest = $derived(Math.max(1, ...bars.map((bar) => magnitude(bar.line))));
	const width = (line: Line) => `${(magnitude(line) / widest) * 100}%`;

	const unclassified = $derived(
		report && report.unclassified_out.count > 0
			? {
					line: report.unclassified_out,
					href: ledgerHref({
						from: report.from,
						to: report.to,
						uncategorised: true,
						direction: 'out'
					})
				}
			: null
	);
</script>

<ListCard
	title={report
		? `Top expense categories, ${formatMonthName(report.from, locale)} so far`
		: 'Top expense categories'}
	linkLabel="By category"
	href={report ? byCategoryHref(report.from, report.to) : undefined}
>
	{#if status === 'loading'}
		<div class="h-32 animate-pulse rounded-md bg-muted" data-slot="categories-skeleton"></div>
	{:else if status === 'error' && !report}
		<p class="text-sm text-muted-foreground">
			The categories could not be loaded.
			{#if onretry}
				<button type="button" class="font-medium text-primary hover:underline" onclick={onretry}>
					Try again
				</button>
			{/if}
		</p>
	{:else if bars.length === 0 && !unclassified}
		<p class="text-sm text-muted-foreground">Nothing spent this month yet.</p>
	{:else}
		<ul class="flex flex-col gap-1" data-slot="category-bars">
			{#each bars as bar (bar.key)}
				<li data-category={bar.key}>
					<svelte:element
						this={bar.href ? 'a' : 'div'}
						href={bar.href}
						class="flex min-h-12 items-center gap-3 rounded-sm px-1 text-sm outline-none hover:bg-row-hover focus-visible:ring-2 focus-visible:ring-ring"
					>
						<DimensionIcon icon={bar.icon} color={bar.color} size="comfortable" />
						<span class="w-28 shrink-0 truncate font-medium">{bar.name}</span>
						<span class="h-2 min-w-0 flex-1" aria-hidden="true">
							<span
								class="block h-2 rounded-full"
								data-color={bar.color}
								style:width={width(bar.line)}
								style:background-color={dimensionVars(bar.color).fg}
							></span>
						</span>
						<span class="shrink-0 text-right"><LineFigure line={bar.line} {locale} /></span>
					</svelte:element>
				</li>
			{/each}
		</ul>
		{#if unclassified}
			<a
				href={unclassified.href}
				class="flex items-baseline justify-between gap-3 border-t border-border px-1 pt-3 text-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
				data-slot="unclassified-out"
			>
				<AbsentValue
					label="Unclassified"
					explanation="Money out that has no category yet, so it is in no bar above."
				/>
				<LineFigure line={unclassified.line} {locale} />
			</a>
		{/if}
	{/if}
</ListCard>
