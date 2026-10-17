// Which importers have a settings form (ux/views/importers.md "The instance page": one form
// component per importer, chosen by its name, like the provenance widget). Only the CSV importer
// has one so far; a fetch importer's setup (discovery, the login) is a later wave.
export const SETTINGS_FORMS: readonly string[] = ['csv'];

export function hasSettingsForm(importer: string): boolean {
	return SETTINGS_FORMS.includes(importer);
}
