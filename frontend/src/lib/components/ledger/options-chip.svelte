<script lang="ts" module>
	export type ChipOption<T extends string | number> = {
		value: T;
		label: string;
		/** a dimension colour name: shown as a dot before the label */
		color?: string;
		/** a longer explanation, as a tooltip */
		hint?: string;
		/** a review token: its badge (the one the rows show) is drawn before the label */
		flag?: string;
	};
</script>

<script lang="ts" generics="T extends string | number">
	import type { Snippet } from 'svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import FilterChip from './filter-chip.svelte';

	// A multi-select chip: a checkbox list (OR within the dimension) with a search box for long
	// lists and an optional footer for dimension-specific switches.
	let {
		label,
		heading,
		options,
		selected,
		active = selected.length > 0,
		searchable = options.length > 8,
		emptyText = 'Nothing to choose from yet',
		manageHref,
		onchange,
		footer
	}: {
		label: string;
		heading: string;
		options: readonly ChipOption<T>[];
		selected: readonly T[];
		active?: boolean;
		searchable?: boolean;
		emptyText?: string;
		/** where the dimension is managed (categories, payees): a "Manage…" link at the end */
		manageHref?: string;
		onchange: (selected: T[]) => void;
		footer?: Snippet;
	} = $props();

	let query = $state('');
	const shown = $derived(
		query.trim() === ''
			? options
			: options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()))
	);

	function toggle(value: T, checked: boolean) {
		const rest = selected.filter((v) => v !== value);
		onchange(checked ? [...rest, value] : rest);
	}
</script>

<FilterChip {label} {active}>
	<div class="flex items-center justify-between">
		<span class="text-xs font-medium text-muted-foreground">{heading}</span>
		{#if selected.length > 0}
			<Button variant="ghost" size="xs" onclick={() => onchange([])}>Clear</Button>
		{/if}
	</div>
	{#if searchable}
		<Input
			type="search"
			placeholder="Search…"
			aria-label={`Search ${heading.toLowerCase()}`}
			bind:value={query}
		/>
	{/if}
	{#if options.length === 0}
		<p class="py-2 text-sm text-muted-foreground">{emptyText}</p>
	{:else}
		<ul class="-mx-1 max-h-64 overflow-y-auto" aria-label={heading}>
			{#each shown as option (option.value)}
				<li>
					<label
						class="flex h-8 items-center gap-2 rounded-md px-1.5 text-[13px] hover:bg-muted"
						title={option.hint}
					>
						<input
							type="checkbox"
							class="size-4 shrink-0 accent-primary"
							checked={selected.includes(option.value)}
							onchange={(event) => toggle(option.value, event.currentTarget.checked)}
						/>
						{#if option.flag}
							<span aria-hidden="true" class="inline-flex"><ReviewBadge flag={option.flag} /></span>
						{/if}
						{#if option.color}
							<AccountDot name={option.label} color={option.color} />
						{:else}
							<span class="truncate">{option.label}</span>
						{/if}
					</label>
				</li>
			{:else}
				<li class="px-1.5 py-2 text-sm text-muted-foreground">No match</li>
			{/each}
		</ul>
	{/if}
	{@render footer?.()}
	{#if manageHref}
		<a
			href={manageHref}
			class="mt-1 border-t border-border pt-2 text-[13px] text-primary underline-offset-4 hover:underline"
		>
			Manage…
		</a>
	{/if}
</FilterChip>
