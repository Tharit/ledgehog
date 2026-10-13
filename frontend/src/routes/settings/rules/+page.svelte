<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount } from 'svelte';
	import NoticeLine from '#lib/components/common/notice-line.svelte';
	import PageHeader from '#lib/components/common/page-header.svelte';
	import RuleDeleteDialog from '#lib/components/rules/rule-delete-dialog.svelte';
	import RuleList from '#lib/components/rules/rule-list.svelte';
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

	// the line holds one notice: what an editor settled, with the lists that did not load after it
	const notice = $derived.by(() => {
		const parts = [
			store.notice,
			store.lookupsFailed.length > 0
				? `Some lists could not be loaded (${store.lookupsFailed.join(', ')}); their names may be missing below.`
				: null
		].filter((part) => part !== null);
		return parts.length > 0 ? { text: parts.join(' '), error: false } : null;
	});
</script>

<svelte:head>
	<title>Rules · Settings · Ledgehog</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<PageHeader
		title="Rules"
		description="A rule decides entries for good, without review. They are tried in this order: counter-account rules, then payee rules, then category rules; within each, the lower priority first."
		actionLabel="Add rule"
		actionHref={NEW_RULE_PATH}
	/>

	<NoticeLine {notice} />

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
