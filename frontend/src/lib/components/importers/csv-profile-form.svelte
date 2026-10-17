<script lang="ts">
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import type { CsvDraft } from '#lib/importers/csv-profile.js';
	import LocatedDateFields from './located-date-fields.svelte';
	import ProfileField from './profile-field.svelte';

	// The CSV importer's settings (ux/views/importers.md "The CSV profile form"; plugins/importers/
	// csv.md §2–§6), in the groups of the profile. Every field is labelled and carries helper text
	// instead of an example value as a placeholder. The form holds nothing of its own: it edits the
	// draft it is given, and the server's refusals (`errors`, by field id) stand under their fields.
	let {
		draft,
		errors = {},
		disabled = false
	}: {
		draft: CsvDraft;
		errors?: Record<string, string>;
		disabled?: boolean;
	} = $props();

	const err = (...keys: string[]) =>
		keys.map((k) => errors[k]).find((m) => m !== undefined) ?? null;

	const COLUMN =
		'A column is named by its header, by Name#2 for the second column of that name, or by its position counted from 1.';
	const YES_NO = [
		{ value: 'no', label: 'No' },
		{ value: 'yes', label: 'Yes' }
	];

	function addFilter() {
		draft.filters.push({ column: '', kind: 'equals', value: '' });
	}
	function removeFilter(index: number) {
		draft.filters.splice(index, 1);
	}
</script>

<div class="flex flex-col gap-6" data-slot="csv-profile-form">
	<fieldset class="flex flex-col gap-3" {disabled}>
		<legend class="mb-1 text-base font-semibold">Reading the file</legend>
		<ProfileField
			label="Encoding"
			hint="Leave empty to detect it: UTF-8 if the file decodes as it, otherwise cp1252. Name one to force it."
			error={err('encoding')}
			bind:value={draft.encoding}
		/>
		<div class="grid gap-3 sm:grid-cols-2">
			<ProfileField
				label="Delimiter"
				hint="One character. Leave empty to detect it."
				error={err('delimiter')}
				bind:value={draft.delimiter}
				narrow
			/>
			<ProfileField
				label="Quote"
				hint="The character that wraps a cell holding the delimiter."
				error={err('quote')}
				bind:value={draft.quote}
				narrow
			/>
		</div>
		<ProfileField
			label="Header marker"
			hint="The column names that identify the header row, one per line: the first row containing all of them. Everything above it is the preamble."
			error={err('header_marker')}
			bind:value={draft.headerMarker}
			multiline
		/>
	</fieldset>

	<fieldset class="flex flex-col gap-3" {disabled}>
		<legend class="mb-1 text-base font-semibold">Columns</legend>
		<ProfileField
			label="Booking date column"
			hint={COLUMN}
			error={err('booked_on')}
			bind:value={draft.bookedOn}
		/>
		<ProfileField
			label="Date format"
			hint="Written with dd, d, MM, M and yyyy, with the file’s separators between them."
			error={err('date_format')}
			bind:value={draft.dateFormat}
		/>
		<ProfileField
			label="Value date column"
			hint="Optional. A column of dates."
			error={err('value_on')}
			bind:value={draft.valueOn}
		/>

		<Field
			label="Amount"
			hint="One signed column, or a credit and a debit column (the amount is credit minus debit)."
			error={err('amount')}
		>
			{#snippet children(control)}
				<ChoiceSelect
					{...control}
					label="Amount"
					value={draft.amountMode}
					options={[
						{ value: 'signed', label: 'One signed column' },
						{ value: 'split', label: 'A credit and a debit column' }
					]}
					onchange={(next) => (draft.amountMode = next as CsvDraft['amountMode'])}
				/>
			{/snippet}
		</Field>
		{#if draft.amountMode === 'signed'}
			<ProfileField label="Amount column" hint={COLUMN} bind:value={draft.amountColumn} />
		{:else}
			<div class="grid gap-3 sm:grid-cols-2">
				<ProfileField label="Credit column" hint={COLUMN} bind:value={draft.credit} />
				<ProfileField
					label="Debit column"
					hint="An empty cell counts as 0."
					bind:value={draft.debit}
				/>
			</div>
		{/if}
		<div class="grid gap-3 sm:grid-cols-2">
			<ProfileField
				label="Decimal separator"
				hint="One character."
				error={err('decimal_sep')}
				bind:value={draft.decimalSep}
				narrow
			/>
			<ProfileField
				label="Thousands separator"
				hint="One character, or empty for none. It differs from the decimal separator."
				error={err('thousands_sep')}
				bind:value={draft.thousandsSep}
				narrow
			/>
		</div>

		<div class="grid gap-3 sm:grid-cols-2">
			<ProfileField
				label="Counterparty name column"
				hint="Optional."
				error={err('counterparty_name')}
				bind:value={draft.counterpartyName}
			/>
			<ProfileField
				label="Counterparty account column"
				hint="Optional. The IBAN or account number."
				error={err('counterparty_ref')}
				bind:value={draft.counterpartyRef}
			/>
			<ProfileField
				label="Counterparty BIC column"
				hint="Optional."
				error={err('counterparty_bic')}
				bind:value={draft.counterpartyBic}
			/>
			<ProfileField
				label="End-to-end ID column"
				hint="Optional."
				error={err('end_to_end_id')}
				bind:value={draft.endToEndId}
			/>
			<ProfileField
				label="Mandate reference column"
				hint="Optional."
				error={err('mandate_ref')}
				bind:value={draft.mandateRef}
			/>
			<ProfileField
				label="Booking text column"
				hint="Optional."
				error={err('booking_text')}
				bind:value={draft.bookingText}
			/>
		</div>
		<ProfileField
			label="Purpose columns"
			hint="One column per line. Their cells are joined with a space; empty cells are dropped."
			error={err('purpose')}
			bind:value={draft.purpose}
			multiline
		/>
		<div class="grid gap-3 sm:grid-cols-2">
			<ProfileField
				label="Instructed amount column"
				hint="Optional: an amount stated in another currency. Needs its currency column too. Ignored on a row whose currency is the account’s."
				error={err('instructed')}
				bind:value={draft.instructedAmount}
			/>
			<ProfileField
				label="Instructed currency column"
				hint="Optional. The currency of the instructed amount."
				bind:value={draft.instructedCurrency}
			/>
		</div>
		<ProfileField
			label="Currency column"
			hint="Optional. Where there is one, every row must be in the account’s currency."
			error={err('currency')}
			bind:value={draft.currency}
		/>
	</fieldset>

	<fieldset class="flex flex-col gap-3" {disabled}>
		<legend class="mb-1 text-base font-semibold">Rows</legend>
		<ProfileField
			label="Placeholders"
			hint="One per line. A cell with exactly this text counts as empty."
			error={err('placeholders')}
			bind:value={draft.placeholders}
			multiline
		/>
		<Field
			label="Row filters"
			hint="A row is skipped when its cell equals the value (trimmed, case-sensitive) or matches it as a regular expression, before the cell is parsed. Use it for pending rows and for files of several currencies."
			error={err('filters')}
			group
		>
			{#each draft.filters as filter, index (index)}
				<div class="grid items-end gap-2 sm:grid-cols-[1fr_9rem_1fr_auto]" data-slot="filter-row">
					<ProfileField label={`Filter ${index + 1}: column`} bind:value={filter.column} />
					<Field label={`Filter ${index + 1}: test`}>
						{#snippet children(control)}
							<ChoiceSelect
								{...control}
								label={`Filter ${index + 1}: test`}
								value={filter.kind}
								options={[
									{ value: 'equals', label: 'equals' },
									{ value: 'matches', label: 'matches' }
								]}
								onchange={(next) => (filter.kind = next as 'equals' | 'matches')}
							/>
						{/snippet}
					</Field>
					<ProfileField label={`Filter ${index + 1}: value`} bind:value={filter.value} />
					<ActionButton
						type="button"
						variant="outline"
						onclick={() => removeFilter(index)}
						aria-label={`Remove filter ${index + 1}`}
					>
						Remove
					</ActionButton>
				</div>
			{/each}
			<div>
				<ActionButton type="button" variant="outline" onclick={addFilter}>Add filter</ActionButton>
			</div>
		</Field>
	</fieldset>

	<fieldset class="flex flex-col gap-3" {disabled}>
		<legend class="mb-1 text-base font-semibold">Balance and coverage</legend>
		<Field
			label="Balance"
			hint="The file’s balance becomes a balance record; without one the account reconciles against balances entered by hand."
			error={err('balance')}
		>
			{#snippet children(control)}
				<ChoiceSelect
					{...control}
					label="Balance"
					value={draft.balanceMode}
					options={[
						{ value: 'none', label: 'None' },
						{ value: 'running_column', label: 'A running-balance column' },
						{ value: 'labelled', label: 'A labelled figure' }
					]}
					onchange={(next) => (draft.balanceMode = next as CsvDraft['balanceMode'])}
				/>
			{/snippet}
		</Field>
		{#if draft.balanceMode === 'running_column'}
			<ProfileField
				label="Balance column"
				hint={`${COLUMN} The balance is the value after the last row before the export date.`}
				bind:value={draft.balanceColumn}
			/>
		{:else if draft.balanceMode === 'labelled'}
			<ProfileField
				label="Balance label"
				hint="The text of the cell that labels the figure, anywhere in the file: a cell that is exactly this text, else one that contains it."
				bind:value={draft.balanceLabel}
			/>
			<div class="grid grid-cols-2 gap-3">
				<ProfileField
					label="Balance: cells to the right"
					hint="Counted from the label cell."
					bind:value={draft.balanceRight}
					narrow
				/>
				<ProfileField
					label="Balance: rows below"
					hint="Counted from the label cell, in the same column."
					bind:value={draft.balanceBelow}
					narrow
				/>
			</div>
			<LocatedDateFields
				title="Balance date"
				hint="The date of the figure, if the file states one."
				error={err('balance.date')}
				bind:value={draft.balanceDate}
				anchored
			/>
		{/if}
		<LocatedDateFields
			title="Export date"
			hint="Without it the export date is the day of the upload."
			error={err('export_date')}
			bind:value={draft.exportDate}
			formatHint="Written with dd, d, MM, M, yyyy, HH, mm and ss."
		/>
		<LocatedDateFields
			title="Coverage end"
			hint="The period end the file states. Without it, coverage is the last booking date after filtering."
			error={err('coverage_end')}
			bind:value={draft.coverageEnd}
		/>
	</fieldset>

	<fieldset class="flex flex-col gap-3" {disabled}>
		<legend class="mb-1 text-base font-semibold">Statement payment</legend>
		<Field
			label="Statement payment"
			hint="For a card whose export lists purchases but not the payments that settle it: one synthetic payment per file nets the statement to zero. Off for a card that lists its payments."
			error={err('statement_payment')}
		>
			{#snippet children(control)}
				<ChoiceSelect
					{...control}
					label="Statement payment"
					value={draft.paymentOn ? 'yes' : 'no'}
					options={[
						{ value: 'no', label: 'Off' },
						{ value: 'yes', label: 'On' }
					]}
					onchange={(next) => (draft.paymentOn = next === 'yes')}
				/>
			{/snippet}
		</Field>
		{#if draft.paymentOn}
			<ProfileField
				label="Paying account reference"
				hint="The bank reference of the account that pays the card: it types the payment a transfer to that account."
				bind:value={draft.paymentRef}
			/>
			<ProfileField
				label="Payment purpose"
				hint="A text; {'{statement_date}'} stands for the coverage date, written YYYY-MM-DD."
				bind:value={draft.paymentPurpose}
			/>
			<ProfileField
				label="Days after the statement"
				hint="At least 1: the payment is dated the coverage date plus this many days."
				bind:value={draft.paymentOffset}
				narrow
			/>
		{/if}
	</fieldset>

	<fieldset class="flex flex-col gap-3" {disabled}>
		<legend class="mb-1 text-base font-semibold">Signs</legend>
		<div class="grid gap-3 sm:grid-cols-2">
			<Field
				label="Invert amounts"
				hint="For a source that shows purchases as positive. Applies to the instructed amount too."
				error={err('invert_amounts')}
			>
				{#snippet children(control)}
					<ChoiceSelect
						{...control}
						label="Invert amounts"
						value={draft.invertAmounts ? 'yes' : 'no'}
						options={YES_NO}
						onchange={(next) => (draft.invertAmounts = next === 'yes')}
					/>
				{/snippet}
			</Field>
			<Field
				label="Invert balance"
				hint="Separately from the amounts: a source that shows a debt as positive inverts both."
				error={err('invert_balance')}
			>
				{#snippet children(control)}
					<ChoiceSelect
						{...control}
						label="Invert balance"
						value={draft.invertBalance ? 'yes' : 'no'}
						options={YES_NO}
						onchange={(next) => (draft.invertBalance = next === 'yes')}
					/>
				{/snippet}
			</Field>
		</div>
	</fieldset>
</div>
