<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { formatCount } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ConditionField } from '#lib/rules/conditions.js';
	import type { RulePreview, RulePreviewList, RulePreviewRow, RuleSets } from '#lib/rules/types.js';
	import RulePreviewTable from './rule-preview-table.svelte';

	type ListName = 'matches' | 'different_value' | 'lost_key';

	// What the rule would do, as the server computed it for the form as it stands (spec §5.9, the
	// consequence pattern of patterns §6): the result first, then the entries behind it. The three
	// lists hold the server's rows, capped; "show more" asks for the next ones. Counts are the
	// server's: "confirmed" is the matches minus the unconfirmed ones the server counted.
	let {
		preview,
		status,
		current,
		failure = null,
		retryable = false,
		rows,
		columns,
		moreBusy = null,
		sets,
		lookups,
		ruleName,
		locale = 'en',
		onmore,
		onretry
	}: {
		preview: RulePreview | null;
		status: 'idle' | 'loading' | 'ready' | 'error';
		/** the preview is of the form as it stands; false while a new one is on its way */
		current: boolean;
		/** why there is no preview, in words */
		failure?: string | null;
		retryable?: boolean;
		/** the rows held per list: the first page and what "show more" added */
		rows: Record<ListName, readonly RulePreviewRow[]>;
		/** the source fields the previewed conditions read: the table's source columns */
		columns: readonly ConditionField[];
		moreBusy?: ListName | null;
		sets: RuleSets;
		lookups: Lookups;
		/** a rule's name by id, for the rule that takes precedence */
		ruleName: (id: number) => string | undefined;
		locale?: string;
		onmore?: (list: ListName) => void;
		onretry?: () => void;
	} = $props();

	const count = (n: number) => formatCount(n, locale);
	const noun = (n: number, one: string, many: string) => `${count(n)} ${n === 1 ? one : many}`;

	const unconfirmed = $derived(preview ? preview.would_confirm + preview.stay_in_review : 0);
	const confirmed = $derived(preview ? Math.max(0, preview.matches.total - unconfirmed) : 0);

	const LISTS: {
		name: Exclude<ListName, 'matches'>;
		title: string;
		note: string;
	}[] = [
		{
			name: 'different_value',
			title: 'Check by hand: hold a different value that settling leaves',
			note: 'Matched entries that hold another value than this rule sets, and that settling leaves as it is: confirmed ones, and values under a standing key. Nothing is changed in bulk.'
		},
		{
			name: 'lost_key',
			title: 'Carry this rule’s key but no longer match',
			note: 'Entries whose value says it came from this rule, which would not decide them now. They keep their value; check them one by one.'
		}
	];
</script>

{#snippet list(name: ListName, data: RulePreviewList, label: string)}
	{@const held = rows[name]}
	<RulePreviewTable rows={held} {columns} {sets} {lookups} {ruleName} {label} {locale} />
	{#if held.length < data.total}
		<div class="flex items-center gap-3 pt-2 text-xs text-muted-foreground">
			<span>Showing {count(held.length)} of {count(data.total)}</span>
			<Button variant="outline" disabled={moreBusy !== null} onclick={() => onmore?.(name)}>
				{moreBusy === name ? 'Loading…' : 'Show more'}
			</Button>
		</div>
	{/if}
{/snippet}

<section
	aria-label="Preview"
	aria-busy={status === 'loading'}
	class="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-5 shadow-card"
>
	<h2 class="text-base font-semibold">Preview</h2>

	{#if status === 'idle'}
		<p class="text-sm text-muted-foreground">
			Choose what the rule sets and add a condition to see what it would do. Nothing is saved until
			you press Save rule.
		</p>
	{:else if status === 'error'}
		<div class="flex flex-col items-start gap-2 text-sm" role="status">
			<p class="text-muted-foreground">{failure ?? 'There is no preview for this rule yet.'}</p>
			{#if retryable}
				<Button variant="outline" onclick={onretry}>Try again</Button>
			{/if}
		</div>
	{:else if !preview}
		<p class="text-sm text-muted-foreground" role="status">Checking what would change…</p>
	{:else}
		<div class={current ? 'flex flex-col gap-4' : 'flex flex-col gap-4 opacity-60'}>
			{#if !current}
				<p class="text-xs text-muted-foreground" role="status">Updating for your last change…</p>
			{/if}

			<div class="flex flex-col gap-1" data-slot="preview-result">
				<p class="text-base font-semibold">
					{#if preview.matches.total === 0}
						Matches no entries
					{:else}
						Matches {noun(preview.matches.total, 'entry', 'entries')} ({count(unconfirmed)} unconfirmed,
						{count(confirmed)} confirmed)
					{/if}
				</p>
				{#if unconfirmed > 0}
					<p class="text-sm">
						Would confirm {noun(preview.would_confirm, 'entry', 'entries')},
						{count(preview.stay_in_review)}
						{preview.stay_in_review === 1 ? 'stays' : 'stay'} in review
					</p>
				{:else if preview.matches.total > 0}
					<p class="text-sm text-muted-foreground">
						Nothing to confirm: every match is confirmed already.
					</p>
				{/if}
			</div>

			{#if preview.matches.total > 0}
				<div class="flex flex-col" data-slot="preview-matches">
					{@render list('matches', preview.matches, 'Matched entries')}
				</div>
			{/if}

			{#each LISTS as item (item.name)}
				{@const data = preview[item.name]}
				<details class="rounded-lg border px-3 py-2" data-slot={`preview-${item.name}`}>
					<summary class="text-sm font-medium">
						{item.title} ({count(data.total)})
					</summary>
					<div class="mt-2 flex flex-col gap-2">
						<p class="text-xs text-muted-foreground">{item.note}</p>
						{#if data.total === 0}
							<p class="text-xs text-muted-foreground">None.</p>
						{:else}
							{@render list(item.name, data, item.title)}
						{/if}
					</div>
				</details>
			{/each}
		</div>
	{/if}
</section>
