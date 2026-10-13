// State of the tags screen: the list and the writes (add, rename or recolour, delete). The list
// is reloaded after every write and handed to the shared lookups, so the ledger's filter bar and
// tag popover see the change. No domain computation here.
import { ApiError, createTag, deleteTag, listTags, updateTag } from '#lib/api/index.js';
import { attempt } from '#lib/dimensions/attempt.js';
import { needsReload, type Outcome } from '#lib/dimensions/errors.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import type { Tag } from '#lib/types/domain.js';
import { indexTags, tagDeletedNotice } from './summary.js';

export type TagsStatus = 'loading' | 'ready' | 'error';
export type TagsNotice = { text: string; error: boolean };

/** What an edit sets: `null` clears the colour, absent stays. */
export type TagPatch = { name?: string; color?: string | null };

export class TagsStore {
	tags = $state.raw<Tag[]>([]);
	status = $state<TagsStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	notice = $state.raw<TagsNotice | null>(null);

	readonly byId = $derived(indexTags(this.tags));

	/** Load the list. `quiet` keeps what is shown (a reload after a write). */
	async load(quiet = false): Promise<void> {
		if (!quiet) this.status = 'loading';
		try {
			this.tags = await listTags();
			lookupsStore.setTags(this.tags);
			this.status = 'ready';
			this.error = null;
		} catch (error) {
			if (quiet && this.status === 'ready') return;
			this.error =
				error instanceof ApiError
					? error
					: new ApiError(0, 'network_error', 'The server could not be reached.');
			this.status = 'error';
		}
	}

	notify(text: string, error = false): void {
		this.notice = { text, error };
	}

	async #after<T>(outcome: Outcome<T>): Promise<Outcome<T>> {
		if (outcome.ok || needsReload(outcome.failure)) await this.load(true);
		return outcome;
	}

	async create(name: string, color: string | null = null): Promise<Outcome<Tag>> {
		const outcome = await this.#after(await attempt(() => createTag(name, color)));
		return outcome.ok ? { ok: true, value: outcome.value.tag } : outcome;
	}

	async update(id: number, patch: TagPatch): Promise<Outcome<Tag>> {
		const outcome = await this.#after(await attempt(() => updateTag(id, patch)));
		return outcome.ok ? { ok: true, value: outcome.value.tag } : outcome;
	}

	/** Delete; on success the notice names the entries that lost the tag. */
	async remove(tag: Tag): Promise<Outcome<number>> {
		const outcome = await this.#after(await attempt(() => deleteTag(tag.id)));
		if (!outcome.ok) return outcome;
		this.notify(tagDeletedNotice(tag.name, outcome.value.removed_memberships));
		return { ok: true, value: outcome.value.removed_memberships };
	}
}
