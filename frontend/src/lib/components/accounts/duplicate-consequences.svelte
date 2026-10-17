<script lang="ts">
	import type { Preview } from '#lib/accounts/duplicate-flow.svelte.js';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { formatMoney } from '#lib/format/index.js';
	import type { Entry } from '#lib/types/domain.js';

	// What marking one row as a duplicate would do, as the consequence list of patterns §6: the
	// entries it deletes, the partners it unpairs and returns to review, the derived entries that
	// change, the documents it frees. The server's dry run is what is shown; the page itself still
	// shows no entry.
	let { preview, locale = 'en' }: { preview: Preview; locale?: string } = $props();

	const confirmed = (entry: Entry) => !entry.review_flags.includes('unconfirmed');
	const text = (entry: Entry) => entry.description ?? entry.display_text ?? '';
	const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

	function derivedLine(
		items: readonly {
			type: string;
			booked_on: string;
			amount: { amount: number; currency: string };
		}[]
	): string {
		return items.length === 0
			? 'none'
			: items
					.map((d) => `${d.type} ${formatMoney(d.amount.amount, d.amount.currency, { locale })}`)
					.join(', ');
	}
</script>

{#if preview.status === 'checking'}
	<p class="text-muted-foreground" data-slot="preview-checking">Checking what would change…</p>
{:else if preview.status === 'error'}
	<p class="text-destructive" role="alert" data-slot="preview-error">{preview.failure.text}</p>
{:else}
	{@const out = preview.out}
	{@const removedCount = out.removed_entry_ids.length}
	{@const allShown = preview.removed.length === removedCount}
	<div class="flex flex-col gap-1.5" data-slot="consequences">
		{#if removedCount > 0}
			<p class="font-medium">
				Deleted: {plural(removedCount, 'entry', 'entries')}{#if allShown}
					({preview.removed.filter(confirmed).length} confirmed){/if}
			</p>
			<ul class="flex flex-col">
				{#each preview.removed as entry (entry.id)}
					<li class="flex items-baseline gap-2 border-b border-border py-0.5 text-[13px]">
						<DateDisplay date={entry.booked_on} {locale} />
						<span class="min-w-0 flex-1 truncate">{text(entry)}</span>
						<span class="text-xs text-muted-foreground"
							>{confirmed(entry) ? 'confirmed' : 'in review'}</span
						>
						<MoneyDisplay
							minor={entry.amount.amount}
							currency={entry.amount.currency}
							{locale}
							class="w-24"
						/>
					</li>
				{/each}
			</ul>
		{:else}
			<p>Deletes no entry.</p>
		{/if}

		{#if out.partners.length > 0}
			<p class="mt-1 font-medium">
				Unpaired and returned to review: {plural(out.partners.length, 'entry', 'entries')}
			</p>
			<ul class="flex flex-col">
				{#each out.partners as entry (entry.id)}
					<li class="flex items-baseline gap-2 border-b border-border py-0.5 text-[13px]">
						<DateDisplay date={entry.booked_on} {locale} />
						<span class="min-w-0 flex-1 truncate">{text(entry)}</span>
						<MoneyDisplay
							minor={entry.amount.amount}
							currency={entry.amount.currency}
							{locale}
							class="w-24"
						/>
					</li>
				{/each}
			</ul>
		{/if}

		{#each out.derived_changes as change (change.account_id)}
			<p data-slot="derived-change">
				Derived entries change: {derivedLine(change.before)} → {derivedLine(change.after)}.
			</p>
		{/each}
		{#if out.freed_document_ids.length > 0}
			<p>Frees {plural(out.freed_document_ids.length, 'document', 'documents')}.</p>
		{/if}
		{#if out.repointed_source_ids.length > 0}
			<p>
				{plural(out.repointed_source_ids.length, 'row', 'rows')} that duplicated it will duplicate the
				other row instead.
			</p>
		{/if}
	</div>
{/if}
