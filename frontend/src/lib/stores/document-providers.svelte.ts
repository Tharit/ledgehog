// The providers of the registered document importers: the options of the documents list's provider
// chip. Fetched when a screen needs it; a failed fetch keeps what is held (an empty list at first).
import { listDocumentProviders } from '#lib/api/index.js';

export class DocumentProvidersStore {
	providers = $state.raw<string[]>([]);
	/** the list has been fetched at least once */
	loaded = $state(false);

	/** Fetch the list (it replaces what is held). */
	async load(): Promise<void> {
		try {
			const providers = await listDocumentProviders();
			this.providers = Array.isArray(providers) ? providers : [];
			this.loaded = true;
		} catch {
			// the list held stays
		}
	}
}

export const documentProvidersStore = new DocumentProvidersStore();
