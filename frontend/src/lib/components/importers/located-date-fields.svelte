<script lang="ts">
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import type { LocatedDraft } from '#lib/importers/csv-profile.js';
	import ProfileField from './profile-field.svelte';

	// A date found in the file by label (csv.md §5): a cell at an offset from a label, or a pattern in
	// a cell's text. It is optional, so it opens with an on/off choice. `anchored` says that without
	// a label it is read from the balance figure's own cell (the balance date only).
	let {
		title,
		hint,
		value = $bindable(),
		error = null,
		anchored = false,
		formatHint
	}: {
		title: string;
		hint: string;
		value: LocatedDraft;
		error?: string | null;
		anchored?: boolean;
		formatHint?: string;
	} = $props();
</script>

<div class="flex flex-col gap-3" data-slot="located-date">
	<Field label={title} {hint} {error}>
		{#snippet children(control)}
			<ChoiceSelect
				{...control}
				label={title}
				value={value.on ? 'on' : 'off'}
				options={[
					{ value: 'off', label: 'Not read from the file' },
					{ value: 'on', label: 'Read from the file' }
				]}
				onchange={(next) => (value.on = next === 'on')}
			/>
		{/snippet}
	</Field>
	{#if value.on}
		<div class="flex flex-col gap-3 border-l-2 border-border pl-4">
			<ProfileField
				label={`${title}: format`}
				hint={formatHint ?? 'Written with dd, d, MM, M and yyyy.'}
				bind:value={value.format}
			/>
			<ProfileField
				label={`${title}: label`}
				hint={anchored
					? 'The text of the cell that labels it. Empty reads it at the offsets from the balance figure’s own cell.'
					: 'The text of the cell that labels it: a cell that is exactly this text, else one that contains it.'}
				bind:value={value.label}
			/>
			<div class="grid grid-cols-2 gap-3">
				<ProfileField
					label={`${title}: cells to the right`}
					hint="Counted from the label cell."
					bind:value={value.right}
					narrow
				/>
				<ProfileField
					label={`${title}: rows below`}
					hint="Counted from the label cell, in the same column."
					bind:value={value.below}
					narrow
				/>
			</div>
			<ProfileField
				label={`${title}: pattern`}
				hint="Optional. A regular expression, searched in the cell’s text; its first group is the date."
				bind:value={value.pattern}
			/>
		</div>
	{/if}
</div>
