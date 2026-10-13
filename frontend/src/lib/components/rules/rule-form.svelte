<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ConditionRow } from '#lib/rules/conditions.js';
	import { SETS, SETS_INFO, takesPayeeCondition, type RuleForm } from '#lib/rules/form.js';
	import { RULES_PATH } from '#lib/rules/links.js';
	import type { FieldErrors } from '#lib/rules/messages.js';
	import { SELECT_CLASS } from '#lib/rules/styles.js';
	import { kindWord } from '#lib/rules/targets.js';
	import type { RuleSets } from '#lib/rules/types.js';
	import RuleConditions from './rule-conditions.svelte';
	import TargetPicker from './target-picker.svelte';

	// The rule editor's form: name, what it sets and the target, the example and the conditions,
	// and the priority under "Advanced". It holds nothing: every edit goes up and the page's store
	// gives the form back. Enter in a field never submits; ⌘/Ctrl+Enter saves (patterns §11.2).
	let {
		form,
		lookups,
		errors = {},
		editing = false,
		saveBlocked = null,
		saving = false,
		example,
		onedit,
		oncondition,
		onaddcondition,
		onremovecondition,
		onsave,
		ondelete
	}: {
		form: RuleForm;
		lookups: Lookups;
		errors?: FieldErrors;
		editing?: boolean;
		/** why the rule cannot be saved yet; null when it can */
		saveBlocked?: string | null;
		saving?: boolean;
		/** the example region, shown above the conditions */
		example?: Snippet;
		onedit: (patch: Partial<RuleForm>, now?: boolean) => void;
		oncondition: (index: number, patch: Partial<Omit<ConditionRow, 'key'>>) => void;
		onaddcondition: () => void;
		onremovecondition: (index: number) => void;
		onsave: () => void;
		ondelete?: () => void;
	} = $props();

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
			event.preventDefault();
			if (saveBlocked === null) onsave();
		}
	}

	const advancedOpen = $derived(form.priority.trim() !== '' || errors.priority !== undefined);
</script>

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
			autocomplete="off"
			aria-invalid={errors.name ? true : undefined}
			aria-describedby={errors.name ? 'rule-name-error' : undefined}
			oninput={(event) => onedit({ name: event.currentTarget.value })}
		/>
		{#if errors.name}
			<p id="rule-name-error" class="text-xs text-destructive">{errors.name}</p>
		{/if}
		<p class="text-xs text-muted-foreground">
			Shown as the reason (“rule: Rent”) wherever this rule decides an entry.
		</p>
	</div>

	<fieldset class="flex flex-col gap-3">
		<legend class="mb-1 text-sm font-semibold">What it sets</legend>
		<div class="flex flex-col gap-1">
			<label for="rule-sets" class="text-xs font-medium">Sets</label>
			<select
				id="rule-sets"
				class={`${SELECT_CLASS} w-full`}
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

	{@render example?.()}

	<RuleConditions
		rows={form.conditions}
		errors={errors.rows}
		listError={errors.conditions}
		payee={form.condition_payee_id}
		takesPayee={takesPayeeCondition(form.sets)}
		payeeError={errors.condition_payee_id}
		{lookups}
		onchange={oncondition}
		onadd={onaddcondition}
		onremove={onremovecondition}
		onpayee={(id) => onedit({ condition_payee_id: id }, true)}
	/>

	<details class="rounded-lg border px-3 py-2" open={advancedOpen}>
		<summary class="cursor-pointer text-sm font-medium">Advanced</summary>
		<div class="mt-3 flex flex-col gap-1">
			<label for="rule-priority" class="text-xs font-medium">Priority</label>
			<Input
				id="rule-priority"
				class="w-28"
				inputmode="numeric"
				value={form.priority}
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
			<Button variant="destructive" class="ml-auto" onclick={ondelete}>Delete…</Button>
		{/if}
		<span class="basis-full text-xs text-muted-foreground">⌘/Ctrl + Enter saves.</span>
	</div>
</form>
