// State of the instance page, add or edit (ux/views/importers.md "The instance page"): a draft editor
// (patterns §11.2): the label and the importer's settings are edited as a draft; nothing is saved
// until "Save importer". The server judges the settings; its refusal names the setting and stands
// under that field (patterns §11.5). Page-scoped.
import {
	classifyImporterError,
	createInstance,
	listImporters,
	listInstances,
	updateInstance,
	type CatalogEntry,
	type ImporterError,
	type ImporterInstance
} from '#lib/api/importers.js';
import { todayIso } from '#lib/format/index.js';
import { settingsFormOf, type AnyDraft } from '#lib/importers/forms.js';
import { describeImporterError } from '#lib/importers/messages.js';
import { session } from './session.svelte.js';

export type EditorLoad = 'loading' | 'ready' | 'missing' | 'error';

export type SaveResult = { instance: ImporterInstance; created: boolean };

/** Where the server's refusal stands: by field id (`label`, a CSV field), the rest as one line. */
export type EditorErrors = Record<string, string>;

function sentence(message: string): string {
	const text = message.replace(/^[a-z_.]+:\s*/, '');
	return text.charAt(0).toUpperCase() + text.slice(1);
}

export class ImporterEditorStore {
	readonly instanceId: number | null;
	readonly importerName: string | null;

	loadStatus = $state<EditorLoad>('loading');
	loadError = $state.raw<ImporterError | null>(null);
	/** the stored instance, when editing */
	instance = $state.raw<ImporterInstance | null>(null);
	catalog = $state.raw<CatalogEntry[]>([]);

	label = $state('');
	/** the importer's draft, in the type of its form adapter (`lib/importers/forms.ts`) */
	draft = $state<AnyDraft>({});
	/** the preset the form was last filled from (add only) */
	preset = $state('');

	saving = $state(false);
	errors = $state.raw<EditorErrors>({});
	/** a refusal that belongs to no field, or a failure that is not a refusal */
	failure = $state<string | null>(null);

	#initial = $state('');

	readonly editing: boolean;
	readonly locale = $derived(session.config?.locale ?? 'en');

	constructor({
		instanceId = null,
		importer = null
	}: {
		instanceId?: number | null;
		importer?: string | null;
	}) {
		this.instanceId = instanceId;
		this.importerName = importer;
		this.editing = instanceId !== null;
	}

	/** The importer this page edits: the instance's, or the one chosen to add. */
	get importer(): string | null {
		return this.instance?.importer ?? this.importerName;
	}

	/** the catalog's entry for the importer: its kind and presets */
	get entry(): CatalogEntry | null {
		return this.catalog.find((e) => e.name === this.importer) ?? null;
	}

	get presetNames(): string[] {
		const entry = this.entry;
		return entry ? Object.keys(entry.presets).sort() : [];
	}

	/** the draft differs from what was loaded or last saved */
	get dirty(): boolean {
		return this.loadStatus === 'ready' && this.#snapshot() !== this.#initial;
	}

	#snapshot(): string {
		return JSON.stringify({ label: this.label, draft: this.draft });
	}

	async init(): Promise<void> {
		this.loadStatus = 'loading';
		this.loadError = null;
		const [instances, catalog] = await Promise.allSettled([
			this.editing ? listInstances() : Promise.resolve([] as ImporterInstance[]),
			listImporters()
		]);
		if (catalog.status === 'fulfilled') this.catalog = catalog.value;
		// the catalog gives an add page its importer and presets; an edit page does without it
		const failed =
			instances.status === 'rejected'
				? instances.reason
				: !this.editing && catalog.status === 'rejected'
					? catalog.reason
					: null;
		if (instances.status === 'rejected' || failed !== null) {
			this.loadError = classifyImporterError(failed);
			this.loadStatus = 'error';
			return;
		}
		if (this.editing) {
			const found = instances.value.find((i) => i.id === this.instanceId) ?? null;
			if (!found) {
				this.loadStatus = 'missing';
				return;
			}
			this.#adopt(found);
		} else {
			if (!this.entry) {
				this.loadStatus = 'missing';
				return;
			}
			this.label = '';
			this.draft =
				this.#form()?.emptyDraft({
					startDate: this.entry?.start_date_default ?? null,
					today: todayIso(session.config?.timezone ?? 'UTC')
				}) ?? {};
			this.#initial = this.#snapshot();
		}
		this.loadStatus = 'ready';
	}

	#adopt(instance: ImporterInstance): void {
		this.instance = instance;
		this.label = instance.label;
		this.draft = this.#form()?.draftFromSettings(instance.settings) ?? {};
		this.#initial = this.#snapshot();
	}

	#form() {
		return this.importer ? settingsFormOf(this.importer) : null;
	}

	/** Fill the form from a preset, as a draft edit; the label stays what it is. */
	choosePreset(name: string): void {
		const settings = this.entry?.presets[name];
		if (!settings) return;
		this.preset = name;
		this.draft = this.#form()?.draftFromSettings(settings) ?? {};
		this.errors = {};
		this.failure = null;
	}

	/** The instance as the server now has it (a link was added or removed on this page). */
	replaceInstance(instance: ImporterInstance): void {
		this.instance = instance;
	}

	/** The message under a field: the first of `keys` the server refused. */
	errorFor(...keys: string[]): string | null {
		for (const key of keys) if (this.errors[key]) return this.errors[key];
		return null;
	}

	/** Save the draft: the instance as it now is, or null (the refusal is in `errors` or `failure`). */
	async save(): Promise<SaveResult | null> {
		const importer = this.importer;
		const form = this.#form();
		if (this.saving || !importer || !form || this.loadStatus !== 'ready') return null;
		this.errors = {};
		this.failure = null;
		const problems = form.problems?.(this.draft) ?? {};
		if (Object.keys(problems).length > 0) {
			this.errors = problems;
			return null;
		}
		this.saving = true;
		const fields = { label: this.label, settings: form.settingsFromDraft(this.draft) };
		try {
			const created = !this.editing;
			const instance =
				this.instanceId === null
					? await createInstance(importer, fields)
					: await updateInstance(this.instanceId, fields);
			this.saving = false;
			this.#adopt(instance);
			return { instance, created };
		} catch (error) {
			this.saving = false;
			this.#refuse(classifyImporterError(error));
			return null;
		}
	}

	#refuse(error: ImporterError): void {
		switch (error.kind) {
			case 'invalid_profile': {
				const field = error.setting ? (this.#form()?.fieldOfRefusal(error.setting) ?? null) : null;
				if (field) {
					this.errors = { [field]: sentence(error.message) };
				} else {
					this.failure = describeImporterError(error);
				}
				return;
			}
			case 'invalid_instance':
				this.errors = { label: sentence(error.message) };
				return;
			case 'validation': {
				const found: EditorErrors = {};
				for (const problem of error.problems) {
					const key = problem.field.split('.')[0] === 'label' ? 'label' : null;
					if (key && !found[key]) found[key] = sentence(problem.message);
				}
				if (Object.keys(found).length > 0) this.errors = found;
				else this.failure = describeImporterError(error);
				return;
			}
			default:
				this.failure = describeImporterError(error);
		}
	}

	dispose(): void {
		// nothing runs in the background
	}
}
