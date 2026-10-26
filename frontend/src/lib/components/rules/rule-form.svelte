<script lang="ts">
	import type { Snippet } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import type { ConditionRow } from '#lib/rules/conditions.js';
	import { SETS, SETS_INFO, takesPayeeCondition, type RuleForm } from '#lib/rules/form.js';
	import { RULES_PATH } from '#lib/rules/links.js';
	import type { FieldErrors } from '#lib/rules/messages.js';
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
	<Field
		label="Name"
		hint="Shown as the reason (“rule: Rent”) wherever this rule decides an entry."
		error={errors.name ?? null}
	>
		{#snippet children(control)}
			<Input
				{...control}
				value={form.name}
				autocomplete="off"
				oninput={(event) => onedit({ name: event.currentTarget.value })}
			/>
		{/snippet}
	</Field>

	<fieldset class="flex flex-col gap-3">
		<legend class="mb-1 text-sm font-semibold">What it sets</legend>
		<Field
			label="Sets"
			hint={`${SETS_INFO[form.sets].hint}${editing ? ' Fixed once the rule exists.' : ''}`}
		>
			{#snippet children(control)}
				<ChoiceSelect
					{...control}
					label="Sets"
					value={form.sets}
					options={SETS.map((sets) => ({ value: sets, label: SETS_INFO[sets].name }))}
					disabled={editing}
					onchange={(next) => onedit({ sets: next as RuleSets }, true)}
				/>
			{/snippet}
		</Field>
		<Field label={SETS_INFO[form.sets].name} error={errors.target ?? null}>
			{#snippet children(control)}
				<TargetPicker
					id={control.id}
					kind={form.sets}
					value={form.target}
					{lookups}
					label={`The ${kindWord(form.sets)} this rule sets`}
					invalid={errors.target !== undefined}
					onchange={(target) => onedit({ target }, true)}
				/>
			{/snippet}
		</Field>
	</fieldset>

	{@render example?.()}

	<RuleConditions
		rows={form.conditions}
		errors={errors.rows}
		listError={errors.conditions}
		takesPayee={takesPayeeCondition(form.sets)}
		{lookups}
		onchange={oncondition}
		onadd={onaddcondition}
		onremove={onremovecondition}
	/>

	<details class="rounded-lg border px-3 py-2" open={advancedOpen}>
		<summary class="text-sm font-medium">Advanced</summary>
		<div class="mt-3">
			<Field
				label="Priority"
				hint="Among rules that set the same kind of value, the lower number is tried first. Blank is 100."
				error={errors.priority ?? null}
			>
				{#snippet children(control)}
					<Input
						{...control}
						class="w-28"
						inputmode="numeric"
						value={form.priority}
						oninput={(event) => onedit({ priority: event.currentTarget.value })}
					/>
				{/snippet}
			</Field>
		</div>
	</details>

	<div class="flex flex-wrap items-center gap-2">
		<ActionButton
			busy={saving}
			busyLabel="Saving…"
			disabled={saveBlocked !== null}
			reason={saveBlocked ?? undefined}
			onclick={onsave}
		>
			Save rule
		</ActionButton>
		<ActionButton variant="outline" href={RULES_PATH}>Cancel</ActionButton>
		{#if editing && ondelete}
			<ActionButton variant="destructive" class="ml-auto" onclick={ondelete}>Delete…</ActionButton>
		{/if}
		<span class="basis-full text-xs text-muted-foreground">⌘/Ctrl + Enter saves.</span>
	</div>
</form>
