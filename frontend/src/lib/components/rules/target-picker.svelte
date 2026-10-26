<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import Picker from '#lib/components/common/picker.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { RuleSets } from '#lib/rules/types.js';
	import { kindWord, targetOptions } from '#lib/rules/targets.js';
	import { cn } from '#lib/utils.js';
	import RuleTarget from './rule-target.svelte';

	// Find a category, payee or account in a searchable list (the shared picker in a popover).
	// Adding one is not done here: the list says where to (Settings).
	let {
		kind,
		value,
		lookups,
		label,
		id,
		clearable = false,
		invalid = false,
		noun,
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
		/** what the list holds, in words, where it is not the kind's own ("account" for a condition) */
		noun?: string;
		onchange: (id: number | null) => void;
	} = $props();

	let open = $state(false);

	const options = $derived(targetOptions(kind, lookups, value));
	const word = $derived(noun ?? kindWord(kind));
	const article = $derived(/^[aeiou]/i.test(word) ? 'an' : 'a');
	const chooseLabel = $derived(`Choose ${article} ${word}`);
	const manage = $derived(
		kind === 'category'
			? { href: '/settings/categories', text: 'Manage categories' }
			: kind === 'payee'
				? { href: '/settings/payees', text: 'Manage payees' }
				: null
	);

	function choose(next: number) {
		open = false;
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
				'flex h-8 min-w-0 flex-1 items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive',
				value === null && 'text-muted-foreground'
			)}
		>
			{#if value === null}
				<span>Choose {article} {word}…</span>
			{:else}
				<RuleTarget sets={kind} id={value} {lookups} full />
			{/if}
			<ChevronsUpDownIcon size={14} strokeWidth={1.75} class="shrink-0 text-muted-foreground" />
		</Popover.Trigger>
		<Popover.Content align="start" class="w-80 gap-0 p-1" aria-label={chooseLabel}>
			<Picker
				items={options}
				selectedId={value}
				label="Choices"
				findLabel={`Search ${word}`}
				placeholder={`Find ${article} ${word}…`}
				emptyText={`No ${word} yet.`}
				onselect={choose}
			>
				{#snippet row(option)}
					<RuleTarget sets={kind} id={option.id} {lookups} full />
				{/snippet}
			</Picker>
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
		<IconButton verb="Clear" label={`Clear the ${word}`} onclick={() => onchange(null)}>
			<XIcon aria-hidden="true" />
		</IconButton>
	{/if}
</div>
