<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import AccountDot from '#lib/components/common/account-dot.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import DateDisplay from '#lib/components/common/date-display.svelte';
	import MoneyDisplay from '#lib/components/common/money-display.svelte';
	import ReviewBadge from '#lib/components/common/review-badge.svelte';
	import Segmented from '#lib/components/common/segmented.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { NEW_RULE_PATH } from '#lib/rules/links.js';
	import { withExample } from '#lib/rules/example.js';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import { allocationText, type FieldName, type FieldValue } from '#lib/units/draft.js';
	import type { UnitDraftFlow } from '#lib/units/unit-draft-flow.svelte.js';
	import type { ProblemText } from '#lib/units/problems.js';
	import type { UnitProblem } from '#lib/units/types.js';
	import { shownFor, type EntryView, type FieldView } from '#lib/units/view.js';
	import { cn } from '#lib/utils.js';
	import EvidenceLine from './evidence-line.svelte';
	import FieldPicker from './field-picker.svelte';
	import PartnerField from './partner-field.svelte';
	import TagField from './tag-field.svelte';

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
		partnerDirection = null,
		locale = 'en'
	}: {
		view: EntryView;
		flow: UnitDraftFlow;
		lookups: Lookups;
		/** the problems of the preview that name this entry */
		problems?: { problem: UnitProblem; text: ProblemText }[];
		/** where the partner's group sits relative to this leg's, when the panel shows it */
		partnerDirection?: 'above' | 'below' | null;
		locale?: string;
	} = $props();

	const account = $derived(
		view.accountId === null ? undefined : lookups.accounts.get(view.accountId)
	);
	const partner = $derived(view.stored?.partner ?? null);
	const partnerAccount = $derived(partner ? lookups.accounts.get(partner.account_id) : undefined);
	const isTransfer = $derived(view.type === 'transfer');
	// the partner's side: a leg the draft joined (picked, proposed, settling's pair). It is re-paired
	// from the side the panel was opened on; its type and counter-account are the pair's
	const pairSide = $derived(view.joined && isTransfer && view.booking === null);
	const badgeSubject = $derived({
		type: view.type,
		counterpart_entry_id: view.row
			? view.row.counterpart_entry_id
			: (view.stored?.counterpart_entry_id ?? null)
	});
	// converting is for the entry that keeps the source: a split row is a flow (spec §5.9)
	const canConvert = $derived(
		!view.isNew && view.original && view.booking === null && !view.joined
	);
	// a booking's type is its source's (spec §5.8): said, not chosen
	const typeName = $derived(view.type === 'transfer' ? 'Transfer' : 'Flow');
	const counterAccount = $derived.by(() => {
		const id = view.fields.counter_account.value;
		return typeof id === 'number' ? lookups.accounts.get(id) : undefined;
	});
	const invalid = (field: FieldName) =>
		problems.some((p) => p.problem.field === field || p.problem.field === `${field}_id`);
	const amountText = $derived(
		flow.amountTexts[view.id] ??
			(view.amount ? allocationText(view.amount.amount, view.amount.currency, locale) : '')
	);
	// a block of a split says what its amount is: the original takes what the others leave (the
	// server's figure), every other block is a share the user sets
	const splitLabel = $derived(
		view.original && view.inSplit ? 'Residual' : view.isNew || view.inSplit ? 'Split' : null
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

	// "Add account" in the counter-account picker: the dialog opens locked to the currency the
	// currency rule asks for, when the preview says one; the new account is chosen on success
	function addAccount(
		trigger: HTMLElement | null,
		currency: string | undefined = required ?? undefined
	) {
		accountDialog.openAdd({
			currency,
			returnFocus: trigger,
			onadded: (account) => pick(view.fields.counter_account, account.id)
		});
	}

	function pick(field: FieldView, value: number | null) {
		// the X: the user takes their choice back (a payee: empty; the rest is proposed again)
		if (value === null) {
			flow.clearField(view.id, field.name);
			return;
		}
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

	// an entry with no type yet has no segment chosen
	const TYPES = $derived<
		{ value: string | null; label: string; disabled: boolean; reason: string }[]
	>(
		(['flow', 'transfer'] as const).map((value) => ({
			value,
			label: value === 'flow' ? 'Flow' : 'Transfer',
			disabled: !canConvert,
			reason: 'Only the original entry of a split can change its type'
		}))
	);

	function setType(next: 'flow' | 'transfer') {
		if (view.type !== next) flow.setType(view.id, next);
	}
</script>

<!-- the offer to turn the user's change of a rule's value into a rule: another page, in a new tab,
	because the panel may hold a draft; the same address as the icon of the source strip -->
{#snippet ruleOffer(field: FieldView)}
	{#if field.changedFromRule && view.stored?.source && !view.isNew}
		<a
			href={withExample(NEW_RULE_PATH, view.id)}
			target="_blank"
			rel="noopener"
			class="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
			data-slot="rule-offer"
			data-field={field.name}
		>
			Create rule from this transaction
		</a>
	{/if}
{/snippet}

{#snippet evidenceOf(field: FieldView)}
	<div class="flex flex-wrap items-baseline gap-x-3">
		<EvidenceLine evidence={field.evidence} />
		{@render ruleOffer(field)}
		{#if field.canReset}
			<ActionButton
				variant="link"
				class="h-auto p-0 text-xs"
				onclick={() => flow.revertField(view.id, field.name)}
			>
				Reset to proposal
			</ActionButton>
		{/if}
	</div>
{/snippet}

<section
	aria-label={view.isNew ? 'New split entry' : `Entry ${view.id}`}
	class={cn(
		'relative flex flex-col gap-3 rounded-lg border bg-card p-4 text-[13px]',
		view.isNew && 'border-dashed'
	)}
	data-slot="entry-editor"
	data-entry-id={view.id}
	data-new={view.isNew || undefined}
>
	<!-- the source text is what the entry is, muted; the description stays the user's -->
	{#if view.sourceText}
		<span
			class="min-w-0 truncate text-muted-foreground"
			title={view.sourceText}
			data-slot="source-text">{view.sourceText}</span
		>
	{/if}
	{#if view.removable}
		<IconButton
			verb="Remove split"
			compact
			class="absolute top-2 right-2"
			onclick={() => flow.removeSplit(view.id)}
		>
			<XIcon aria-hidden="true" />
		</IconButton>
	{/if}
	<div class={cn('flex flex-wrap items-baseline gap-x-4 gap-y-1', view.removable && 'pr-8')}>
		{#if view.amount}
			<span class="flex items-baseline gap-2">
				<MoneyDisplay
					minor={view.amount.amount}
					currency={view.amount.currency}
					{locale}
					showCurrency
					class="text-lg font-semibold"
				/>
				{#if splitLabel}
					<span class="text-xs text-muted-foreground" data-slot="split-label">{splitLabel}</span>
				{/if}
			</span>
		{:else if splitLabel}
			<span class="text-xs text-muted-foreground" data-slot="split-label">{splitLabel}</span>
		{/if}
		{#if !view.isNew}
			<DateDisplay date={view.row?.booked_on ?? view.stored?.booked_on ?? ''} {locale} />
		{/if}
		{#if account}
			<AccountDot name={account.name} color={resolveAccount(account).color} />
		{/if}
		<span class="flex items-center gap-1">
			{#each view.flags as flag (flag)}<ReviewBadge {flag} entry={badgeSubject} />{/each}
		</span>
	</div>

	<dl class="grid grid-cols-[8rem_1fr] items-start gap-x-4 gap-y-2">
		{#if view.amountEditable}
			<dt class="pt-1.5 text-muted-foreground">
				<label for={`amount-${view.id}`}>Amount</label>
			</dt>
			<dd class="min-w-0" data-slot="amount-field">
				<div class="flex items-center gap-2">
					<Input
						id={`amount-${view.id}`}
						bind:ref={amountInput}
						value={amountText}
						inputmode="decimal"
						autocomplete="off"
						aria-label={view.isNew ? 'Amount of the new split' : 'Amount'}
						aria-invalid={amountError ? true : undefined}
						aria-describedby={amountError ? `amount-error-${view.id}` : undefined}
						class="w-40 text-right tabular-nums"
						oninput={(event) => flow.setAmountText(view.id, event.currentTarget.value)}
						onblur={() => flow.applyAmountText(view.id)}
						onkeydown={(event) => {
							if (event.key === 'Enter') flow.applyAmountText(view.id);
						}}
					/>
					<span class="text-muted-foreground">{view.amount?.currency ?? ''}</span>
				</div>
				{#if amountError}
					<p id={`amount-error-${view.id}`} role="alert" class="text-xs text-destructive">
						{amountError}
					</p>
				{/if}
			</dd>
		{/if}

		{#if !view.isNew}
			<dt class="pt-1.5 text-muted-foreground">Type</dt>
			<dd class="min-w-0">
				{#if view.booking}
					<span class="inline-block pt-1.5" data-slot="booking-type">{typeName}</span>
				{:else if pairSide}
					<span class="inline-block pt-1.5" data-slot="pair-type">{typeName}</span>
				{:else}
					<Segmented
						label="Type"
						options={TYPES}
						value={view.type}
						onchange={(next) => {
							if (next === 'flow' || next === 'transfer') setType(next);
						}}
					/>
				{/if}
				<div class="flex flex-wrap items-baseline gap-x-3">
					<EvidenceLine evidence={view.fields.type.evidence} />
					{@render ruleOffer(view.fields.type)}
				</div>
			</dd>
		{/if}

		{#if isTransfer && view.booking}
			<!-- a counter-leg booking: its counter-account and its partner, the charge, are fixed -->
			<dt class="text-muted-foreground">Counter account</dt>
			<dd class="min-w-0" data-slot="booking-counter-account">
				{#if counterAccount}
					<AccountDot name={counterAccount.name} color={resolveAccount(counterAccount).color} />
				{/if}
				<EvidenceLine evidence={view.fields.counter_account.evidence} />
			</dd>
			<dt class="text-muted-foreground">Partner</dt>
			<dd class="min-w-0" data-slot="partner">
				<span class="flex flex-wrap items-baseline gap-x-2" data-slot="partner-leg">
					{#if partnerDirection}
						<span aria-hidden="true">{partnerDirection === 'below' ? '↓' : '↑'}</span>
						<span>Its charge is the entry {partnerDirection}</span>
					{:else}
						<span>Its charge</span>
					{/if}
				</span>
				<EvidenceLine evidence={view.pairEvidence} />
			</dd>
		{:else if pairSide}
			<!-- the partner's side: its counter-account is the pair's, shown as such -->
			<dt class="text-muted-foreground">Counter account</dt>
			<dd class="min-w-0" data-slot="pair-counter-account">
				{#if counterAccount}
					<AccountDot name={counterAccount.name} color={resolveAccount(counterAccount).color} />
				{/if}
				<EvidenceLine evidence={view.fields.counter_account.evidence} />
			</dd>
			{#if view.transfer}
				<PartnerField
					{view}
					{flow}
					{lookups}
					{locale}
					direction={partnerDirection}
					counterAccountId={typeof view.fields.counter_account.value === 'number'
						? view.fields.counter_account.value
						: null}
					onaddaccount={addAccount}
				/>
			{/if}
		{:else if isTransfer}
			<dt class="pt-1.5 text-muted-foreground">Counter account</dt>
			<dd class="min-w-0">
				<FieldPicker
					kind="counter_account"
					label="Counter account"
					value={typeof view.fields.counter_account.value === 'number'
						? view.fields.counter_account.value
						: null}
					{lookups}
					clearable={view.fields.counter_account.clearable}
					proposal={view.fields.counter_account.proposal}
					invalid={invalid('counter_account')}
					disabledReason={accountReason}
					add={{ label: 'Add account', run: addAccount }}
					onchange={(id) => pick(view.fields.counter_account, id)}
				/>
				{@render evidenceOf(view.fields.counter_account)}
			</dd>
			{#if view.transfer && !view.isNew}
				<PartnerField
					{view}
					{flow}
					{lookups}
					{locale}
					direction={partnerDirection}
					counterAccountId={typeof view.fields.counter_account.value === 'number'
						? view.fields.counter_account.value
						: null}
					onaddaccount={addAccount}
				/>
			{:else if partner}
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
					clearable={view.fields.category.clearable}
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
					clearable={view.fields.payee.clearable}
					emptyText="No payee"
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

		<dt class="pt-0.5 text-muted-foreground">Tags</dt>
		<dd class="min-w-0">
			<TagField
				tagIds={view.tagIds}
				{lookups}
				busy={flow.tagBusy || flow.committing}
				ontoggle={(tagId) => flow.toggleTag(view.id, tagId)}
				oncreate={(name) => void flow.createTag(view.id, name)}
			/>
		</dd>
	</dl>
</section>
