<script lang="ts">
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import { onDestroy, onMount } from 'svelte';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import Field from '#lib/components/common/field.svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import LeaveGuard from '#lib/components/rules/leave-guard.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { InstanceDecisionFlow } from '#lib/importers/decision-flow.svelte.js';
	import { LinkAccountFlow } from '#lib/importers/link-flow.svelte.js';
	import { IMPORTERS_PATH, instanceUrl } from '#lib/importers/links.js';
	import { describeImporterError, doneText, doneUrl } from '#lib/importers/messages.js';
	import { SETTLE_STALE } from '#lib/ledger/errors.js';
	import { ImporterEditorStore } from '#lib/stores/importer-editor.svelte.js';
	import { lookupsStore } from '#lib/stores/lookups.svelte.js';
	import { session } from '#lib/stores/session.svelte.js';
	import type { Account } from '#lib/types/domain.js';
	import ImporterSettings from './importer-settings.svelte';
	import InstanceDecisionDialog from './instance-decision-dialog.svelte';
	import LinkAccountDialog from './link-account-dialog.svelte';
	import LinkedAccounts from './linked-accounts.svelte';

	// The instance page, add (`instanceId` null, `importer` named) or edit (ux/views/importers.md "The
	// instance page"): a draft editor (patterns §11.2) with "Save importer" and Cancel, the label and
	// the importer's own settings, and, for an instance already saved, its linked accounts. Leaving,
	// after a save, is the route's business (`onleave`, with the address to go to). `intent` says how
	// the page was reached: `added` right after saving a new instance, `link` from the list's "Link
	// account"; both open the link dialog at once, once, and `ontidy` lets the route drop it.
	let {
		instanceId = null,
		importer = null,
		intent = null,
		onleave,
		ontidy
	}: {
		instanceId?: number | null;
		importer?: string | null;
		intent?: 'added' | 'link' | null;
		onleave: (url: string) => void;
		ontidy?: () => void;
	} = $props();

	// made once per page: the route keys it by what it edits
	const make = () => new ImporterEditorStore({ instanceId, importer });
	const store = make();
	let leaving = $state(false);
	let notice = $state<{ text: string; error: boolean } | null>(null);

	function leave(url: string) {
		leaving = true;
		onleave(url);
	}

	const say = (text: string, settleFailed = false) =>
		(notice = { text: settleFailed ? `${text} ${SETTLE_STALE}` : text, error: false });

	const accountName = (id: number) =>
		lookupsStore.lookups.accounts.get(id)?.name ?? `Account #${id}`;

	const link = new LinkAccountFlow({
		linked: (instance, accountId, settleFailed) => {
			store.replaceInstance(instance);
			say(
				doneText({ action: 'linked', label: instance.label, account: accountName(accountId) }),
				settleFailed
			);
			// the account is synced now: its facts changed
			void lookupsStore.reload();
		},
		gone: () => leave(IMPORTERS_PATH)
	});
	const decision = new InstanceDecisionFlow({
		done: (_kind, instance, now, accountId, settleFailed) => {
			if (now) store.replaceInstance(now);
			say(
				doneText({
					action: 'unlinked',
					label: instance.label,
					account: accountId === null ? 'The account' : accountName(accountId)
				}),
				settleFailed
			);
			void lookupsStore.reload();
		},
		gone: () => leave(IMPORTERS_PATH)
	});

	/** open accounts the instance does not link yet */
	const linkable = $derived.by<Account[]>(() => {
		const linked = new Set(store.instance?.accounts.map((a) => a.account_id));
		return [...lookupsStore.lookups.accounts.values()].filter(
			(a) => a.closed_on === null && !linked.has(a.id)
		);
	});

	onMount(async () => {
		void lookupsStore.ensure();
		await store.init();
		const stored = store.instance;
		if (intent && stored) {
			if (intent === 'added') {
				say(`Importer “${stored.label}” was added. Link an account to use it.`);
			}
			if (!stored.disabled && stored.emits.includes('transactions')) link.start(stored);
			ontidy?.();
		}
	});
	onDestroy(() => {
		store.dispose();
		link.close();
		decision.close();
	});

	async function save() {
		const result = await store.save();
		if (!result) return;
		leave(
			result.created
				? instanceUrl(result.instance.id, { added: true })
				: doneUrl({ action: 'saved', label: result.instance.label })
		);
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
			event.preventDefault();
			void save();
		}
	}

	const title = $derived(store.editing ? (store.instance?.label ?? 'Importer') : 'Add importer');
	const description = $derived(
		store.editing
			? 'Change the importer’s settings. Saving changes later uploads only: rows already imported keep saying what the file said.'
			: `Name the importer and describe the file format${store.importer ? ` (${store.importer})` : ''}. Link an account once it is saved, then check the profile with a dry run on the upload page.`
	);
	const locale = $derived(session.config?.locale ?? 'en');
</script>

<LeaveGuard dirty={store.dirty && !leaving} subject="this importer" />

<div class="flex flex-col gap-4">
	<a
		href={IMPORTERS_PATH}
		class="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground underline-offset-2 hover:underline"
	>
		<ArrowLeftIcon size={14} strokeWidth={1.75} aria-hidden="true" />
		All importers
	</a>
	<PageHeader {title} {description} />

	<NoticeLine {notice} />

	{#if store.loadStatus === 'loading'}
		<p class="text-sm text-muted-foreground" aria-busy="true">Loading…</p>
	{:else if store.loadStatus === 'missing'}
		<ErrorState
			title={store.editing ? 'This importer does not exist' : 'This importer is not available'}
			message={store.editing
				? 'It may have been deleted.'
				: 'This deployment does not register the importer named in the address.'}
		/>
		<ActionButton variant="outline" href={IMPORTERS_PATH} class="w-fit">
			Back to the importers
		</ActionButton>
	{:else if store.loadStatus === 'error'}
		<ErrorState
			title="The importer could not be loaded"
			message={store.loadError ? describeImporterError(store.loadError) : ''}
			onretry={() => store.init()}
		/>
	{:else if store.importer}
		<!-- one explicit save button; Enter in a field does not submit (⌘/Ctrl+Enter does) -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<form
			class="flex max-w-3xl flex-col gap-6 rounded-xl border bg-card p-5 shadow-card"
			aria-label="Importer"
			onsubmit={(event) => event.preventDefault()}
			{onkeydown}
		>
			{#if !store.editing && store.presetNames.length > 0}
				<Field
					label="Start from a preset"
					hint="Fills the form below as a draft. Nothing is saved until you save the importer, and Cancel discards it."
				>
					{#snippet children(control)}
						<ChoiceSelect
							{...control}
							label="Start from a preset"
							value={store.preset}
							options={[
								{ value: '', label: 'No preset' },
								...store.presetNames.map((name) => ({ value: name, label: name }))
							]}
							disabled={store.saving}
							onchange={(next) => (next === '' ? (store.preset = '') : store.choosePreset(next))}
						/>
					{/snippet}
				</Field>
			{/if}

			<Field
				label="Label"
				hint="The importer’s one name. Rows it imports say csv: and this label as their source format, so it is read from here."
				error={store.errorFor('label')}
			>
				{#snippet children(control)}
					<Input {...control} bind:value={store.label} readonly={store.saving} autocomplete="off" />
				{/snippet}
			</Field>

			<ImporterSettings
				importer={store.importer}
				draft={store.draft}
				errors={store.errors}
				disabled={store.saving}
			/>

			{#if store.failure}
				<p role="alert" class="text-sm text-destructive" data-slot="save-failure">
					{store.failure}
				</p>
			{/if}

			<div class="flex justify-end gap-2">
				<ActionButton variant="outline" href={IMPORTERS_PATH} disabled={store.saving}>
					Cancel
				</ActionButton>
				<ActionButton
					busy={store.saving}
					busyLabel="Saving…"
					disabled={!store.label.trim()}
					reason={!store.label.trim() ? 'Give the importer a label first.' : undefined}
					onclick={() => void save()}
				>
					Save importer
				</ActionButton>
			</div>
		</form>

		{#if store.editing && store.instance}
			<div class="max-w-3xl">
				<LinkedAccounts
					instance={store.instance}
					lookups={lookupsStore.lookups}
					onlink={() => store.instance && link.start(store.instance)}
					onunlink={(accountId) =>
						store.instance && decision.start('unlink', store.instance, accountId)}
				/>
			</div>
		{/if}
	{/if}
</div>

<LinkAccountDialog flow={link} accounts={linkable} {locale} />
<InstanceDecisionDialog flow={decision} lookups={lookupsStore.lookups} />
