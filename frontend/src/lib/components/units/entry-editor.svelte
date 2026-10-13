<script lang="ts">
	import AbsentValue from '#lib/components/common/absent-value.svelte';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import Field from '#lib/components/common/field.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import TagChip from '#lib/components/common/tag-chip.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { formatMoney } from '#lib/format/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { resolveAccount, resolveTag } from '#lib/theme/resolve.js';
	import { allocationText, type FieldName, type FieldValue } from '#lib/units/draft.js';
	import type { UnitDraftFlow } from '#lib/units/unit-draft-flow.svelte.js';
	import type { ProblemText } from '#lib/units/problems.js';
	import type { UnitProblem } from '#lib/units/types.js';
	import { shownFor, type EntryView, type FieldView } from '#lib/units/view.js';
	import { cn } from '#lib/utils.js';
	import EvidenceLine from './evidence-line.svelte';
	import FieldPicker from './field-picker.svelte';

	// One entry of the unit under the draft (patterns §4.1, §5): its amount, then each derived value
	// with the basis it was derived on and "Reset to proposal", the type, the texts. A split shows
	// its original as the residual (whose amount the server computes) and its other rows with an
	// amount to type. Nothing is decided here: every change goes to the flow, whose preview says
	// what it implies.
	let {
		view,
		flow,
		lookups,
		problems = [],
		locale = 'en'
	}: {
		view: EntryView;
		flow: UnitDraftFlow;
		lookups: Lookups;
		/** the problems of the preview that name this entry */
		problems?: { problem: UnitProblem; text: ProblemText }[];
		locale?: string;
	} = $props();

	const account = $derived(lookups.accounts.get(view.accountId));
	const partner = $derived(view.stored?.partner ?? null);
	const partnerAccount = $derived(partner ? lookups.accounts.get(partner.account_id) : undefined);
	const tags = $derived(
		(view.row?.tag_ids ?? view.stored?.tag_ids ?? []).flatMap((id) => {
			const tag = lookups.tags.get(id);
			return tag ? [tag] : [];
		})
	);
	const isTransfer = $derived(view.type === 'transfer');
	// converting is for the entry that keeps the source: a split row is a flow (spec §5.9)
	const canConvert = $derived(!view.isNew && view.original);
	const invalid = (field: FieldName) =>
		problems.some((p) => p.problem.field === field || p.problem.field === `${field}_id`);
	const amountText = $derived(
		flow.amountTexts[view.id] ??
			(view.amount ? allocationText(view.amount.amount, view.amount.currency, locale) : '')
	);
	// the original of a split takes what the others leave: the server's figure, said in words
	const residualText = $derived(
		view.sourceAmount
			? `Residual: what the other entries leave of ${formatMoney(
					view.sourceAmount.amount,
					view.sourceAmount.currency,
					{ locale, showPlus: false }
				)}`
			: 'Residual: what the other entries leave'
	);
	const amountError = $derived(flow.amountErrors[view.id] ?? null);
	const required = $derived.by(() => {
		const found = problems.find((p) => p.problem.code === 'currency_rule');
		const value = found?.problem.detail.required;
		return typeof value === 'string' ? value : null;
	});

	function accountReason(id: number): string | undefined {
		if (id === view.accountId) return 'Own account';
		if (required && lookups.accounts.get(id)?.currency !== required) return `Needs ${required}`;
		return undefined;
	}

	function pick(field: FieldView, value: number | null) {
		flow.setField(view.id, field.name, value as FieldValue, shownFor(field, value));
	}

	let amountInput = $state<HTMLInputElement | null>(null);
	// a split row just added: the amount is what is typed next
	$effect(() => {
		if (flow.lastAddedSplit === view.id && amountInput) {
			amountInput.focus({ preventScroll: false });
			flow.lastAddedSplit = null;
		}
	});

	const TYPES = ['flow', 'transfer'] as const;

	function setType(next: 'flow' | 'transfer') {
		if (view.type !== next) flow.convert(view.id, view.type);
	}
</script>

{#snippet evidenceOf(field: FieldView)}
	<div class="flex flex-wrap items-baseline gap-x-3">
		<EvidenceLine evidence={field.evidence} />
		{#if field.canReset}
			<ActionButton
				variant="link"
				class="h-auto p-0 text-xs"
				onclick={() => flow.resetField(view.id, field.name)}
			>
				Reset to proposal
			</ActionButton>
		{/if}
	</div>
{/snippet}

<section
	aria-label={view.isNew ? 'New split entry' : `Entry ${view.id}`}
	class={cn(
		'flex flex-col gap-3 rounded-lg border bg-card p-4 text-[13px]',
		view.isNew && 'border-dashed'
	)}
	data-slot="entry-editor"
	data-entry-id={view.id}
	data-new={view.isNew || undefined}
>
	<div class="flex flex-wrap items-end gap-x-4 gap-y-2">
		{#if view.amountEditable}
			<div class="w-40" data-slot="amount-field">
				<Field label={view.isNew ? 'Amount of the new split' : 'Amount'} error={amountError}>
					{#snippet children(control)}
						<Input
							{...control}
							bind:ref={amountInput}
							value={amountText}
							inputmode="decimal"
							autocomplete="off"
							class="text-right tabular-nums"
							oninput={(event) => flow.setAmountText(view.id, event.currentTarget.value)}
						/>
					{/snippet}
				</Field>
			</div>
			<span class="pb-1.5 text-muted-foreground">{view.amount?.currency ?? ''}</span>
		{:else if view.amount}
			<div class="flex flex-col">
				<MoneyDisplay
					minor={view.amount.amount}
					currency={view.amount.currency}
					{locale}
					showCurrency
					class="text-lg font-semibold"
				/>
				{#if view.inSplit && view.original}
					<span class="text-xs text-muted-foreground" data-slot="residual">
						{residualText}
					</span>
				{/if}
			</div>
		{/if}
		{#if !view.isNew}
			<DateDisplay date={view.row?.booked_on ?? view.stored?.booked_on ?? ''} {locale} />
		{/if}
		{#if account}
			<AccountDot name={account.name} color={resolveAccount(account).color} />
		{/if}
		<span class="flex items-center gap-1">
			{#each view.flags as flag (flag)}<ReviewBadge {flag} />{/each}
		</span>
		{#if view.removable}
			<ActionButton
				variant="outline"
				class="ml-auto"
				onclick={() => flow.removeSplit(view.id)}
				aria-label={view.isNew ? 'Remove this split' : `Remove entry ${view.id} from the split`}
			>
				Remove split
			</ActionButton>
		{/if}
	</div>

	<dl class="grid grid-cols-[8rem_1fr] items-start gap-x-4 gap-y-2">
		{#if !view.isNew}
			<dt class="pt-1.5 text-muted-foreground">Type</dt>
			<dd class="min-w-0">
				<div role="group" aria-label="Type" class="inline-flex gap-1">
					{#each TYPES as kind (kind)}
						<ActionButton
							variant="outline"
							aria-pressed={view.type === kind}
							class={cn(view.type === kind && 'bg-accent')}
							disabled={!canConvert}
							reason="Only the original entry of a split can change its type"
							onclick={() => setType(kind)}
						>
							{kind === 'flow' ? 'Flow' : 'Transfer'}
						</ActionButton>
					{/each}
				</div>
				<EvidenceLine evidence={view.fields.type.evidence} />
			</dd>
		{/if}

		{#if isTransfer}
			<dt class="pt-1.5 text-muted-foreground">Counter account</dt>
			<dd class="min-w-0">
				<FieldPicker
					kind="counter_account"
					label="Counter account"
					value={typeof view.fields.counter_account.value === 'number'
						? view.fields.counter_account.value
						: null}
					{lookups}
					proposal={view.fields.counter_account.proposal}
					invalid={invalid('counter_account')}
					disabledReason={accountReason}
					onchange={(id) => pick(view.fields.counter_account, id)}
				/>
				{@render evidenceOf(view.fields.counter_account)}
			</dd>
			{#if partner}
				<dt class="text-muted-foreground">Partner leg</dt>
				<dd class="flex flex-wrap items-center gap-x-3" data-slot="partner">
					{#if partnerAccount}
						<AccountDot name={partnerAccount.name} color={resolveAccount(partnerAccount).color} />
					{/if}
					<DateDisplay date={partner.booked_on} {locale} />
					<MoneyDisplay
						minor={partner.amount.amount}
						currency={partner.amount.currency}
						{locale}
						showCurrency
						class="inline"
					/>
				</dd>
			{/if}
		{:else}
			<dt class="pt-1.5 text-muted-foreground">Category</dt>
			<dd class="min-w-0">
				<FieldPicker
					kind="category"
					label="Category"
					value={typeof view.fields.category.value === 'number' ? view.fields.category.value : null}
					{lookups}
					clearable
					proposal={view.fields.category.proposal}
					invalid={invalid('category')}
					onchange={(id) => pick(view.fields.category, id)}
				/>
				{@render evidenceOf(view.fields.category)}
			</dd>
			<dt class="pt-1.5 text-muted-foreground">Payee</dt>
			<dd class="min-w-0">
				<FieldPicker
					kind="payee"
					label="Payee"
					value={typeof view.fields.payee.value === 'number' ? view.fields.payee.value : null}
					{lookups}
					clearable
					proposal={view.fields.payee.proposal}
					invalid={invalid('payee')}
					onchange={(id) => pick(view.fields.payee, id)}
				/>
				{@render evidenceOf(view.fields.payee)}
			</dd>
		{/if}

		<dt class="pt-1.5 text-muted-foreground">
			<label for={`description-${view.id}`}>Description</label>
		</dt>
		<dd class="min-w-0">
			<Input
				id={`description-${view.id}`}
				value={view.description ?? ''}
				autocomplete="off"
				oninput={(event) => flow.setText(view.id, 'description', event.currentTarget.value)}
			/>
		</dd>
		<dt class="pt-1.5 text-muted-foreground"><label for={`note-${view.id}`}>Note</label></dt>
		<dd class="min-w-0">
			<Input
				id={`note-${view.id}`}
				value={view.note ?? ''}
				autocomplete="off"
				oninput={(event) => flow.setText(view.id, 'note', event.currentTarget.value)}
			/>
		</dd>

		{#if !view.isNew}
			<dt class="text-muted-foreground">Tags</dt>
			<dd class="flex flex-wrap items-center gap-1">
				{#each tags as tag (tag.id)}
					<TagChip name={tag.name} color={resolveTag(tag).color} />
				{:else}
					<AbsentValue label="None" explanation="Tags are added from the ledger with t" />
				{/each}
				<span class="text-xs text-muted-foreground" data-slot="tags-note">
					Saved immediately, outside this draft
				</span>
			</dd>
		{/if}
	</dl>

	{#if view.original}
		<div>
			<ActionButton variant="outline" onclick={() => flow.addSplit(view.id)}>Add split</ActionButton
			>
		</div>
	{/if}
</section>
