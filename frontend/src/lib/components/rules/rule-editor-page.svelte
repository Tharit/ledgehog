<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { RULES_PATH } from '#lib/rules/links.js';
	import { describeRuleError, doneUrl } from '#lib/rules/messages.js';
	import type { FromEntry } from '#lib/rules/prefill.js';
	import { RuleDeleteFlow } from '#lib/stores/rule-delete.svelte.js';
	import { RuleEditorStore, type SaveResult } from '#lib/stores/rule-editor.svelte.js';
	import RuleDeleteDialog from './rule-delete-dialog.svelte';
	import RuleForm from './rule-form.svelte';
	import RulePreview from './rule-preview.svelte';

	// The rule editor: the form on one side, the server's preview of it on the other (stacked on a
	// narrow screen). New (`ruleId` null, optionally from an entry) or a stored rule. Leaving, after
	// a save or a delete, is the route's business (`onleave`, with the address to go to).
	let {
		ruleId = null,
		from = null,
		onleave
	}: { ruleId?: number | null; from?: FromEntry | null; onleave: (url: string) => void } = $props();

	// the editor is made once per page: the route keys it by what it edits
	const make = () => new RuleEditorStore({ ruleId, from });
	const store = make();
	const remove = new RuleDeleteFlow({
		locale: () => store.locale,
		deleted: (rule, touched, settleFailed) =>
			onleave(doneUrl({ action: 'deleted', name: rule.name, touched, settleFailed })),
		gone: () => onleave(RULES_PATH)
	});

	onMount(() => void store.init());
	onDestroy(() => {
		store.dispose();
		remove.close();
	});

	async function save() {
		const result: SaveResult | null = await store.save();
		if (result) {
			onleave(
				doneUrl({
					action: 'saved',
					name: result.rule.name,
					touched: result.touched,
					settleFailed: result.settleFailed
				})
			);
		}
	}

	const failure = $derived(store.error ? describeRuleError(store.error, store.locale) : null);
	const retryable = $derived(store.error?.kind === 'network' || store.error?.kind === 'other');
	const rows = $derived({
		matches: store.rowsOf('matches'),
		different_value: store.rowsOf('different_value'),
		lost_key: store.rowsOf('lost_key')
	});
	const title = $derived(
		store.editing ? (store.rule?.name ?? 'Rule') : from ? 'New rule from an entry' : 'New rule'
	);
</script>

<div class="flex flex-col gap-4">
	<a
		href={RULES_PATH}
		class="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground underline-offset-2 hover:underline"
	>
		<ArrowLeftIcon size={14} strokeWidth={1.75} aria-hidden="true" />
		All rules
	</a>
	<h2 class="text-xl font-semibold">{title}</h2>

	<!-- one reserved line, so a notice appearing never moves the form (patterns §7) -->
	<div class="flex min-h-5 flex-col gap-1">
		{#if store.notice}
			<Notice role={store.notice.error ? 'alert' : 'status'}>{store.notice.text}</Notice>
		{/if}
		{#if store.lookupsFailed.length > 0}
			<Notice>
				Some lists could not be loaded ({store.lookupsFailed.join(', ')}); their names may be
				missing below.
			</Notice>
		{/if}
	</div>

	{#if store.loadStatus === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading…</p>
	{:else if store.loadStatus === 'missing'}
		<ErrorState
			title="This rule does not exist"
			message="It may have been deleted. Rules that were deleted show “rule deleted” where they decided an entry."
		/>
		<Button variant="outline" href={RULES_PATH} class="w-fit">Back to the rules</Button>
	{:else if store.loadStatus === 'error'}
		<ErrorState
			title="The rule could not be loaded"
			message={store.loadError ? describeRuleError(store.loadError, store.locale) : ''}
			onretry={() => store.init()}
		/>
	{:else}
		{@const stored = store.rule}
		<div class="grid items-start gap-4 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
			<RuleForm
				form={store.form}
				suggestions={store.suggestions}
				lookups={store.lookups}
				errors={store.fieldErrors}
				editing={store.editing}
				saveBlocked={store.saveBlocked}
				saving={store.saving}
				onedit={(patch, now) => store.edit(patch, now)}
				onsave={save}
				ondelete={stored ? () => remove.start(stored) : undefined}
			/>
			<RulePreview
				preview={store.preview}
				status={store.previewStatus}
				current={store.previewCurrent}
				{failure}
				{retryable}
				{rows}
				moreBusy={store.moreBusy}
				sets={store.form.sets}
				lookups={store.lookups}
				ruleName={(id) => store.ruleName(id)}
				locale={store.locale}
				onmore={(name) => store.more(name)}
				onretry={() => store.refreshPreview()}
			/>
		</div>
	{/if}
</div>

<RuleDeleteDialog flow={remove} locale={store.locale} />
