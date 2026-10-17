<script lang="ts">
	import { formatCount, formatDate, formatMoney } from '#lib/format/index.js';
	import type { DryRunReport } from '#lib/types/domain.js';

	// What a dry run carries, so that a profile can be judged before the file is used (ux/views/
	// importers.md "Uploading a file", step 2; plugins/importers/csv.md §7): the file as read (encoding,
	// delimiter, the header row, the columns mapped, the first rows as parsed), the counts with examples
	// by line number and reason (never cell content), the export date and the coverage with where each
	// came from, the balance record and the statement payment that would be written, and the
	// importer's warnings. The run summary as it would stand is the page's own component.
	let {
		report,
		currency,
		locale = 'en',
		failed = false
	}: {
		report: DryRunReport;
		currency: string;
		locale?: string;
		/** the run would end in a failure: it takes the place of the counts, the dates and the balance */
		failed?: boolean;
	} = $props();

	const count = (n: number) => formatCount(n, locale);
	const money = (minor: number) => formatMoney(minor, currency, { locale, showCurrency: true });
	const date = (iso: string) => formatDate(iso, locale);

	const counts = $derived(
		[
			{ key: 'skipped', label: 'Skipped as not transactions', category: report.skipped },
			{ key: 'filtered', label: 'Filtered by a row filter', category: report.filtered },
			{ key: 'zero', label: 'Dropped as zero bookings', category: report.zero_dropped },
			{
				key: 'currency',
				label: 'In another currency than the account’s',
				category: report.currency_mismatch
			}
		].filter((row) => row.category.count > 0)
	);
	const read = $derived(report.header_line !== null);
</script>

<div class="flex flex-col gap-4 text-sm" data-slot="upload-report">
	{#if read}
		<section class="flex flex-col gap-2" aria-label="The file as read">
			<h3 class="text-base font-semibold">The file as read</h3>
			<dl class="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-4 gap-y-1">
				{#if report.encoding}
					<dt class="text-muted-foreground">Encoding</dt>
					<dd>{report.encoding}</dd>
				{/if}
				{#if report.delimiter}
					<dt class="text-muted-foreground">Delimiter</dt>
					<dd><code>{report.delimiter}</code></dd>
				{/if}
				<dt class="text-muted-foreground">Header row</dt>
				<dd>line {report.header_line}</dd>
				<dt class="text-muted-foreground">Columns mapped</dt>
				<dd>
					{#if report.columns.length === 0}
						none
					{:else}
						<ul class="flex flex-col gap-0.5" data-slot="mapped-columns">
							{#each report.columns as column (column.field + column.index)}
								<li>
									<span class="font-medium">{column.field}</span>
									from <span>“{column.name}”</span>
									<span class="text-muted-foreground">(column {column.index})</span>
								</li>
							{/each}
						</ul>
					{/if}
				</dd>
			</dl>
			{#if report.sample.length > 0}
				<div class="overflow-x-auto rounded-lg border" data-slot="sample-rows">
					<table class="w-full text-left text-xs">
						<thead class="text-muted-foreground">
							<tr>
								<th class="px-2 py-1 font-medium">Line</th>
								<th class="px-2 py-1 font-medium">Booking date</th>
								<th class="px-2 py-1 text-right font-medium">Amount</th>
								<th class="px-2 py-1 font-medium">Cells</th>
							</tr>
						</thead>
						<tbody>
							{#each report.sample as row (row.row)}
								<tr class="border-t">
									<td class="px-2 py-1 tabular-nums">{row.row}</td>
									<td class="px-2 py-1 whitespace-nowrap">{date(row.booked_on)}</td>
									<td class="px-2 py-1 text-right whitespace-nowrap tabular-nums">
										{money(row.amount_minor)}
									</td>
									<td class="max-w-md truncate px-2 py-1 text-muted-foreground">
										{row.cells.join(' | ')}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{/if}

	{#if !report.failure && !failed}
		<section class="flex flex-col gap-2" aria-label="Counts">
			<h3 class="text-base font-semibold">Counts</h3>
			<dl class="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-4 gap-y-2" data-slot="counts">
				<dt class="text-muted-foreground">Rows read</dt>
				<dd>{count(report.rows_read)}</dd>
				<dt class="text-muted-foreground">Imported</dt>
				<dd>{count(report.emitted)}</dd>
				{#each counts as row (row.key)}
					<dt class="text-muted-foreground">{row.label}</dt>
					<dd class="flex flex-col gap-0.5">
						<span>{count(row.category.count)}</span>
						{#if row.category.examples.length > 0}
							<ul class="flex flex-col text-xs text-muted-foreground">
								{#each row.category.examples as example (example.row)}
									<li>line {example.row}: {example.reason}</li>
								{/each}
							</ul>
						{/if}
					</dd>
				{/each}
			</dl>
		</section>

		<section class="flex flex-col gap-2" aria-label="Dates and balance">
			<h3 class="text-base font-semibold">Dates and balance</h3>
			<dl class="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-4 gap-y-2" data-slot="dates">
				{#if report.export_date}
					<dt class="text-muted-foreground">Export date</dt>
					<dd>
						{date(report.export_date)}
						{#if report.export_date_source}
							<span class="text-muted-foreground">({report.export_date_source})</span>
						{/if}
					</dd>
				{/if}
				{#if report.coverage}
					<dt class="text-muted-foreground">Coverage</dt>
					<dd>
						through {date(report.coverage)}
						{#if report.coverage_source}
							<span class="text-muted-foreground">({report.coverage_source})</span>
						{/if}
					</dd>
				{/if}
				<dt class="text-muted-foreground">Balance record</dt>
				<dd data-slot="report-balance">
					{#if report.balance}
						{money(report.balance.amount_minor)} on {date(report.balance.dated_on)}
						<span class="text-muted-foreground">
							(the figure in the file: {money(report.balance.figure_minor)} on
							{date(report.balance.figure_on)}, {report.balance
								.source}{#if report.balance.rolled_back_rows > 0}, rolled back by {money(
									report.balance.rolled_back_by_minor
								)} over
								{count(report.balance.rolled_back_rows)}
								{report.balance.rolled_back_rows === 1 ? 'row' : 'rows'}{/if})
						</span>
					{:else}
						none; the account reconciles against balances entered by hand
					{/if}
				</dd>
				{#if report.synthetic}
					<dt class="text-muted-foreground">Statement payment</dt>
					<dd data-slot="report-synthetic">
						{money(report.synthetic.amount_minor)} on {date(report.synthetic.booked_on)}
						<span class="text-muted-foreground">
							(derived from the statement: the sum of {count(report.synthetic.row_count)}
							{report.synthetic.row_count === 1 ? 'row' : 'rows'}, {money(
								report.synthetic.sum_minor
							)})
						</span>
					</dd>
				{/if}
			</dl>
		</section>
	{/if}

	{#if report.warnings.length > 0}
		<section class="flex flex-col gap-1" aria-label="Warnings" data-slot="report-warnings">
			<h3 class="text-base font-semibold">Warnings</h3>
			<ul class="flex list-disc flex-col gap-0.5 pl-5">
				{#each report.warnings as warning, i (i)}
					<li>{warning}</li>
				{/each}
			</ul>
		</section>
	{/if}
</div>
