<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import {
		CONDITION_OPS,
		ENTRY_GROUP,
		ACCOUNT_FIELD,
		FIELD_LABELS,
		OP_LABELS,
		OP_LABELS_PAYEE,
		PAYEE_FIELD,
		SOURCE_FIELDS,
		SOURCE_GROUP,
		SOURCE_TEXT_FIELD,
		isAccountRow,
		isIdRow,
		isPayeeRow,
		payeeOfRow,
		type ConditionRow,
		type RowField,
		type RowOp
	} from '#lib/rules/conditions.js';
	import TargetPicker from './target-picker.svelte';

	// The conditions of a rule: a list of rows `[field] [operator] [value]`, all of which must hold,
	// where any rule can test the entry's account and a category rule its payee (rows whose operator is
	// fixed and whose value is picked from a list). Conditions are text the server judges;
	// nothing is matched here. It holds nothing: every change goes up and the form comes back.
	let {
		rows,
		errors = {},
		listError,
		takesPayee = false,
		lookups,
		onchange,
		onadd,
		onremove
	}: {
		rows: readonly ConditionRow[];
		/** the server's word about a row, by the row's position */
		errors?: Record<number, string>;
		/** the server's word about the conditions as a whole */
		listError?: string;
		/** category rules only: the field list offers the payee */
		takesPayee?: boolean;
		lookups: Lookups;
		onchange: (index: number, patch: Partial<Omit<ConditionRow, 'key'>>) => void;
		onadd: () => void;
		onremove: (index: number) => void;
	} = $props();

	/** the payee or account a row names that the lists do not know: deleted (or merged) since */
	function targetGone(row: ConditionRow): boolean {
		const id = payeeOfRow(row);
		if (id === null) return false;
		return isAccountRow(row) ? !lookups.accounts.has(id) : !lookups.payees.has(id);
	}

	const opOptions = CONDITION_OPS.map((op) => ({ value: op, label: OP_LABELS[op] }));

	/**
	 * the field list in two groups: the source transaction's fields, then the entry's (its source
	 * text and account, and the payee on category rules, kept on a row that has it)
	 */
	function fieldOptions(row: ConditionRow) {
		const options: { value: string; label: string; group: string }[] = [];
		for (const field of SOURCE_FIELDS) {
			options.push({ value: field, label: FIELD_LABELS[field], group: SOURCE_GROUP });
		}
		options.push({
			value: SOURCE_TEXT_FIELD,
			label: FIELD_LABELS[SOURCE_TEXT_FIELD],
			group: ENTRY_GROUP
		});
		options.push({ value: ACCOUNT_FIELD, label: 'Account', group: ENTRY_GROUP });
		if (takesPayee || isPayeeRow(row)) {
			options.push({ value: PAYEE_FIELD, label: 'Payee', group: ENTRY_GROUP });
		}
		return options;
	}

	const hasBlank = $derived(rows.some((row) => row.value.trim() === ''));
</script>

<fieldset class="flex flex-col gap-3">
	<legend class="mb-1 text-sm font-semibold">When the entry has</legend>
	<p class="text-xs text-muted-foreground">All the conditions must hold.</p>

	<ul class="flex flex-col gap-3" aria-label="Conditions">
		{#each rows as row, index (row.key)}
			{@const error = errors[index]}
			{@const n = index + 1}
			<li class="flex flex-col gap-1" data-condition-row={index}>
				<div class="flex flex-wrap items-center gap-2">
					<ChoiceSelect
						class="w-52 max-w-full"
						label={`Condition ${n}: field`}
						value={row.field}
						options={fieldOptions(row)}
						onchange={(next) => onchange(index, { field: next as RowField })}
					/>
					{#if isIdRow(row)}
						{@const account = isAccountRow(row)}
						<ChoiceSelect
							class="w-48 max-w-full"
							label={`Condition ${n}: operator`}
							value="is"
							options={[{ value: 'is', label: OP_LABELS_PAYEE }]}
							disabled
							onchange={() => {}}
						/>
						<div
							class="flex min-w-48 flex-1 items-center gap-2"
							data-payee-value={account ? undefined : ''}
							data-account-value={account ? '' : undefined}
						>
							{#if targetGone(row)}
								<span
									class="shrink-0 text-sm text-muted-foreground"
									title={account
										? 'This account no longer exists; the rule cannot match until you pick another.'
										: 'This payee no longer exists; the rule cannot match until you pick another.'}
									>{account ? 'Account deleted' : 'Payee deleted'}</span
								>
							{/if}
							<div class="min-w-0 flex-1">
								<TargetPicker
									id={`rule-condition-${row.key}-${account ? 'account' : 'payee'}`}
									kind={account ? 'counter_account' : 'payee'}
									noun={account ? 'account' : undefined}
									value={targetGone(row) ? null : payeeOfRow(row)}
									{lookups}
									label={`Condition ${n}: ${account ? 'account' : 'payee'}`}
									invalid={error !== undefined}
									onchange={(id) => onchange(index, { value: id === null ? '' : String(id) })}
								/>
							</div>
						</div>
					{:else}
						<ChoiceSelect
							class="w-48 max-w-full"
							label={`Condition ${n}: operator`}
							value={row.op}
							options={opOptions}
							onchange={(next) => onchange(index, { op: next as RowOp })}
						/>
						<Input
							class="w-auto min-w-40 flex-1"
							aria-label={`Condition ${n}: value`}
							value={row.value}
							autocomplete="off"
							spellcheck={false}
							aria-invalid={error ? true : undefined}
							aria-describedby={error ? `rule-condition-${row.key}-error` : undefined}
							oninput={(event) => onchange(index, { value: event.currentTarget.value })}
						/>
					{/if}
					<IconButton verb="Remove" label={`Remove condition ${n}`} onclick={() => onremove(index)}>
						<XIcon aria-hidden="true" />
					</IconButton>
				</div>
				{#if error}
					<p id={`rule-condition-${row.key}-error`} class="text-xs text-destructive">{error}</p>
				{/if}
				{#if isPayeeRow(row)}
					<p class="text-xs text-muted-foreground">
						Uses the payee found for the entry, even a suggested one you have not confirmed.
					</p>
				{:else if row.field === SOURCE_TEXT_FIELD}
					<p class="text-xs text-muted-foreground">
						The entry’s own text, as a booked order item has one; an entry without one never
						matches.
					</p>
				{:else if row.op === 'regex'}
					<p class="text-xs text-muted-foreground">
						A regular expression, found anywhere in the text, upper and lower case alike; at most
						200 characters.
					</p>
				{/if}
			</li>
		{/each}
	</ul>

	{#if listError}
		<p class="text-xs text-destructive">{listError}</p>
	{/if}

	<div class="flex flex-wrap items-center gap-3">
		<Button variant="outline" onclick={onadd}>Add condition</Button>
		{#if hasBlank && rows.length > 1}
			<span class="text-xs text-muted-foreground">Rows without a value are left out.</span>
		{/if}
	</div>
</fieldset>
