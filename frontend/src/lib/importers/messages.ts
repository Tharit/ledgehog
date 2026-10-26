// What the importer screens say, routed by the kind of failure (patterns §8, §11.5), never by a
// message the server wrote.
import type { ImporterError, UploadFailure } from '#lib/api/importers.js';
import { IMPORTERS_PATH } from './links.js';

/** The refusals of the request itself, and the failures every screen shares. */
export function describeImporterError(error: ImporterError): string {
	switch (error.kind) {
		case 'invalid_profile':
			return error.setting
				? `The server did not accept the setting “${error.setting}”: ${afterSetting(error.message, error.setting)}`
				: `The server did not accept the settings: ${error.message}`;
		case 'validation':
			return 'The server did not accept this; check the highlighted fields.';
		case 'invalid_instance':
			return error.message;
		case 'instance_has_runs':
			return 'This importer has runs; disable it instead.';
		case 'instance_disabled':
			return 'This importer is disabled. Enable it first.';
		case 'not_an_account_source':
			return 'This importer does not deliver transactions, so it has no accounts to link.';
		case 'not_a_file_source':
			return 'This importer does not take files.';
		case 'account_closed':
			return 'This account is closed. Reopen it first.';
		case 'account_not_linked':
			return 'This account is not linked to this importer (any more).';
		case 'already_linked':
			return 'This account is already linked to this importer.';
		case 'clearance_account':
			return 'A clearance account is fed by the orders of its providers and is never linked.';
		case 'file_too_large':
			return 'The file is larger than 10 MiB. Upload a smaller export.';
		case 'parse_failed':
			return `The file could not be read: ${error.message}`;
		case 'contract_violation':
			return `The file broke a rule of the import: ${error.message}`;
		case 'importer_error':
			return error.message;
		case 'not_found':
			return 'This no longer exists. It was deleted elsewhere.';
		case 'try_again':
			return 'The server was busy and did not write this. Try again.';
		case 'unauthenticated':
			return 'Your session has ended. Sign in again.';
		case 'network':
			return 'The server could not be reached. Check the connection and try again.';
		default:
			return 'The server could not do this. Try again in a moment.';
	}
}

/** The plugin writes "<setting>: <what is wrong>"; the setting is named once, so drop it from the text. */
function afterSetting(message: string, setting: string): string {
	const head = `${setting}:`;
	return message.startsWith(head) ? message.slice(head.length).trim() : message;
}

/**
 * What a failure the real run would end in says (a dry run reports it in place of the counts):
 * which setting to look at where the failure names one.
 */
export function describeUploadFailure(failure: UploadFailure): string {
	switch (failure.kind) {
		case 'contract_violation':
			return failure.rule === 'currency_mismatch'
				? 'A row is in a currency other than the account’s. Check the currency column and the row filters in the profile.'
				: `The file broke a rule of the import (${failure.rule ?? 'unnamed'}): ${failure.message}`;
		case 'parse_failed':
			return `The file could not be read with this profile: ${failure.message}`;
		case 'invalid_profile':
			return `The profile has a setting the importer cannot use: ${failure.message}`;
		case 'instance_disabled':
			return 'This importer is disabled. Enable it first.';
		case 'account_closed':
			return 'This account is closed. Reopen it first.';
		case 'account_not_linked':
			return 'This account is not linked to this importer (any more).';
		default:
			return failure.message;
	}
}

// ---- what a page that saved or removed something tells the list ------------------------------

export type ImporterDone =
	| { action: 'added' | 'saved' | 'deleted'; label: string }
	| { action: 'linked' | 'unlinked'; label: string; account: string };

const DONE_PARAM = 'done';
const LABEL_PARAM = 'label';

/** The notice for a write that finished on another page; null for anything the address does not hold. */
export function doneFromSearch(search: string): ImporterDone | null {
	const params = new URLSearchParams(search);
	const action = params.get(DONE_PARAM);
	const label = params.get(LABEL_PARAM) ?? '';
	if (action === 'added' || action === 'saved' || action === 'deleted') return { action, label };
	return null;
}

/** The address a page sends the list to after it saved or deleted: the notice rides in it once. */
export function doneUrl(done: { action: 'added' | 'saved' | 'deleted'; label: string }): string {
	const params = new URLSearchParams({ [DONE_PARAM]: done.action, [LABEL_PARAM]: done.label });
	return `${IMPORTERS_PATH}?${params}`;
}

export function doneText(done: ImporterDone): string {
	switch (done.action) {
		case 'added':
			return `Importer “${done.label}” was added.`;
		case 'saved':
			return `Importer “${done.label}” was saved. Later uploads use the new settings.`;
		case 'deleted':
			return `Importer “${done.label}” was deleted, with its links.`;
		case 'linked':
			return `${done.account} is now linked to “${done.label}”.`;
		case 'unlinked':
			return `${done.account} is no longer linked to “${done.label}”; its coverage and rows stay.`;
	}
}
