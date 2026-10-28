<script lang="ts">
	import DimensionIcon from '#lib/components/common/dimension-icon.svelte';
	import DateField from '#lib/components/common/date-field.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { resolveAccount } from '#lib/theme/resolve.js';
	import { formatDate } from '#lib/format/index.js';
	import { sinceSourceText } from '#lib/sync/plan.js';
	import type { AccountInfo } from '#lib/sync/progress.js';
	import type { PlanAccount } from '#lib/types/domain.js';

	// An account of a login in the plan (ux/views/sync.md "Starting"): its start in words, and only for
	// an account without coverage a date field labelled "Start", prefilled, the start for this run
	// (spec §5.4). An account with coverage shows its start and cannot change it.
	let {
		account,
		info = null,
		start = '',
		disabled = false,
		locale = 'en',
		onchange
	}: {
		account: PlanAccount;
		info?: AccountInfo | null;
		/** the start the user chose; empty means the plan's own */
		start?: string;
		disabled?: boolean;
		locale?: string;
		onchange?: (start: string) => void;
	} = $props();

	const name = $derived(info?.name ?? `Account ${account.account_id}`);
	const words = $derived(sinceSourceText(account.since_source));
</script>

<li
	class="flex flex-wrap items-center gap-x-4 gap-y-1 py-1.5 text-[13px]"
	data-slot="plan-account"
	data-editable={account.editable}
>
	<span class="flex min-w-40 items-center gap-2 font-medium">
		{#if info}<DimensionIcon {...resolveAccount(info)} />{/if}
		<span>{name}</span>
	</span>
	{#if account.editable}
		<div class="w-44">
			<Field label="Start">
				{#snippet children(control)}
					<DateField
						{...control}
						label={`Start of ${name}`}
						{locale}
						{disabled}
						value={start || account.since}
						onchange={(value) => onchange?.(value)}
					/>
				{/snippet}
			</Field>
		</div>
		<span class="text-muted-foreground" data-slot="plan-since">
			nothing fetched yet · {words}
		</span>
	{:else}
		<span class="text-muted-foreground" data-slot="plan-since">
			from {formatDate(account.since, locale)} · {words}
		</span>
	{/if}
</li>
