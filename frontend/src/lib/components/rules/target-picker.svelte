<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import * as Command from '#lib/components/ui/command/index.js';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { RuleSets } from '#lib/rules/types.js';
	import { filterOptions, kindWord, targetOptions } from '#lib/rules/targets.js';
	import { cn } from '#lib/utils.js';
	import RuleTarget from './rule-target.svelte';

	// Find a category, payee or account in a searchable list (the same popover and list as the tag
	// chooser). Creating one is not done here: the list says where to (Settings).
	let {
		kind,
		value,
		lookups,
		label,
		id,
		clearable = false,
		invalid = false,
		onchange
	}: {
		kind: RuleSets;
		value: number | null;
		lookups: Lookups;
		/** the accessible name of the button */
		label: string;
		id?: string;
		clearable?: boolean;
		invalid?: boolean;
		onchange: (id: number | null) => void;
	} = $props();

	let open = $state(false);
	let query = $state('');

	const options = $derived(targetOptions(kind, lookups, value));
	const shown = $derived(filterOptions(options, query));
	const manage = $derived(
		kind === 'category'
			? { href: '/settings/categories', text: 'Manage categories' }
			: kind === 'payee'
				? { href: '/settings/payees', text: 'Manage payees' }
				: null
	);

	function choose(next: number) {
		open = false;
		query = '';
		onchange(next);
	}
</script>

<div class="flex items-center gap-1">
	<Popover.Root bind:open>
		<Popover.Trigger
			{id}
			aria-label={label}
			aria-invalid={invalid || undefined}
			class={cn(
				'flex h-8 min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive',
				value === null && 'text-muted-foreground'
			)}
		>
			{#if value === null}
				<span>Choose a {kindWord(kind)}…</span>
			{:else}
				<RuleTarget sets={kind} id={value} {lookups} full />
			{/if}
			<ChevronsUpDownIcon size={14} strokeWidth={1.75} class="shrink-0 text-muted-foreground" />
		</Popover.Trigger>
		<Popover.Content align="start" class="w-80 gap-0 p-1" aria-label={`Choose a ${kindWord(kind)}`}>
			<Command.Root shouldFilter={false}>
				<Command.Input aria-label={`Search ${kindWord(kind)}`} bind:value={query} />
				<Command.List aria-label="Choices">
					{#each shown as option (option.id)}
						<Command.Item
							value={`target-${option.id}`}
							data-checked={option.id === value}
							onSelect={() => choose(option.id)}
						>
							<RuleTarget sets={kind} id={option.id} {lookups} full />
						</Command.Item>
					{/each}
					{#if shown.length === 0}
						<p class="px-2 py-6 text-center text-sm text-muted-foreground">
							{options.length === 0 ? `No ${kindWord(kind)} yet.` : `No ${kindWord(kind)} matches.`}
						</p>
					{/if}
				</Command.List>
			</Command.Root>
			{#if manage}
				<a
					href={manage.href}
					target="_blank"
					rel="noopener"
					class="border-t px-2 pt-2 pb-1 text-xs text-muted-foreground underline-offset-2 hover:underline"
				>
					Not there? {manage.text} (opens in a new tab)
				</a>
			{/if}
		</Popover.Content>
	</Popover.Root>
	{#if clearable && value !== null}
		<button
			type="button"
			class="inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-muted"
			aria-label={`Clear the ${kindWord(kind)}`}
			title="Clear"
			onclick={() => onchange(null)}
		>
			<XIcon size={16} strokeWidth={1.75} aria-hidden="true" />
		</button>
	{/if}
</div>
