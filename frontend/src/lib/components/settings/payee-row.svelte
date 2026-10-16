<script lang="ts">
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import RowActions, { type RowAction } from '#lib/components/common/row-actions.svelte';
	import { describeFailure } from '#lib/dimensions/errors.js';
	import type { PayeesStore } from '#lib/payees/store.svelte.js';
	import { PAYEE_ICONS } from '#lib/theme/icon-sets.js';
	import { resolvePayee } from '#lib/theme/resolve.js';
	import type { Payee } from '#lib/types/domain.js';
	import { cn } from '#lib/utils.js';
	import LookPicker from './look-picker.svelte';

	// One payee (comfortable density, design §5): its look (the initial stands in for a missing
	// icon, "default" says so when the look is not its own), name and note, with edit inline and
	// merge and delete in the `⋯` menu (patterns §11.3). Edit opens the manager's form dialog,
	// where the note and the document provider are edited; the provider is shown under the name.
	let {
		payee,
		store,
		revealed = false,
		focus = false,
		onedit
	}: {
		payee: Payee;
		store: PayeesStore;
		/** just added: marked briefly */
		revealed?: boolean;
		/** just added and the dialog has closed: take focus */
		focus?: boolean;
		onedit: () => void;
	} = $props();

	const look = $derived(resolvePayee(payee));
	const isDefault = $derived(look.icon === null && payee.color === null);

	let body = $state<HTMLElement | null>(null);

	$effect(() => {
		if (!focus || !body) return;
		body.scrollIntoView({ block: 'nearest' });
		body.focus();
	});

	async function changeLook(patch: { icon?: string | null; color?: string | null }) {
		const result = await store.update(payee.id, patch);
		if (!result.ok) store.notify(describeFailure(result.failure, 'payee'), true);
	}

	const primary = $derived<RowAction[]>([{ verb: 'Edit', icon: PencilIcon, onselect: onedit }]);
	const menu = $derived<RowAction[]>([
		{ verb: 'Merge…', onselect: () => store.merge.start(payee.id) },
		{ verb: 'Delete…', destructive: true, onselect: () => void store.remove.start(payee.id) }
	]);
</script>

<li data-slot="payee-row" data-payee-id={payee.id} data-revealed={revealed || undefined}>
	<div
		bind:this={body}
		tabindex="-1"
		class={cn(
			'group flex min-h-12 items-center gap-3 border-b border-border py-1 transition-colors duration-1000 outline-none focus-visible:ring-2 focus-visible:ring-ring',
			revealed && 'bg-accent'
		)}
	>
		<LookPicker
			name={payee.name}
			icon={payee.icon}
			color={payee.color}
			icons={PAYEE_ICONS}
			shownIcon={look.icon}
			shownColor={look.color}
			initial={look.initial}
			clearLabel="Default"
			onchange={changeLook}
		/>

		<div class="flex min-w-0 flex-1 flex-col">
			<span class="truncate text-sm font-medium">{payee.name}</span>
			<span class="truncate text-xs text-muted-foreground">
				{#if isDefault}<span data-slot="look-hint">default</span>{/if}
				{#if isDefault && payee.document_provider}·{/if}
				{#if payee.document_provider}
					<span data-slot="document-provider" title="The provider of this payee's documents"
						>Documents: {payee.document_provider}</span
					>
				{/if}
				{#if (isDefault || payee.document_provider) && payee.note}·{/if}
				{#if payee.note}<span data-slot="note">{payee.note}</span>{/if}
			</span>
		</div>

		<RowActions name={payee.name} {primary} {menu} />
	</div>
</li>
