<script lang="ts">
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { formatCount } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import {
		DERIVED_NOTICE,
		describeUnitLoadError,
		NO_REVIEW_TEXT,
		NO_REVIEW_TITLE,
		sourceGroups,
		stateText,
		unitTitle
	} from '#lib/units/describe.js';
	import { PANEL_GEOMETRY } from '#lib/units/geometry.js';
	import type { UnitPanel } from '#lib/units/panel.svelte.js';
	import { cn } from '#lib/utils.js';
	import EntryBlock from './entry-block.svelte';
	import SourceStrip from './source-strip.svelte';

	// The work panel (patterns §4.1, §5, §11.1): a large overlay for ONE unit, open while the
	// address says `?unit=`. This wave it is read-only: the unit as the server holds it, every
	// value with its basis. Focus starts on the panel itself, not a field, so `[` and `]` work at
	// once; Esc, the close button and a click on the dimmed list close it, and focus goes back to
	// the list it came from. The geometry is one constant (units/geometry.ts).
	let {
		panel,
		lookups,
		locale = 'en'
	}: { panel: UnitPanel; lookups: Lookups; locale?: string } = $props();

	let content = $state<HTMLElement | null>(null);
	let helpOpen = $state(false);
	$effect(() => {
		if (!panel.isOpen) helpOpen = false;
	});
	// the keys of the panel; the editing keys (c y s x r) join when editing lands
	const HELP: HelpGroup[] = [
		{
			title: 'Panel',
			items: [
				{ keys: '[', description: 'Previous unit' },
				{ keys: ']', description: 'Next unit' },
				{ keys: 'Esc', description: 'Close this help, then the panel' },
				{ keys: '?', description: 'Show or hide this help' }
			]
		}
	];

	// The click or Enter that opened the panel must not count as a click outside it, whatever the
	// order the browser delivers it in: outside clicks are ignored for a moment after opening.
	let openedAt = 0;
	$effect(() => {
		if (panel.isOpen) openedAt = performance.now();
	});
	function ignoreEarlyOutside(event: Event) {
		if (performance.now() - openedAt < 300) event.preventDefault();
	}

	const unit = $derived(panel.unit);
	const title = $derived(
		panel.status === 'missing'
			? NO_REVIEW_TITLE
			: unit
				? unitTitle(unit, lookups)
				: panel.status === 'error'
					? 'Unit'
					: 'Loading…'
	);
	const groups = $derived(unit ? sourceGroups(unit.entries) : []);
	const failure = $derived(
		panel.error ? describeUnitLoadError(panel.error.code, 'The unit') : null
	);

	// keys of the panel act when focus is not in a field (patterns §5); c y s x r come with editing
	const FIELD = 'input, textarea, select, [contenteditable]';

	function onkeydown(event: KeyboardEvent) {
		if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
		if (event.target instanceof Element && event.target.closest(FIELD)) return;
		if (event.key === '[' || event.key === ']') {
			event.preventDefault();
			panel.step(event.key === ']' ? 1 : -1);
		}
	}

	function openAutoFocus(event: Event) {
		event.preventDefault();
		content?.focus({ preventScroll: true });
	}

	function closeAutoFocus(event: Event) {
		const target = panel.focusTarget();
		if (!target) return;
		event.preventDefault();
		target.focus({ preventScroll: true });
	}
</script>

<Dialog.Root
	open={panel.isOpen}
	onOpenChange={(next) => {
		if (!next) panel.close();
	}}
>
	<Dialog.Content
		bind:ref={content}
		tabindex={-1}
		class={cn(PANEL_GEOMETRY, 'grid-rows-[auto_1fr_auto] gap-3 p-5')}
		data-slot="unit-panel"
		{onkeydown}
		onInteractOutside={ignoreEarlyOutside}
		onOpenAutoFocus={openAutoFocus}
		onCloseAutoFocus={closeAutoFocus}
	>
		<header class="flex flex-col gap-1 pr-10">
			<Dialog.Title class="text-lg leading-snug font-semibold">{title}</Dialog.Title>
			<Dialog.Description class="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
				{#if unit}
					<span data-slot="unit-state" data-confirmed={unit.state.confirmed || undefined}>
						{stateText(unit.state)}
					</span>
					{#if panel.position}
						<span data-slot="unit-position">
							{formatCount(panel.position.index, locale)} of {formatCount(
								panel.position.total,
								locale
							)}
						</span>
					{/if}
				{:else if panel.status === 'missing'}
					<span>Nothing to review here</span>
				{:else}
					<span>Unit {panel.unitId ?? ''}</span>
				{/if}
			</Dialog.Description>
		</header>

		<!-- stepping and loading are announced politely -->
		<div role="status" aria-live="polite" class="sr-only">{panel.announcement}</div>

		<div class="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1" data-slot="unit-body">
			{#if panel.status === 'loading' && !unit}
				{#each [0, 1] as n (n)}
					<div class="flex flex-col gap-3 rounded-lg border bg-card p-4" data-skeleton>
						<div class="h-5 w-40 animate-pulse rounded bg-muted"></div>
						<div class="h-3 w-2/3 animate-pulse rounded bg-muted"></div>
						<div class="h-3 w-1/2 animate-pulse rounded bg-muted"></div>
						<div class="h-3 w-3/5 animate-pulse rounded bg-muted"></div>
					</div>
				{/each}
			{:else if panel.status === 'missing'}
				<div
					class="flex flex-col items-start gap-3 rounded-xl border bg-card p-5"
					data-slot="no-review"
				>
					<h3 class="text-base font-semibold">{NO_REVIEW_TITLE}</h3>
					<p class="max-w-prose text-sm text-muted-foreground">{DERIVED_NOTICE}</p>
					<p class="max-w-prose text-sm text-muted-foreground">{NO_REVIEW_TEXT}</p>
					<ActionButton variant="outline" onclick={() => panel.close()}>Close</ActionButton>
				</div>
			{:else if panel.status === 'error' && failure}
				<ErrorState
					title={failure.title}
					message={failure.message}
					onretry={failure.retryable ? () => panel.retry() : undefined}
					class="max-w-none"
				/>
			{:else if unit}
				<div class={cn('flex flex-col gap-3', panel.status === 'loading' && 'opacity-60')}>
					<SourceStrip {groups} {locale} />
					{#each unit.entries as entry (entry.id)}
						<EntryBlock {entry} {lookups} rules={panel.rules} {locale} />
					{/each}
				</div>
			{/if}
		</div>

		<footer
			class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t pt-3 text-xs text-muted-foreground"
		>
			<div class="flex flex-wrap items-center gap-3" data-slot="panel-keys">
				<KeyboardHelp groups={HELP} bind:open={helpOpen} scope="panel" />
				{#if panel.stepNotice}<span class="italic">{panel.stepNotice}</span>{/if}
			</div>
			<ActionButton variant="outline" disabled reason="Editing arrives next">Commit</ActionButton>
		</footer>
	</Dialog.Content>
</Dialog.Root>
