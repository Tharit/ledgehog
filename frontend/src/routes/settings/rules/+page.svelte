<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount } from 'svelte';
	import Notice from '#lib/components/common/notice.svelte';
	import RuleDeleteDialog from '#lib/components/rules/rule-delete-dialog.svelte';
	import RuleList from '#lib/components/rules/rule-list.svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { NEW_RULE_PATH, RULES_PATH } from '#lib/rules/links.js';
	import { describeRuleError, doneFromSearch } from '#lib/rules/messages.js';
	import { RuleListStore } from '#lib/stores/rule-list.svelte.js';

	const store = new RuleListStore();

	onMount(() => {
		// an editor that saved or deleted sends what settled in the address; say it once, then tidy
		const done = doneFromSearch(page.url.search);
		if (done) {
			store.say(done);
			void goto(RULES_PATH, { replaceState: true });
		}
		void store.load();
	});
	onDestroy(() => store.dispose());
</script>

<svelte:head>
	<title>Rules · Settings · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<p class="max-w-prose text-sm text-muted-foreground">
			A rule decides entries for good, without review. They are tried in this order: counter-account
			rules, then payee rules, then category rules; within each, the lower priority first.
		</p>
		<Button href={NEW_RULE_PATH}>Add rule</Button>
	</div>

	<!-- one reserved line, so a notice appearing never moves the list (patterns §7) -->
	<div class="flex min-h-5 flex-col gap-1">
		{#if store.notice}
			<Notice>{store.notice}</Notice>
		{/if}
		{#if store.lookupsFailed.length > 0}
			<Notice>
				Some lists could not be loaded ({store.lookupsFailed.join(', ')}); their names may be
				missing below.
			</Notice>
		{/if}
	</div>

	<RuleList
		rules={store.rules}
		status={store.status}
		lookups={store.lookups}
		failure={store.error ? describeRuleError(store.error, store.locale) : null}
		onretry={() => store.load()}
		ondelete={(rule) => store.remove.start(rule)}
	/>
</div>

<RuleDeleteDialog flow={store.remove} locale={store.locale} />
