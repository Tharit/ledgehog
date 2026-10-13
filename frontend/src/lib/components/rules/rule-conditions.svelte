<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import IconButton from '#lib/components/common/icon-button.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import {
		CONDITION_FIELDS,
		CONDITION_OPS,
		FIELD_LABELS,
		OP_LABELS,
		type ConditionField,
		type ConditionOp,
		type ConditionRow
	} from '#lib/rules/conditions.js';
	import { SELECT_CLASS } from '#lib/rules/styles.js';
	import TargetPicker from './target-picker.svelte';

	// The conditions of a rule: a list of rows `[field] [operator] [value]`, all of which must hold,
	// and for a category rule one more row, the payee. Conditions are text the server judges;
	// nothing is matched here. It holds nothing: every change goes up and the form comes back.
	let {
		rows,
		errors = {},
		listError,
		payee = null,
		takesPayee = false,
		payeeError,
		lookups,
		onchange,
		onadd,
		onremove,
		onpayee
	}: {
		rows: readonly ConditionRow[];
		/** the server's word about a row, by the row's position */
		errors?: Record<number, string>;
		/** the server's word about the conditions as a whole */
		listError?: string;
		payee?: number | null;
		/** category rules only */
		takesPayee?: boolean;
		payeeError?: string;
		lookups: Lookups;
		onchange: (index: number, patch: Partial<Omit<ConditionRow, 'key'>>) => void;
		onadd: () => void;
		onremove: (index: number) => void;
		onpayee: (id: number | null) => void;
	} = $props();

	const hasBlank = $derived(rows.some((row) => row.value.trim() === ''));
</script>

<fieldset class="flex flex-col gap-3">
	<legend class="mb-1 text-sm font-semibold">When an entry’s source transaction has</legend>
	<p class="text-xs text-muted-foreground">All the conditions must hold.</p>

	<ul class="flex flex-col gap-3" aria-label="Conditions">
		{#each rows as row, index (row.key)}
			{@const error = errors[index]}
			{@const n = index + 1}
			<li class="flex flex-col gap-1" data-condition-row={index}>
				<div class="flex flex-wrap items-center gap-2">
					<select
						class={`${SELECT_CLASS} w-52 max-w-full`}
						aria-label={`Condition ${n}: field`}
						value={row.field}
						onchange={(event) =>
							onchange(index, { field: event.currentTarget.value as ConditionField })}
					>
						{#each CONDITION_FIELDS as field (field)}
							<option value={field}>{FIELD_LABELS[field]}</option>
						{/each}
					</select>
					<select
						class={`${SELECT_CLASS} w-48 max-w-full`}
						aria-label={`Condition ${n}: operator`}
						value={row.op}
						onchange={(event) => onchange(index, { op: event.currentTarget.value as ConditionOp })}
					>
						{#each CONDITION_OPS as op (op)}
							<option value={op}>{OP_LABELS[op]}</option>
						{/each}
					</select>
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
					<IconButton verb="Remove" label={`Remove condition ${n}`} onclick={() => onremove(index)}>
						<XIcon aria-hidden="true" />
					</IconButton>
				</div>
				{#if error}
					<p id={`rule-condition-${row.key}-error`} class="text-xs text-destructive">{error}</p>
				{/if}
				{#if row.op === 'regex'}
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

	{#if takesPayee}
		<div class="flex flex-col gap-1">
			<div class="flex flex-wrap items-center gap-2">
				<span id="rule-condition-payee-label" class="w-24 shrink-0 text-sm">Payee is</span>
				<div class="min-w-48 flex-1">
					<TargetPicker
						id="rule-condition-payee"
						kind="payee"
						value={payee}
						{lookups}
						label="Condition payee: the payee the entry must have"
						clearable
						invalid={payeeError !== undefined}
						onchange={onpayee}
					/>
				</div>
			</div>
			{#if payeeError}
				<p class="text-xs text-destructive">{payeeError}</p>
			{/if}
			<p class="text-xs text-muted-foreground">
				Judged on the payee found before the category, a proposed one included.
			</p>
		</div>
	{/if}
</fieldset>
