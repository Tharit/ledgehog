<script lang="ts">
	import { tick, untrack } from 'svelte';
	import EllipsisIcon from '@lucide/svelte/icons/ellipsis';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import ActionDialog from '#lib/components/common/action-dialog.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import KeyboardHelp, { type HelpGroup } from '#lib/components/common/keyboard-help.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';
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
	import { groupsOf, partnerDirections } from '#lib/units/groups.js';
	import { entryViews, type EntryView } from '#lib/units/view.js';
	import { cn } from '#lib/utils.js';
	import CounterLegBlock from './counter-leg-block.svelte';
	import EntryEditor from './entry-editor.svelte';
	import PreviewRegion from './preview-region.svelte';
	import SourceStrip from './source-strip.svelte';

	// The work panel (patterns §4.1, §5, §6, §11.1): a large overlay for ONE unit, open while the
	// address says `?unit=`. It edits the unit as a draft: values with their basis, splits, a
	// transfer's destination, re-resolve; a live preview says what a commit would do, and ⌘/Ctrl+↵
	// commits it and moves on to the next unit. Focus starts on the panel itself, not a field, so
	// the panel's keys work at once. A draft with changes asks before it is lost (Esc, Cancel, the
	// close button, a click on the dimmed list, stepping, a consequence row). Editing or deleting
	// a user-authored entry is the entry form's: the host wires `onEditEntry` and `onDeleteEntry`.
	let {
		panel,
		lookups,
		locale = 'en',
		onEditEntry,
		onDeleteEntry
	}: {
		panel: UnitPanel;
		lookups: Lookups;
		locale?: string;
		/** "Edit entry" of a user-authored transaction (the entry form's dialog) */
		onEditEntry?: (entryId: number) => void;
		/** "Delete entry…" of a user-authored transaction */
		onDeleteEntry?: (entryId: number) => void;
	} = $props();

	const flow = $derived(panel.flow);

	let content = $state<HTMLElement | null>(null);
	let helpOpen = $state(false);
	$effect(() => {
		if (!panel.isOpen) helpOpen = false;
	});
	const HELP: HelpGroup[] = [
		{
			title: 'Panel',
			items: [
				{ keys: '[', description: 'Previous unit' },
				{ keys: ']', description: 'Next unit' },
				{ keys: 'Ctrl/⌘ Enter', description: 'Commit, then the next unit' },
				{ keys: 'Esc', description: 'Close this help, then the panel' },
				{ keys: '?', description: 'Show or hide this help' }
			]
		},
		{
			title: 'Editing',
			items: [
				{ keys: 'c', description: 'Category' },
				{ keys: 'y', description: 'Payee' },
				{ keys: 't', description: 'Tags' },
				{ keys: 's', description: 'Split entry' },
				{ keys: 'p', description: 'Partner of a transfer' },
				{ keys: 'x', description: 'Toggle flow ↔ transfer' },
				{ keys: 'r', description: 'Re-resolve type, payee, category and counter account' }
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
	const views = $derived<EntryView[]>(
		unit && flow.draft
			? entryViews({
					unit,
					draft: flow.draft,
					preview: flow.preview,
					rules: panel.rules,
					locale,
					stale: flow.stale,
					accountName: (id) => lookups.accounts.get(id)?.name
				})
			: []
	);
	const problemTexts = $derived(flow.problemTexts);
	// one group per source transaction: its blocks, with "Split entry" at its foot. A unit of one
	// source keeps the plain layout (the strip on top, no header)
	const panelGroups = $derived(unit ? groupsOf(views, unit.entries) : []);
	const multi = $derived(panelGroups.length > 1);
	// where each leg's partner is shown, for the hint in its partner row
	const directions = $derived(partnerDirections(panelGroups));
	const reason = $derived(flow.commitReason);
	// a user-authored transaction is edited and deleted through the entry form
	const authored = $derived(unit?.entries.find((e) => e.authored) ?? null);
	const dirtyReason = 'Commit or discard your changes first';

	// keys of the panel act when focus is not in a field (patterns §5)
	const FIELD = 'input, textarea, select, [contenteditable]';

	function editorOf(target: EventTarget | null): HTMLElement | null {
		const near =
			target instanceof Element ? target.closest<HTMLElement>('[data-slot="entry-editor"]') : null;
		return (
			near ??
			content?.querySelector<HTMLElement>('[data-slot="entry-editor"]:not([data-new])') ??
			null
		);
	}

	function viewOf(editor: HTMLElement | null): EntryView | undefined {
		return editor ? views.find((v) => String(v.id) === editor.dataset.entryId) : undefined;
	}

	function openPicker(editor: HTMLElement | null, kind: string) {
		editor?.querySelector<HTMLElement>(`[data-picker="${kind}"]`)?.click();
	}

	function split(editor: HTMLElement | null) {
		const view = viewOf(editor);
		if (!view || !flow.draft) return;
		const source = view.isNew
			? flow.draft.splits.find((s) => s.id === view.id)?.sourceEntryId
			: view.id;
		if (source !== undefined) flow.addSplit(source);
	}

	async function convert(editor: HTMLElement | null) {
		const view = viewOf(editor);
		if (!view || view.isNew || !view.original) return;
		const toTransfer = view.type !== 'transfer';
		flow.convert(view.id, view.type);
		// its destination is what is chosen next
		if (toTransfer) {
			await tick();
			openPicker(editor, 'counter_account');
		}
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.defaultPrevented) return;
		// the commit chord works from anywhere in the panel, a field included; Enter alone never does
		if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
			event.preventDefault();
			void flow.commit();
			return;
		}
		if (event.ctrlKey || event.metaKey || event.altKey) return;
		if (event.target instanceof Element && event.target.closest(FIELD)) return;
		const editor = () => editorOf(event.target);
		switch (event.key) {
			case '[':
			case ']':
				event.preventDefault();
				panel.step(event.key === ']' ? 1 : -1);
				break;
			case 'c':
				event.preventDefault();
				openPicker(editor(), 'category');
				break;
			case 'y':
				event.preventDefault();
				openPicker(editor(), 'payee');
				break;
			case 't':
				event.preventDefault();
				openPicker(editor(), 'tags');
				break;
			case 'p': {
				// the focused leg's partner list, else the first one the panel has
				const near = editor()?.querySelector<HTMLElement>('[data-picker="partner"]');
				const any = content?.querySelector<HTMLElement>('[data-picker="partner"]');
				if (near ?? any) {
					event.preventDefault();
					(near ?? any)!.click();
				}
				break;
			}
			case 's':
				event.preventDefault();
				split(editor());
				break;
			case 'x':
				event.preventDefault();
				void convert(editor());
				break;
			case 'r':
				event.preventDefault();
				flow.reresolve(true);
				break;
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

	// back on the panel itself: after advancing, after "keep editing"
	$effect(() => {
		void panel.focusToken;
		untrack(() => content?.focus({ preventScroll: true }));
	});
</script>

<!-- controlled: the panel's store decides whether it is open. A click outside, Esc and the close
     button only ask to close (`panel.close()`: with changes, a decision dialog first), so the dialog
     never closes under a store that still says open -->
<Dialog.Root
	bind:open={
		() => panel.isOpen,
		(next) => {
			if (!next) panel.close();
		}
	}
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
		<header class="flex items-start gap-2 pr-10">
			<div class="flex min-w-0 flex-1 flex-col gap-1">
				<Dialog.Title class="text-lg leading-snug font-semibold">{title}</Dialog.Title>
				<Dialog.Description
					class="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground"
				>
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
			</div>
			{#if unit}
				<DropdownMenu.Root>
					<DropdownMenu.Trigger>
						{#snippet child({ props })}
							<IconButton
								tooltip={false}
								verb="More actions"
								label="More actions for this unit"
								{...props}
							>
								<EllipsisIcon aria-hidden="true" />
							</IconButton>
						{/snippet}
					</DropdownMenu.Trigger>
					<DropdownMenu.Content align="end" class="min-w-52">
						<DropdownMenu.Item disabled={flow.committing} onSelect={() => flow.reresolve(true)}>
							Re-resolve
							<DropdownMenu.Shortcut>r</DropdownMenu.Shortcut>
						</DropdownMenu.Item>
						<DropdownMenu.Item
							disabled={!flow.isDirty || flow.committing}
							onSelect={() => flow.discard()}
						>
							Reset
						</DropdownMenu.Item>
						{#if authored && (onEditEntry || onDeleteEntry)}
							<DropdownMenu.Separator />
						{/if}
						{#if authored && onEditEntry}
							<DropdownMenu.Item
								disabled={flow.isDirty}
								title={flow.isDirty ? dirtyReason : undefined}
								onSelect={() => onEditEntry(authored.id)}
							>
								<span class="flex flex-col">
									Edit entry
									{#if flow.isDirty}
										<span class="text-xs text-muted-foreground">{dirtyReason}</span>
									{/if}
								</span>
							</DropdownMenu.Item>
						{/if}
						{#if authored && onDeleteEntry}
							<DropdownMenu.Item
								variant="destructive"
								disabled={flow.isDirty}
								title={flow.isDirty ? dirtyReason : undefined}
								onSelect={() => onDeleteEntry(authored.id)}
							>
								<span class="flex flex-col">
									Delete entry…
									{#if flow.isDirty}
										<span class="text-xs text-muted-foreground">{dirtyReason}</span>
									{/if}
								</span>
							</DropdownMenu.Item>
						{/if}
					</DropdownMenu.Content>
				</DropdownMenu.Root>
			{/if}
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
					{#if !multi}
						<SourceStrip {groups} {locale} />
					{/if}
					{#if flow.draft?.reresolveAll}
						<p class="text-sm text-muted-foreground" data-slot="reresolved">
							Re-resolved: type, payee, category and counter account are what resolution proposes
							now. Reset discards all changes.
						</p>
					{/if}
					{#each panelGroups as group, index (group.key)}
						<div
							class={cn('flex flex-col gap-3', group.ghost && 'opacity-80')}
							data-slot="source-group"
							data-ghost={group.ghost ? '' : undefined}
						>
							{#if multi}
								{@const account = lookups.accounts.get(group.header.accountId)}
								<!-- a divider band: it starts the section of one source -->
								<div
									class={cn(
										'flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 border-b border-border bg-muted px-3 py-2 text-sm font-semibold',
										index > 0 && 'border-t'
									)}
									data-slot="group-header"
								>
									<span class="flex flex-wrap items-center gap-x-2">
										{#if account}
											<AccountDot name={account.name} color={resolveAccount(account).color} />
										{:else}
											Account {group.header.accountId}
										{/if}
										{#if group.ghost}
											<span aria-hidden="true" class="font-normal text-muted-foreground">·</span>
											<span class="font-normal text-muted-foreground" data-slot="ghost-hint"
												>created when you commit</span
											>
										{/if}
									</span>
								</div>
							{/if}
							<div
								class={cn('flex flex-col gap-3', multi && 'border-l border-border pl-3')}
								data-slot="group-content"
							>
								{#if multi && group.strip}
									<SourceStrip groups={[group.strip]} {locale} />
								{/if}
								{#each group.views as view (view.id)}
									{#if group.ghost}
										<CounterLegBlock {view} ghost={group.ghost} {lookups} {locale} />
									{:else}
										<EntryEditor
											{view}
											{flow}
											{lookups}
											{locale}
											partnerDirection={directions.get(view.id) ?? null}
											problems={problemTexts.filter((item) => item.problem.entry_id === view.id)}
										/>
									{/if}
								{/each}
								{#if group.splitEntryId !== null}
									{@const splitEntryId = group.splitEntryId}
									<ActionButton
										variant="outline"
										class="w-full border-dashed"
										disabled={flow.committing}
										onclick={() => flow.addSplit(splitEntryId)}
									>
										Split entry
									</ActionButton>
								{/if}
							</div>
						</div>
					{/each}
					<PreviewRegion
						{flow}
						{lookups}
						{locale}
						grouped={multi}
						onopen={(id) => panel.openEntry(id)}
					/>
				</div>
			{/if}
		</div>

		<footer class="flex flex-col gap-2 border-t pt-3 text-xs text-muted-foreground">
			{#if flow.notice}
				{@const notice = flow.notice}
				<Notice role={notice.kind === 'error' ? 'alert' : 'status'}>
					{notice.text}
					{#snippet action()}
						{#if notice.action}
							<ActionButton variant="link" class="h-auto p-0" onclick={notice.action.run}>
								{notice.action.label}
							</ActionButton>
						{/if}
					{/snippet}
				</Notice>
			{/if}
			<div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
				<div class="flex flex-wrap items-center gap-3" data-slot="panel-keys">
					<KeyboardHelp groups={HELP} bind:open={helpOpen} scope="panel" />
					{#if panel.stepNotice}<span class="italic">{panel.stepNotice}</span>{/if}
				</div>
				<div class="flex items-center gap-2">
					<ActionButton
						variant="outline"
						disabled={!flow.isDirty || flow.committing}
						reason={flow.committing ? undefined : 'Nothing to reset'}
						onclick={() => flow.discard()}
					>
						Reset
					</ActionButton>
					<ActionButton variant="outline" disabled={flow.committing} onclick={() => panel.close()}>
						Cancel
					</ActionButton>
					<ActionButton
						busy={flow.committing}
						busyLabel="Committing…"
						disabled={reason !== null}
						reason={reason ?? undefined}
						aria-keyshortcuts="Control+Enter Meta+Enter"
						onclick={() => flow.commit()}
					>
						Commit
					</ActionButton>
				</div>
			</div>
		</footer>
	</Dialog.Content>
</Dialog.Root>

<!-- a draft with changes asks before it is lost: Cancel is focused, Enter never confirms -->
<ActionDialog
	open={panel.leave !== null}
	mode="decision"
	destructive
	title="Discard changes?"
	verb="Discard"
	width="sm"
	onclose={() => panel.cancelLeave()}
	onsubmit={() => panel.confirmLeave()}
	oncloseautofocus={(event) => {
		event.preventDefault();
		content?.focus({ preventScroll: true });
	}}
>
	<p class="text-muted-foreground">
		The changes to this unit have not been committed. Discarding them leaves the unit as it is.
	</p>
</ActionDialog>
