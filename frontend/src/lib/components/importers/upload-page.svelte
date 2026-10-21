<script lang="ts">
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import { onDestroy, onMount } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Field from '#lib/components/common/field.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { accountUrl, instanceUrl } from '#lib/importers/links.js';
	import { describeImporterError, describeUploadFailure } from '#lib/importers/messages.js';
	import { dryRunAsRun } from '#lib/importers/run.js';
	import { ImporterUploadStore } from '#lib/stores/importer-upload.svelte.js';
	import RunSummary from './run-summary.svelte';
	import UploadReport from './upload-report.svelte';

	// The upload page of an account (ux/views/importers.md "Uploading a file"): one page, three steps.
	// Choosing the file starts the dry run at once; the report shows what the profile makes of it, so
	// it can be judged before the file is used; "Upload" runs the real operation with the same file
	// and the page becomes the run summary. "Edit profile" opens the instance's page in a new tab and
	// "Check again" reruns the dry run on the same file; the page keeps the file.
	let { accountId, instanceId }: { accountId: number; instanceId: number } = $props();

	// made once per page: the route keys it by the account and the instance
	const make = () => new ImporterUploadStore({ accountId, instanceId });
	const store = make();

	onMount(() => void store.init());
	onDestroy(() => store.dispose());

	const account = $derived(store.account);
	const currency = $derived(account?.currency ?? '');
	const dry = $derived(store.dry);
	const back = $derived(accountUrl(accountId));
	const description = $derived(
		account && store.instance ? `${account.name} · ${store.instance.label}` : undefined
	);
	const checking = $derived(store.phase === 'checking');
	const uploading = $derived(store.phase === 'uploading');
	const notice = $derived(store.notice ? { text: store.notice, error: false } : null);

	function onfile(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		void store.choose(input.files?.[0] ?? null);
	}
</script>

<div class="flex flex-col gap-4">
	<a
		href={back}
		class="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground underline-offset-2 hover:underline"
	>
		<ArrowLeftIcon size={14} strokeWidth={1.75} aria-hidden="true" />
		{account ? account.name : 'The account'}
	</a>
	<PageHeader level={1} title="Upload a file" {description} />

	<NoticeLine {notice} />

	{#if store.loadStatus === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading…</p>
	{:else if store.loadStatus === 'missing'}
		<ErrorState
			title="Nothing to upload to"
			message="The account or the importer does not exist (any more), or the address does not name them."
		/>
		<ActionButton variant="outline" href={back} class="w-fit">Back to the account</ActionButton>
	{:else if store.loadStatus === 'error'}
		<ErrorState
			title="The importer could not be loaded"
			message={store.loadError ? describeImporterError(store.loadError) : ''}
			onretry={() => store.init()}
		/>
	{:else if store.phase === 'done' && store.run}
		<div
			class="flex max-w-3xl flex-col gap-4 rounded-xl border bg-card p-5 shadow-card"
			data-slot="upload-done"
		>
			<h2 class="text-base font-semibold">The file was uploaded</h2>
			<RunSummary run={store.run} {currency} locale={store.locale} />
			<div>
				<ActionButton href={back}>Back to the account</ActionButton>
			</div>
		</div>
	{:else}
		<div class="flex max-w-3xl flex-col gap-5 rounded-xl border bg-card p-5 shadow-card">
			<Field
				label="File"
				hint="For this account only; up to 10 MiB. Choosing it checks it at once, and nothing is written until you upload it."
			>
				{#snippet children(control)}
					<Input
						{...control}
						type="file"
						accept=".csv,.txt,.xls,.xlsx,.ods,text/csv,text/plain,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.oasis.opendocument.spreadsheet"
						disabled={store.blocked !== null || uploading}
						onchange={onfile}
					/>
				{/snippet}
			</Field>

			{#if checking}
				<p class="text-muted-foreground" aria-busy="true" data-slot="checking">
					Checking the file…
				</p>
			{:else if dry}
				<section class="flex flex-col gap-4" aria-label="The report" data-slot="report">
					{#if dry.failure}
						<div
							class="flex flex-col gap-1 rounded-lg border bg-muted/40 p-3 text-sm"
							data-slot="report-failure"
						>
							<p class="font-medium">Uploading this file would fail. Nothing would be imported.</p>
							<p class="text-muted-foreground">{describeUploadFailure(dry.failure)}</p>
						</div>
					{/if}
					<UploadReport
						report={dry.report}
						{currency}
						locale={store.locale}
						failed={dry.failure !== null}
					/>
					{#if !dry.failure}
						<div class="flex flex-col gap-2">
							<h3 class="text-base font-semibold">As the run would stand</h3>
							<RunSummary
								run={dryRunAsRun(dry, accountId)}
								{currency}
								locale={store.locale}
								dryRun
							/>
						</div>
					{/if}
					<div class="flex flex-wrap gap-2">
						<ActionButton
							variant="outline"
							href={instanceUrl(instanceId)}
							target="_blank"
							rel="noopener"
						>
							Edit profile
						</ActionButton>
						<ActionButton
							variant="outline"
							busy={checking}
							busyLabel="Checking…"
							disabled={uploading}
							onclick={() => void store.check()}
						>
							Check again
						</ActionButton>
					</div>
				</section>
			{/if}

			{#if store.blocked}
				<p role="alert" class="text-sm text-destructive" data-slot="blocked">
					{describeImporterError(store.blocked)}
				</p>
			{/if}
			{#if store.refusal}
				<p role="alert" class="text-sm text-destructive" data-slot="refusal">{store.refusal}</p>
			{/if}

			<div class="flex justify-end gap-2">
				<ActionButton variant="outline" href={back} disabled={uploading}>Cancel</ActionButton>
				<ActionButton
					busy={uploading}
					busyLabel="Uploading…"
					disabled={store.uploadBlocked !== null}
					reason={store.uploadBlocked ?? undefined}
					onclick={() => void store.commit()}
				>
					Upload
				</ActionButton>
			</div>
		</div>
	{/if}
</div>
