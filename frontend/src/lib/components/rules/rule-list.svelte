<script lang="ts">
	import Trash2Icon from '@lucide/svelte/icons/trash-2';
	import EmptyState from '#lib/components/common/empty-state.svelte';
	import ErrorState from '#lib/components/common/error-state.svelte';
	import RowActions from '#lib/components/common/row-actions.svelte';
	import { DEFAULT_PRIORITY, SETS_INFO, targetId } from '#lib/rules/form.js';
	import { groupRules } from '#lib/rules/groups.js';
	import type { Lookups } from '#lib/ledger/lookups.js';
	import { NEW_RULE_PATH, ruleUrl } from '#lib/rules/links.js';
	import { summarizeConditions } from '#lib/rules/summary.js';
	import type { Rule } from '#lib/rules/types.js';
	import RuleTarget from './rule-target.svelte';

	// The rules, grouped by what they set and in evaluation order within each group (spec §5.9):
	// a name, what it asks for in one line, what it sets. Priority shows only when it is not the
	// default. Comfortable density: 48px rows with a second line (design §5). A row's primary
	// action is its name, a link to the editor; its one other action, "Delete…", is an inline icon
	// button (patterns §11.3).
	let {
		rules,
		status,
		lookups,
		failure = null,
		onretry,
		ondelete
	}: {
		rules: readonly Rule[];
		status: 'loading' | 'ready' | 'error';
		lookups: Lookups;
		/** why the list could not be loaded, in words */
		failure?: string | null;
		onretry?: () => void;
		ondelete?: (rule: Rule) => void;
	} = $props();

	const groups = $derived(groupRules(rules));
	const payeeName = (id: number) => lookups.payees.get(id)?.name;
</script>

{#if status === 'error'}
	<ErrorState
		title="The rules could not be loaded"
		message={failure ?? 'The server could not answer this request.'}
		{onretry}
	/>
{:else if status === 'loading'}
	<div class="flex flex-col gap-2" aria-busy="true" data-slot="rules-loading">
		{#each [0, 1, 2, 3] as i (i)}
			<div class="h-12 animate-pulse rounded-lg bg-muted"></div>
		{/each}
	</div>
{:else if rules.length === 0}
	<EmptyState title="No rules yet" actionLabel="Add rule" actionHref={NEW_RULE_PATH}>
		A rule decides entries for good, without review: it says which entries it matches and what it
		sets on them.
	</EmptyState>
{:else}
	<div class="flex flex-col gap-6">
		{#each groups as group (group.sets)}
			<section aria-label={SETS_INFO[group.sets].group} class="flex flex-col gap-1">
				<h2 class="text-base font-semibold">{SETS_INFO[group.sets].group}</h2>
				<ul class="flex flex-col rounded-xl border bg-card shadow-card">
					{#each group.rules as rule (rule.id)}
						<li
							class="group grid min-h-12 grid-cols-[minmax(0,1fr)_minmax(0,14rem)_auto] items-center gap-x-4 border-b border-border px-4 py-1.5 last:border-b-0"
							data-rule-id={rule.id}
						>
							<div class="flex min-w-0 flex-col">
								<span class="flex min-w-0 items-baseline gap-2">
									<a
										href={ruleUrl(rule.id)}
										class="truncate text-sm font-medium underline-offset-2 hover:underline"
									>
										{rule.name}
									</a>
									{#if rule.priority !== DEFAULT_PRIORITY}
										<span class="shrink-0 text-xs text-muted-foreground">
											priority {rule.priority}
										</span>
									{/if}
								</span>
								<span
									class="truncate text-xs text-muted-foreground"
									title={summarizeConditions(rule, payeeName)}
								>
									{summarizeConditions(rule, payeeName)}
								</span>
							</div>
							<div class="flex min-w-0 items-center text-sm">
								<RuleTarget sets={group.sets} id={targetId(rule)} {lookups} />
							</div>
							<RowActions
								name={rule.name}
								primary={[
									{
										verb: 'Delete…',
										label: `Delete the rule ${rule.name}`,
										icon: Trash2Icon,
										onselect: () => ondelete?.(rule)
									}
								]}
							/>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	</div>
{/if}
