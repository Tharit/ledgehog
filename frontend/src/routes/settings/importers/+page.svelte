<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount } from 'svelte';
	import AddImporterDialog from '#lib/components/importers/add-importer-dialog.svelte';
	import ImporterList from '#lib/components/importers/importer-list.svelte';
	import InstanceDecisionDialog from '#lib/components/importers/instance-decision-dialog.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import { IMPORTERS_PATH, instanceUrl, newImporterUrl } from '#lib/importers/links.js';
	import { refreshNotice, startRefresh } from '#lib/importers/refresh.js';
	import { sync } from '#lib/stores/sync.svelte.js';
	import { describeImporterError, doneFromSearch } from '#lib/importers/messages.js';
	import { ImporterListStore } from '#lib/stores/importer-list.svelte.js';
	import { refetchOnChange } from '#lib/stores/new-data.svelte.js';

	const store = new ImporterListStore();
	let adding = $state(false);
	// a refused "Refresh accounts" stays here, as a notice; a busy one links to the running task
	let refused = $state<ReturnType<typeof refreshNotice> | null>(null);

	async function refresh(instanceId: number) {
		refused = null;
		const refusal = await startRefresh(instanceId, {
			start: (id) => sync.startDiscovery(id),
			go: (path) => goto(path)
		});
		if (refusal) refused = refreshNotice(refusal, sync.status === 'idle' ? '/sync' : sync.homePath);
	}

	onMount(() => {
		// a page that saved or deleted sends what settled in the address; say it once, then tidy
		const done = doneFromSearch(page.url.search);
		if (done) {
			store.say(done);
			void goto(IMPORTERS_PATH, { replaceState: true });
		}
		void store.load();
	});
	onDestroy(() => store.dispose());
	// not a snapshot: "last ran" moves with every write
	refetchOnChange('ledger', () => void store.load());
</script>

<svelte:head>
	<title>Importers · Settings · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		title="Importers"
		description="An importer reads a statement export into the accounts linked to it. One importer holds the settings of one file format."
		actionLabel="Add importer"
		onaction={() => (adding = true)}
		actionDisabled={store.status !== 'ready'}
	/>

	<NoticeLine notice={refused ?? store.notice}>
		{#snippet action()}
			{#if refused?.action}
				{@const go = refused.action}
				<ActionButton variant="link" class="h-auto p-0" href={go.path}>{go.label}</ActionButton>
			{/if}
		{/snippet}
	</NoticeLine>

	<ImporterList
		instances={store.instances}
		catalog={store.catalog}
		status={store.status}
		lookups={store.lookups}
		locale={store.locale}
		timeZone={store.timeZone}
		busy={store.busy}
		failure={store.error ? describeImporterError(store.error) : null}
		onadd={() => (adding = true)}
		onretry={() => store.load()}
		onedit={(instance) => void goto(instanceUrl(instance.id))}
		onlink={(instance) => void goto(instanceUrl(instance.id, { linkAccount: true }))}
		onrefresh={(instance) => void refresh(instance.id)}
		ontoggle={(instance) => store.setDisabled(instance, !instance.disabled)}
		onreset={(instance) => store.decision.start('reset', instance)}
		ondelete={(instance) => store.decision.start('delete', instance)}
	/>
</div>

<AddImporterDialog
	open={adding}
	catalog={store.catalog}
	onclose={() => (adding = false)}
	onpick={(name) => {
		adding = false;
		void goto(newImporterUrl(name));
	}}
/>
<InstanceDecisionDialog flow={store.decision} lookups={store.lookups} />
