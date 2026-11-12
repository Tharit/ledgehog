// The registry of importer settings forms (ux/views/importers.md "The instance page": one form
// component per importer, chosen by its name, like the provenance widget). Per importer: the form
// component and the draft adapter the editor uses. A fetch importer's accounts come from discovery;
// only its setup form is here.
import type { Component } from 'svelte';
import type { IsoDate } from '#lib/format/index.js';
import CsvProfileForm from '#lib/components/importers/csv-profile-form.svelte';
import EmailForm from '#lib/components/importers/email-form.svelte';
import CamtForm from '#lib/components/importers/camt-form.svelte';
import FintsForm from '#lib/components/importers/fints-form.svelte';
import * as csv from './csv-profile.js';
import * as email from './email-profile.js';
import * as fints from './fints-profile.js';

export type FormProps<D> = { draft: D; errors?: Record<string, string>; disabled?: boolean };

/** What a new instance's draft may be prefilled with: today. */
export type DraftContext = { today: IsoDate };

export type SettingsForm<D> = {
	component: Component<FormProps<D>>;
	/** the draft of a new instance; `context` carries what the day prefills */
	emptyDraft(context?: DraftContext): D;
	draftFromSettings(settings: Record<string, unknown>): D;
	settingsFromDraft(draft: D): Record<string, unknown>;
	/** the field id a refused setting stands under, or null when the form has none for it */
	fieldOfRefusal(setting: string): string | null;
	/** the client's checks before saving, by field id; absent where the server alone judges */
	problems?(draft: D): Record<string, string>;
};

// the draft is the adapter's own type; the editor holds it without knowing which
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyDraft = any;

const csvForm: SettingsForm<csv.CsvDraft> = {
	component: CsvProfileForm,
	emptyDraft: csv.emptyDraft,
	draftFromSettings: csv.draftFromSettings,
	settingsFromDraft: csv.settingsFromDraft,
	fieldOfRefusal(setting) {
		const field = csv.fieldOfSetting(setting);
		return csv.CSV_FIELDS.includes(field) ? field : null;
	}
};

const fintsForm: SettingsForm<fints.FintsDraft> = {
	component: FintsForm,
	emptyDraft: fints.emptyDraft,
	draftFromSettings: fints.draftFromSettings,
	settingsFromDraft: fints.settingsFromDraft,
	fieldOfRefusal: fints.fieldOfSetting,
	problems: fints.problemsOf
};

const emailForm: SettingsForm<email.EmailDraft> = {
	component: EmailForm,
	emptyDraft: email.emptyDraft,
	draftFromSettings: email.draftFromSettings,
	settingsFromDraft: email.settingsFromDraft,
	fieldOfRefusal: email.fieldOfSetting,
	problems: email.problemsOf
};

// the camt importer has no settings (plugins/importers/camt.md §1): its "form" is one line of text
const camtForm: SettingsForm<Record<string, never>> = {
	component: CamtForm,
	emptyDraft: () => ({}),
	draftFromSettings: () => ({}),
	settingsFromDraft: () => ({}),
	fieldOfRefusal: () => null
};

export const SETTINGS_FORMS: Readonly<Record<string, SettingsForm<AnyDraft>>> = {
	csv: csvForm,
	fints: fintsForm,
	email: emailForm,
	camt: camtForm
};

export function settingsFormOf(importer: string): SettingsForm<AnyDraft> | null {
	return Object.hasOwn(SETTINGS_FORMS, importer) ? SETTINGS_FORMS[importer] : null;
}

export function hasSettingsForm(importer: string): boolean {
	return settingsFormOf(importer) !== null;
}
