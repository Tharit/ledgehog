<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import RuleTarget from '#lib/components/rules/rule-target.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import Picker from '#lib/components/common/picker.svelte';
	import * as Popover from '#lib/components/ui/popover/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { kindWord, targetOptions } from '#lib/rules/targets.js';
	import type { RuleSets } from '#lib/rules/types.js';
	import { cn } from '#lib/utils.js';

	// One derived value of an entry chosen from a searchable list (the shared picker in a popover):
	// a category, a payee or a transfer's counter-account. Only existing things are offered; adding
	// one is done in Settings, or, where the caller gives `add` (accounts), in a dialog from here. The X is not a plain clear (see `clearable`). An item may be disabled with its reason (an account the currency
	// rule or the entry's own account rules out). A proposal is italic and muted.
	let {
		kind,
		value,
		lookups,
		label,
		proposal = false,
		invalid = false,
		clearable = false,
		emptyText,
		disabled = false,
		disabledReason,
		add,
		onchange
	}: {
		kind: RuleSets;
		value: number | null;
		lookups: Lookups;
		/** the accessible name of the button ("Category") */
		label: string;
		proposal?: boolean;
		invalid?: boolean;
		/** show the X: the payee's makes it empty, the others' means "remove my choice" */
		clearable?: boolean;
		/** what an empty field says instead of "Choose a …": the empty value of a field that may be empty ("No payee") */
		emptyText?: string;
		disabled?: boolean;
		/** why an item cannot be chosen */
		disabledReason?: (id: number) => string | undefined;
		/** an action under the list that adds the thing wanted (a dialog); `trigger` takes the focus back */
		add?: { label: string; run: (trigger: HTMLElement | null) => void };
		onchange: (id: number | null) => void;
	} = $props();

	let open = $state(false);
	let trigger = $state<HTMLElement | null>(null);

	const items = $derived(
		targetOptions(kind, lookups, value).map((option) => ({
			...option,
			disabled: disabledReason?.(option.id)
		}))
	);
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

<div class="flex items-center gap-1" data-slot="field-picker">
	<Popover.Root bind:open>
		<Popover.Trigger
			bind:ref={trigger}
			aria-label={label}
			aria-invalid={invalid || undefined}
			data-picker={kind}
			{disabled}
			class={cn(
				'flex h-8 min-w-0 flex-1 items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-2.5 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive',
				(value === null || proposal) && 'text-muted-foreground'
			)}
		>
			<span
				class={cn('flex min-w-0', proposal && 'italic')}
				data-proposal={(proposal && value !== null) || undefined}
			>
				{#if value === null}
					<span>{emptyText ?? `Choose a ${kindWord(kind)}…`}</span>
				{:else}
					<RuleTarget sets={kind} id={value} {lookups} full />
				{/if}
			</span>
			<ChevronsUpDownIcon size={14} strokeWidth={1.75} class="shrink-0 text-muted-foreground" />
		</Popover.Trigger>
		<Popover.Content align="start" class="w-80 gap-0 p-1" aria-label={`Choose a ${kindWord(kind)}`}>
			<Picker
				{items}
				selectedId={value}
				label="Choices"
				findLabel={`Search ${kindWord(kind)}`}
				placeholder={`Find a ${kindWord(kind)}…`}
				emptyText={`No ${kindWord(kind)} yet.`}
				onselect={choose}
			>
				{#snippet row(option)}
					<RuleTarget sets={kind} id={option.id} {lookups} full />
				{/snippet}
			</Picker>
			{#if add}
				<div class="border-t px-1 pt-1">
					<ActionButton
						variant="link"
						class="h-auto justify-start p-1 text-xs"
						data-slot="picker-add"
						onclick={() => {
							open = false;
							add.run(trigger);
						}}
					>
						{add.label}
					</ActionButton>
				</div>
			{:else if manage}
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
	{#if clearable && value !== null && !disabled}
		<IconButton
			verb={kind === 'payee' ? 'Clear payee' : 'Remove my choice'}
			label={kind === 'payee' ? 'Clear payee' : `Remove my choice of ${kindWord(kind)}`}
			onclick={() => onchange(null)}
		>
			<XIcon aria-hidden="true" />
		</IconButton>
	{/if}
</div>
