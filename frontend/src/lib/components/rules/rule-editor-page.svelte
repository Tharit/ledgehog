<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { RULES_PATH } from '#lib/rules/links.js';
	import { describeRuleError, doneUrl } from '#lib/rules/messages.js';
	import { sourceColumns } from '#lib/rules/preview.js';
	import { RuleDeleteFlow } from '#lib/stores/rule-delete.svelte.js';
	import { RuleEditorStore, type SaveResult } from '#lib/stores/rule-editor.svelte.js';
	import { RuleExampleStore } from '#lib/stores/rule-example.svelte.js';
	import LeaveGuard from './leave-guard.svelte';
	import RuleDeleteDialog from './rule-delete-dialog.svelte';
	import RuleExample from './rule-example.svelte';
	import RuleForm from './rule-form.svelte';
	import RulePreview from './rule-preview.svelte';

	// The rule editor: the form on one side, the server's preview of it on the other (stacked on a
	// narrow screen). Add (`ruleId` null) or change a stored rule. The example is an entry to look
	// at while writing the conditions; `exampleId` opens the page with one and `onexample` reports
	// each change of it (the route puts it in the address). Leaving, after a save or a delete, is
	// the route's business (`onleave`, with the address to go to).
	let {
		ruleId = null,
		exampleId = null,
		onleave,
		onexample
	}: {
		ruleId?: number | null;
		exampleId?: number | null;
		onleave: (url: string) => void;
		onexample?: (id: number | null) => void;
	} = $props();

	// the editor is made once per page: the route keys it by what it edits
	const make = () => new RuleEditorStore({ ruleId });
	const makeExample = () =>
		new RuleExampleStore({ initialId: exampleId, onchange: (id) => onexample?.(id) });
	const store = make();
	const exampleStore = makeExample();
	// the way out after a save or a delete is not a discard
	let leaving = $state(false);
	const leave = (url: string) => {
		leaving = true;
		onleave(url);
	};
	const remove = new RuleDeleteFlow({
		locale: () => store.locale,
		deleted: (rule, breakdown, settleFailed) =>
			leave(doneUrl({ action: 'deleted', name: rule.name, breakdown, settleFailed })),
		gone: () => leave(RULES_PATH)
	});

	onMount(() => {
		void store.init();
		void exampleStore.init();
	});
	onDestroy(() => {
		store.dispose();
		exampleStore.dispose();
		remove.close();
	});

	async function save() {
		const result: SaveResult | null = await store.save();
		if (result) {
			leave(
				doneUrl({
					action: 'saved',
					name: result.rule.name,
					breakdown: result.breakdown,
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
	const columns = $derived(sourceColumns(store.previewedConditions));
	const title = $derived(store.editing ? (store.rule?.name ?? 'Rule') : 'Add rule');
	const description = $derived(
		store.editing
			? 'Change what this rule matches and what it sets; the preview shows what it would do.'
			: 'Say which entries it matches and what it sets; the preview shows what it would do before anything is saved.'
	);
	// the line holds one notice: the editor's own, with the lists that did not load after it
	const notice = $derived.by(() => {
		const lists =
			store.lookupsFailed.length > 0
				? `Some lists could not be loaded (${store.lookupsFailed.join(', ')}); their names may be missing below.`
				: null;
		if (store.notice) {
			return {
				text: lists ? `${store.notice.text} ${lists}` : store.notice.text,
				error: store.notice.error
			};
		}
		return lists ? { text: lists, error: false } : null;
	});
</script>

<LeaveGuard dirty={store.dirty && !leaving} />

<div class="flex flex-col gap-4">
	<a
		href={RULES_PATH}
		class="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground underline-offset-2 hover:underline"
	>
		<ArrowLeftIcon size={14} strokeWidth={1.75} aria-hidden="true" />
		All rules
	</a>
	<PageHeader {title} {description} />

	<NoticeLine {notice} />

	{#if store.loadStatus === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading…</p>
	{:else if store.loadStatus === 'missing'}
		<ErrorState
			title="This rule does not exist"
			message="It may have been deleted. Rules that were deleted show “rule deleted” where they decided an entry."
		/>
		<ActionButton variant="outline" href={RULES_PATH} class="w-fit">Back to the rules</ActionButton>
	{:else if store.loadStatus === 'error'}
		<ErrorState
			title="The rule could not be loaded"
			message={store.loadError ? describeRuleError(store.loadError, store.locale) : ''}
			onretry={() => store.init()}
		/>
	{:else}
		{@const stored = store.rule}
		<div class="grid items-start gap-4 xl:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
			<RuleForm
				form={store.form}
				lookups={store.lookups}
				errors={store.fieldErrors}
				editing={store.editing}
				saveBlocked={store.saveBlocked}
				saving={store.saving}
				onedit={(patch, now) => store.edit(patch, now)}
				oncondition={(index, patch) => store.editCondition(index, patch)}
				onaddcondition={() => store.addCondition()}
				onremovecondition={(index) => store.removeCondition(index)}
				onsave={save}
				ondelete={stored ? () => remove.start(stored) : undefined}
			>
				{#snippet example()}
					<RuleExample store={exampleStore} lookups={store.lookups} locale={store.locale} />
				{/snippet}
			</RuleForm>
			<RulePreview
				preview={store.preview}
				status={store.previewStatus}
				current={store.previewCurrent}
				{failure}
				{retryable}
				{rows}
				{columns}
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
