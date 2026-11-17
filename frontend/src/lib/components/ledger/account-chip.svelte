<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { cn } from '#lib/utils.js';
	import FilterChip from './filter-chip.svelte';
	import type { ChipOption } from './options-chip.svelte';

	// The account chip carries two dimensions: the accounts of the entries, and, for transfers, the
	// account on the other side. The counter-account list stays folded until one is selected.
	let {
		label,
		options,
		account,
		counter,
		onchange
	}: {
		label: string;
		options: readonly ChipOption<number>[];
		account: readonly number[];
		counter: readonly number[];
		onchange: (patch: { account_id?: number[]; counter_account_id?: number[] }) => void;
	} = $props();

	let query = $state('');
	let expanded = $state(false);
	const open = $derived(expanded || counter.length > 0);
	const searchable = $derived(options.length > 8);
	const shown = $derived(
		query.trim() === ''
			? options
			: options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()))
	);

	function toggle(
		key: 'account_id' | 'counter_account_id',
		selected: readonly number[],
		value: number,
		checked: boolean
	) {
		const rest = selected.filter((v) => v !== value);
		onchange({ [key]: checked ? [...rest, value] : rest });
	}
</script>

{#snippet list(name: string, key: 'account_id' | 'counter_account_id', selected: readonly number[])}
	<ul class="-mx-1 max-h-48 overflow-y-auto" aria-label={name}>
		{#each shown as option (option.value)}
			<li>
				<label class="flex h-8 items-center gap-2 rounded-md px-1.5 text-[13px] hover:bg-row-hover">
					<input
						type="checkbox"
						class="size-4 shrink-0 accent-primary"
						checked={selected.includes(option.value)}
						onchange={(event) => toggle(key, selected, option.value, event.currentTarget.checked)}
					/>
					<DimensionIcon icon={option.icon} color={option.color} initial={option.initial} />
					<span class="truncate">{option.label}</span>
				</label>
			</li>
		{:else}
			<li class="px-1.5 py-2 text-sm text-muted-foreground">No match</li>
		{/each}
	</ul>
{/snippet}

<FilterChip {label} active={account.length > 0 || counter.length > 0}>
	<div class="flex items-center justify-between">
		<span class="text-xs font-medium text-muted-foreground">Account</span>
		{#if account.length > 0 || counter.length > 0}
			<Button
				variant="ghost"
				size="xs"
				onclick={() => onchange({ account_id: [], counter_account_id: [] })}
			>
				Clear
			</Button>
		{/if}
	</div>
	{#if searchable}
		<Input type="search" placeholder="Search…" aria-label="Search accounts" bind:value={query} />
	{/if}
	{#if options.length === 0}
		<p class="py-2 text-sm text-muted-foreground">No accounts yet</p>
	{:else}
		{@render list('Account', 'account_id', account)}
		<div class="mt-1 flex flex-col gap-0.5 border-t border-border pt-2">
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="-mx-1 flex items-center gap-1 rounded-md px-1 text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:hover:text-muted-foreground"
					aria-expanded={open}
					disabled={counter.length > 0}
					onclick={() => (expanded = !expanded)}
				>
					<ChevronRightIcon
						size={14}
						strokeWidth={1.75}
						class={cn('shrink-0 transition-transform', open && 'rotate-90')}
						aria-hidden="true"
					/>
					Counter-account
				</button>
				<span class="text-xs text-muted-foreground">transfers only</span>
			</div>
			{#if open}
				{@render list('Counter-account', 'counter_account_id', counter)}
			{/if}
		</div>
	{/if}
</FilterChip>
