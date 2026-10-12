<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import {
		SETS,
		SETS_INFO,
		takesPayeeCondition,
		type ConditionField,
		type RuleForm
	} from '#lib/rules/form.js';
	import { RULES_PATH } from '#lib/rules/links.js';
	import type { FieldErrors } from '#lib/rules/messages.js';
	import { applySuggestion, isApplied, type Suggestion } from '#lib/rules/prefill.js';
	import { kindWord } from '#lib/rules/targets.js';
	import type { RuleSets } from '#lib/rules/types.js';
	import TargetPicker from './target-picker.svelte';

	// The rule editor's form: name, what it sets and the target, the conditions, and the priority
	// under "Advanced". It holds nothing: every edit goes up (`onedit`) and the page's store gives
	// the form back. Conditions are text the server judges; nothing is matched here.
	let {
		form,
		suggestions = [],
		lookups,
		errors = {},
		editing = false,
		saveBlocked = null,
		saving = false,
		onedit,
		onsave,
		ondelete
	}: {
		form: RuleForm;
		/** the entry's text, each with a box to tick */
		suggestions?: readonly Suggestion[];
		lookups: Lookups;
		errors?: FieldErrors;
		editing?: boolean;
		/** why the rule cannot be saved yet; null when it can */
		saveBlocked?: string | null;
		saving?: boolean;
		onedit: (patch: Partial<RuleForm>, now?: boolean) => void;
		onsave: () => void;
		ondelete?: () => void;
	} = $props();

	function patch(field: ConditionField, value: string): Partial<RuleForm> {
		return { [field]: value } as Partial<RuleForm>;
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
			event.preventDefault();
			if (saveBlocked === null) onsave();
		}
	}

	const advancedOpen = $derived(form.priority.trim() !== '' || errors.priority !== undefined);
</script>

{#snippet condition(field: ConditionField, label: string, hint: string, placeholder: string)}
	{@const error = errors[field]}
	{@const suggestion = suggestions.find((s) => s.field === field)}
	<div class="flex flex-col gap-1">
		<label for={`rule-${field}`} class="text-xs font-medium">{label}</label>
		<Input
			id={`rule-${field}`}
			value={form[field]}
			{placeholder}
			autocomplete="off"
			spellcheck={false}
			aria-invalid={error ? true : undefined}
			aria-describedby={error ? `rule-${field}-error` : undefined}
			oninput={(event) => onedit(patch(field, event.currentTarget.value))}
		/>
		{#if error}
			<p id={`rule-${field}-error`} class="text-xs text-destructive">{error}</p>
		{/if}
		{#if suggestion}
			<label class="flex cursor-pointer items-center gap-2 text-xs">
				<input
					type="checkbox"
					checked={isApplied(form, suggestion)}
					onchange={(event) =>
						onedit(
							patch(field, applySuggestion(form, suggestion, event.currentTarget.checked)[field]),
							true
						)}
				/>
				<span>
					Use <span class="font-medium">“{suggestion.value}”</span>
					<span class="text-muted-foreground">from the entry</span>
				</span>
			</label>
		{/if}
		<p class="text-xs text-muted-foreground">{hint}</p>
	</div>
{/snippet}

<!-- one explicit save button; Enter in a field does not submit (⌘/Ctrl+Enter does) -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<form
	class="flex flex-col gap-5 rounded-xl border bg-card p-5 shadow-card"
	aria-label="Rule"
	onsubmit={(event) => event.preventDefault()}
	{onkeydown}
>
	<div class="flex flex-col gap-1">
		<label for="rule-name" class="text-xs font-medium">Name</label>
		<Input
			id="rule-name"
			value={form.name}
			placeholder="Rent"
			autocomplete="off"
			aria-invalid={errors.name ? true : undefined}
			aria-describedby={errors.name ? 'rule-name-error' : undefined}
			oninput={(event) => onedit({ name: event.currentTarget.value })}
		/>
		{#if errors.name}
			<p id="rule-name-error" class="text-xs text-destructive">{errors.name}</p>
		{/if}
		<p class="text-xs text-muted-foreground">
			Shown as the reason ("rule: Rent") wherever this rule decides an entry.
		</p>
	</div>

	<fieldset class="flex flex-col gap-3">
		<legend class="mb-1 text-sm font-semibold">What it sets</legend>
		<div class="flex flex-col gap-1">
			<label for="rule-sets" class="text-xs font-medium">Sets a</label>
			<select
				id="rule-sets"
				class="h-8 w-full cursor-pointer rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
				value={form.sets}
				disabled={editing}
				onchange={(event) => onedit({ sets: event.currentTarget.value as RuleSets }, true)}
			>
				{#each SETS as sets (sets)}
					<option value={sets}>{SETS_INFO[sets].name}</option>
				{/each}
			</select>
			<p class="text-xs text-muted-foreground">
				{SETS_INFO[form.sets].hint}
				{#if editing}Fixed once the rule exists.{/if}
			</p>
		</div>
		<div class="flex flex-col gap-1">
			<span id="rule-target-label" class="text-xs font-medium">
				{SETS_INFO[form.sets].name}
			</span>
			<TargetPicker
				id="rule-target"
				kind={form.sets}
				value={form.target}
				{lookups}
				label={`The ${kindWord(form.sets)} this rule sets`}
				invalid={errors.target !== undefined}
				onchange={(target) => onedit({ target }, true)}
			/>
			{#if errors.target}
				<p class="text-xs text-destructive">{errors.target}</p>
			{/if}
		</div>
	</fieldset>

	<fieldset class="flex flex-col gap-3">
		<legend class="mb-1 text-sm font-semibold">When an entry has</legend>
		<p class="text-xs text-muted-foreground">All the conditions you fill in must hold.</p>
		{@render condition(
			'counterparty_ref',
			'Counterparty reference',
			'The IBAN or other reference of the other side, compared as plain letters and digits.',
			'DE89 3704 0044 0532 0130 00'
		)}
		{@render condition(
			'mandate_ref',
			'Mandate reference',
			'Tells apart contracts of one creditor, compared as plain letters and digits.',
			''
		)}
		{@render condition(
			'name_prefix',
			'Counterparty name starts with',
			'Case, spacing and the document’s merchant name aside; punctuation counts.',
			'PAYPAL *'
		)}
		{@render condition(
			'name_exact',
			'Counterparty name is',
			'The whole name, compared the same way.',
			''
		)}
		{@render condition(
			'purpose_regex',
			'Purpose matches (regular expression)',
			'Case-insensitive, found anywhere in the purpose; at most 200 characters.',
			'rent|miete'
		)}
		{@render condition(
			'booking_text',
			'Booking text',
			'The bank’s booking text, compared as plain letters and digits.',
			''
		)}
		{#if takesPayeeCondition(form.sets)}
			<div class="flex flex-col gap-1">
				<span class="text-xs font-medium">Payee is</span>
				<TargetPicker
					id="rule-condition-payee"
					kind="payee"
					value={form.condition_payee_id}
					{lookups}
					label="Only entries with this payee"
					clearable
					invalid={errors.condition_payee_id !== undefined}
					onchange={(id) => onedit({ condition_payee_id: id }, true)}
				/>
				{#if errors.condition_payee_id}
					<p class="text-xs text-destructive">{errors.condition_payee_id}</p>
				{/if}
				<p class="text-xs text-muted-foreground">
					Judged on the payee found before the category, a proposed one included.
				</p>
			</div>
		{/if}
	</fieldset>

	<details class="rounded-lg border px-3 py-2" open={advancedOpen}>
		<summary class="cursor-pointer text-sm font-medium">Advanced</summary>
		<div class="mt-3 flex flex-col gap-1">
			<label for="rule-priority" class="text-xs font-medium">Priority</label>
			<Input
				id="rule-priority"
				class="w-28"
				inputmode="numeric"
				value={form.priority}
				placeholder="100"
				aria-invalid={errors.priority ? true : undefined}
				oninput={(event) => onedit({ priority: event.currentTarget.value })}
			/>
			{#if errors.priority}
				<p class="text-xs text-destructive">{errors.priority}</p>
			{/if}
			<p class="text-xs text-muted-foreground">
				Among rules that set the same kind of value, the lower number is tried first. Blank is 100.
			</p>
		</div>
	</details>

	<div class="flex flex-wrap items-center gap-2">
		<span class="inline-flex" title={saveBlocked ?? undefined}>
			<Button disabled={saveBlocked !== null} onclick={onsave}>
				{saving ? 'Saving…' : 'Save rule'}
			</Button>
		</span>
		<Button variant="outline" href={RULES_PATH}>Cancel</Button>
		{#if editing && ondelete}
			<Button variant="destructive" class="ml-auto" onclick={ondelete}>Delete rule…</Button>
		{/if}
		<span class="basis-full text-xs text-muted-foreground">⌘/Ctrl + Enter saves.</span>
	</div>
</form>
