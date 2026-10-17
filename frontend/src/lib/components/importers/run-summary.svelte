<script lang="ts">
	import { formatCount, formatDate, formatDateRange, formatMoney } from '#lib/format/index.js';
	import { accountUrl } from '#lib/importers/links.js';
	import { isDifference, statsOf, type RunSummaryInput } from '#lib/importers/run.js';

	// The run summary (ux/views/importers.md "The run summary"; patterns §8): a report, not an alarm.
	// It says per account what a run did and opens nothing: rows inserted, inserted as duplicates
	// (each "of #N", a link to the row it duplicates on the account's statement, and a link to the
	// duplicate itself), skipped by identity, what the importer left out, the balance record written,
	// the coverage, and the unexplained difference before and after. A failed run shows its error.
	// `run` is a stored run or a dry run in the same shape (`dryRunAsRun`); for a dry run the new
	// duplicates are not linked, since they were rolled back. `currency` is the account's: the amounts
	// of the statistics arrive as minor units, and the server states a currency only where there is one.
	let {
		run,
		currency,
		dryRun = false,
		locale = 'en'
	}: {
		run: RunSummaryInput;
		currency: string;
		dryRun?: boolean;
		locale?: string;
	} = $props();

	const stats = $derived(statsOf(run));
	const account = $derived(run.account_id);
	const money = (minor: number | null) =>
		minor === null ? 'none' : formatMoney(minor, currency, { locale, showCurrency: true });
	const rows = (n: number) => `${formatCount(n, locale)} ${n === 1 ? 'row' : 'rows'}`;
	const link = 'underline underline-offset-2 hover:no-underline';

	const left = $derived.by(() => {
		const parts: string[] = [];
		const zero = stats.importer.filtered ?? 0;
		if (zero > 0) parts.push(`${rows(zero)} dropped as zero bookings`);
		if ((stats.importer.synthetic_skipped ?? 0) > 0) {
			parts.push('the statement payment was not emitted');
		}
		return parts;
	});
	const coverage = $derived(
		run.covered_through
			? run.covered_from
				? formatDateRange(run.covered_from, run.covered_through, locale)
				: `up to ${formatDate(run.covered_through, locale)}`
			: null
	);
	const difference = $derived(stats.unexplained_difference);
	const stays = $derived(isDifference(difference.after));
</script>

<section class="flex flex-col gap-3 text-sm" data-slot="run-summary" data-status={run.status}>
	{#if run.status === 'failed'}
		<p data-slot="run-error" class="flex flex-col gap-1">
			<span class="font-medium">This run failed. Nothing was imported.</span>
			<span class="text-muted-foreground">{run.error_text ?? 'No error was recorded.'}</span>
		</p>
	{:else if run.status === 'running'}
		<p class="text-muted-foreground" aria-busy="true">This run has not finished.</p>
	{:else}
		{#if run.status === 'reverted'}
			<p class="text-muted-foreground">This run was reverted; what it inserted was removed.</p>
		{/if}
		<dl class="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-4 gap-y-2">
			<dt class="text-muted-foreground">{dryRun ? 'Would insert' : 'Inserted'}</dt>
			<dd data-slot="run-inserted">{rows(stats.inserted)}</dd>

			<dt class="text-muted-foreground">Skipped by identity</dt>
			<dd data-slot="run-skipped">
				{rows(stats.skipped_by_identity)}
				{#if stats.skipped_by_identity > 0}
					<span class="text-muted-foreground">(already imported)</span>
				{/if}
			</dd>

			<dt class="text-muted-foreground">
				{dryRun ? 'Would be duplicates' : 'Inserted as duplicates'}
			</dt>
			<dd data-slot="run-duplicates">
				{#if stats.inserted_as_duplicates.length === 0}
					none
				{:else}
					<ul class="flex flex-col gap-0.5">
						{#each stats.inserted_as_duplicates as dup (dup.id)}
							<li>
								{#if account === null || dryRun}
									A new row
								{:else}
									<a href={accountUrl(account, dup.id)} class={link}>Row #{dup.id}</a>
								{/if}
								of
								{#if account === null}
									#{dup.duplicate_of}
								{:else}
									<a href={accountUrl(account, dup.duplicate_of)} class={link}
										>#{dup.duplicate_of}</a
									>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</dd>

			{#if left.length > 0}
				<dt class="text-muted-foreground">Left out by the importer</dt>
				<dd data-slot="run-left-out">{left.join('; ')}</dd>
			{/if}

			{#if stats.balance}
				<dt class="text-muted-foreground">Balance record</dt>
				<dd data-slot="run-balance">
					{money(stats.balance.balance)} on {formatDate(stats.balance.balance_on, locale)}
				</dd>
			{/if}

			{#if coverage}
				<dt class="text-muted-foreground">Coverage</dt>
				<dd data-slot="run-coverage">{coverage}</dd>
			{/if}

			<dt class="text-muted-foreground">Unexplained difference</dt>
			<dd data-slot="run-difference" class="flex flex-col gap-0.5">
				<span>
					Before: {money(difference.before)}. After: {money(difference.after)}.
				</span>
				{#if stays && stats.since_zero.length > 0}
					<span class="text-muted-foreground">
						It lies since
						{#if account !== null}
							<a href={accountUrl(account)} class={link} data-slot="run-records">
								{stats.since_zero.length === 1
									? 'the reported record'
									: `${stats.since_zero.length} reported records`}
							</a>
						{:else}
							{stats.since_zero.length === 1
								? 'the reported record'
								: `${stats.since_zero.length} reported records`}
						{/if}
						on the statement.
					</span>
				{/if}
			</dd>
		</dl>
	{/if}
</section>
