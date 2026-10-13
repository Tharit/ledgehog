// The lists the rule screens resolve ids against (targets, payee conditions, preview rows):
// accounts, categories and payees, from the shared lookups (stores/lookups.svelte.ts), refetched
// so a rule screen never shows a stale name. A list that cannot be loaded is simply empty and
// named, so the screen can say so in one quiet line. Tags are not the rule screens' business.
import type { Lookups } from '#lib/ledger/lookups.js';
import { lookupsStore } from './lookups.svelte.js';

export async function loadRuleLookups(): Promise<{ lookups: Lookups; failed: string[] }> {
	await lookupsStore.reload();
	return {
		lookups: lookupsStore.lookups,
		failed: lookupsStore.failed.filter((name) => name !== 'tags')
	};
}
