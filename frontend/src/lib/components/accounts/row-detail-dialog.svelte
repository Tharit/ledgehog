<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import Provenance from '#lib/components/ledger/provenance.svelte';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { bookingDocumentHref } from '#lib/accounts/booking.js';
	import type { Booking, Provenance as ProvenanceRow } from '#lib/types/domain.js';

	// A statement row's detail (ux/views/account.md), addressed by `?source=`: the provenance widget
	// (patterns §4.5) followed by the row's actions. Open in review is navigation to its unit, not
	// offered on a duplicate (which has no entry). An imported row can be marked as a duplicate, a
	// duplicate cleared; a row entered by hand is edited and deleted with the entry form's own
	// dialogs and never marked (spec §5.6). A booking is none of these: it follows its source, so it
	// offers "Open document" (or "Open charge" for a counter-leg) and nothing that changes it (§5.8).
	let {
		open,
		status,
		provenance,
		locale = 'en',
		timeZone = 'UTC',
		busy = false,
		booking = null,
		bookingAccountName = null,
		onclose,
		onclosefocus,
		onretry,
		onopenreview,
		onopencharge,
		onopenoriginal,
		onmark,
		onnotduplicate,
		onedit,
		ondelete
	}: {
		open: boolean;
		status: 'idle' | 'loading' | 'ready' | 'missing' | 'error';
		provenance: ProvenanceRow | null;
		locale?: string;
		timeZone?: string;
		/** "Not a duplicate" is being written */
		busy?: boolean;
		/** the row is a booking (the statement row says so): where it came from */
		booking?: Booking | null;
		/** the account a transfer booking's charge is on, by name */
		bookingAccountName?: string | null;
		onclose: () => void;
		/**
		 * Focus is about to return to what had it (a click focused the statement's list): the page
		 * places it itself, with `preventScroll`, since the default would scroll the list into view.
		 */
		onclosefocus?: (event: Event) => void;
		onretry?: () => void;
		onopenreview?: (entryId: number) => void;
		/** "Open charge": the charge a counter-leg booking was made from, in review */
		onopencharge?: (entryId: number) => void;
		onopenoriginal?: (sourceId: number) => void;
		onmark?: () => void;
		onnotduplicate?: () => void;
		onedit?: () => void;
		ondelete?: () => void;
	} = $props();

	const isDuplicate = $derived(provenance?.duplicate_of != null);
</script>

<Dialog.Root {open} onOpenChange={(next) => !next && !busy && onclose()}>
	<Dialog.Content
		class="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-xl"
		data-slot="row-detail"
		onCloseAutoFocus={(event) => onclosefocus?.(event)}
	>
		<Dialog.Header>
			<Dialog.Title>Source transaction</Dialog.Title>
			<Dialog.Description>What this account's source said about this row.</Dialog.Description>
		</Dialog.Header>

		<div
			class="-mx-1 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1 text-sm"
			data-slot="dialog-body"
		>
			{#if status === 'loading' || status === 'idle'}
				<p class="text-muted-foreground">Loading the row…</p>
			{:else if status === 'missing'}
				<Notice role="alert">This row no longer exists.</Notice>
			{:else if status === 'error'}
				<Notice role="alert">
					The row could not be loaded.
					{#snippet action()}
						<ActionButton variant="link" class="h-auto p-0" onclick={onretry}
							>Try again</ActionButton
						>
					{/snippet}
				</Notice>
			{:else if provenance}
				<Provenance
					{provenance}
					{locale}
					{timeZone}
					{booking}
					{bookingAccountName}
					{onopenoriginal}
				/>
			{/if}
		</div>

		<Dialog.Footer class="sm:flex-wrap">
			<ActionButton variant="outline" disabled={busy} onclick={onclose}>Close</ActionButton>
			{#if status === 'ready' && provenance}
				{#if booking}
					{@const href = bookingDocumentHref(booking)}
					{#if href}
						<ActionButton variant="outline" {href}>Open document</ActionButton>
					{:else}
						<ActionButton variant="outline" onclick={() => onopencharge?.(booking.id)}>
							Open charge
						</ActionButton>
					{/if}
				{:else if provenance.authored}
					<ActionButton variant="outline" onclick={onedit}>Edit</ActionButton>
					<ActionButton variant="outline" onclick={ondelete}>Delete…</ActionButton>
				{:else if isDuplicate}
					<ActionButton variant="outline" {busy} busyLabel="Clearing…" onclick={onnotduplicate}>
						Not a duplicate
					</ActionButton>
				{:else}
					<ActionButton variant="outline" onclick={onmark}>Mark as duplicate of…</ActionButton>
				{/if}
				{#if provenance.entry_id !== null}
					{@const entryId = provenance.entry_id}
					<ActionButton onclick={() => onopenreview?.(entryId)}>Open in review</ActionButton>
				{/if}
			{/if}
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
