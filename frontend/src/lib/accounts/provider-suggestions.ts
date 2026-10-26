// The providers a clearance account's list suggests: those of the registered document importers
// (spec §3.3). A suggestion is only a convenience, so a failed request is no failure: none are offered.
import { listDocumentProviders } from '#lib/api/index.js';

export async function loadProviderSuggestions(): Promise<string[]> {
	try {
		return await listDocumentProviders();
	} catch {
		return [];
	}
}
