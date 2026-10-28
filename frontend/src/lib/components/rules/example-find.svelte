<script lang="ts">
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { formatCount } from '#lib/format/index.js';
	import { selectable, type RuleExampleStore } from '#lib/stores/rule-example.svelte.js';

	// The find box of the example: type, the entries list answers (after a pause), ↑ ↓ move through
	// the results, Enter picks the highlighted one, Esc closes. A combobox with a listbox; the
	// header row names the columns and is not part of the list. Enter never submits the form.
	let { store, locale = 'en' }: { store: RuleExampleStore; locale?: string } = $props();

	const LISTBOX = 'rule-example-results';
	const optionId = (index: number) => `rule-example-option-${index}`;

	const showResults = $derived(store.open && store.searchText !== '');
	const active = $derived(
		showResults && store.findStatus === 'ready' && store.highlighted >= 0
			? optionId(store.highlighted)
			: undefined
	);

	function onkeydown(event: KeyboardEvent) {
		switch (event.key) {
			case 'ArrowDown':
			case 'ArrowUp':
				event.preventDefault();
				store.move(event.key === 'ArrowDown' ? 1 : -1);
				break;
			case 'Enter':
				// ⌘/Ctrl+Enter is the form's: it saves
				if (event.metaKey || event.ctrlKey) return;
				event.preventDefault();
				if (showResults) store.pick();
				break;
			case 'Escape':
				event.preventDefault();
				event.stopPropagation();
				store.escape();
				break;
		}
	}
</script>

<div class="flex flex-col gap-1">
	<label for="rule-example-find" class="text-xs font-medium">Find an entry</label>
	<Input
		id="rule-example-find"
		role="combobox"
		aria-expanded={showResults && store.findStatus === 'ready' && store.results.length > 0}
		aria-controls={LISTBOX}
		aria-autocomplete="list"
		aria-activedescendant={active}
		autocomplete="off"
		spellcheck={false}
		value={store.query}
		oninput={(event) => store.setQuery(event.currentTarget.value)}
		onfocus={() => {
			if (store.searchText !== '') store.open = true;
		}}
		{onkeydown}
	/>
	<p class="text-xs text-muted-foreground">
		Type part of a counterparty, purpose or booking text. ↑ ↓ to choose, Enter to pick, Esc to
		close.
	</p>

	{#if showResults}
		<div class="rounded-lg border" data-slot="example-results">
			{#if store.findStatus === 'loading'}
				<p class="px-3 py-2 text-sm text-muted-foreground" role="status">Searching…</p>
			{:else if store.findStatus === 'error'}
				<div class="flex items-center gap-3 px-3 py-2 text-sm" role="status">
					<span class="text-muted-foreground">The search failed.</span>
					<Button variant="outline" onclick={() => store.retry()}>Try again</Button>
				</div>
			{:else if store.findStatus === 'ready' && store.results.length === 0}
				<p class="px-3 py-2 text-sm text-muted-foreground" role="status">No entries match.</p>
			{:else if store.findStatus === 'ready'}
				<div class="max-h-72 overflow-auto">
					<div class="min-w-[36rem]">
						<div
							class="sticky top-0 grid grid-cols-[6rem_6rem_minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)] gap-x-3 border-b bg-muted px-3 py-1 text-xs font-medium text-muted-foreground"
							aria-hidden="true"
							data-slot="example-results-header"
						>
							<span>Booked</span>
							<span class="text-right">Amount</span>
							<span>Counterparty name</span>
							<span>Purpose</span>
							<span>Booking text</span>
						</div>
						<ul role="listbox" id={LISTBOX} aria-label="Entries found">
							{#each store.results as entry, index (entry.id)}
								{@const usable = selectable(entry)}
								<!-- the input keeps the focus and the keyboard; a click picks -->
								<!-- svelte-ignore a11y_click_events_have_key_events -->
								<li
									id={optionId(index)}
									role="option"
									aria-selected={index === store.highlighted}
									aria-disabled={usable ? undefined : true}
									data-entry-id={entry.id}
									class={[
										'grid grid-cols-[6rem_6rem_minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)] items-center gap-x-3 border-b border-border px-3 py-1 text-[13px] last:border-b-0',
										!usable && 'cursor-default',
										usable && (index === store.highlighted ? 'bg-accent' : 'hover:bg-row-hover')
									]}
									onmousedown={(event) => event.preventDefault()}
									onmousemove={() => {
										if (usable) store.highlighted = index;
									}}
									onclick={() => store.pick(entry)}
								>
									<DateDisplay date={entry.booked_on} {locale} />
									<MoneyDisplay
										minor={entry.amount.amount}
										currency={entry.amount.currency}
										{locale}
									/>
									{#if entry.source}
										<span class="truncate" title={entry.source.counterparty_name ?? undefined}>
											{entry.source.counterparty_name ?? ''}
										</span>
										<span class="truncate" title={entry.source.purpose ?? undefined}>
											{entry.source.purpose ?? ''}
										</span>
										<span class="truncate" title={entry.source.booking_text ?? undefined}>
											{entry.source.booking_text ?? ''}
										</span>
									{:else}
										<span class="col-span-3 truncate text-muted-foreground">
											No source transaction
										</span>
									{/if}
								</li>
							{/each}
						</ul>
					</div>
				</div>
				{#if store.total > store.results.length}
					<p class="border-t px-3 py-1 text-xs text-muted-foreground">
						Showing {formatCount(store.results.length, locale)} of {formatCount(
							store.total,
							locale
						)}; type more to narrow it down.
					</p>
				{/if}
			{/if}
		</div>
	{/if}
</div>
