// What a prompt looks like (ux/views/sync.md "Prompts", architecture §5.5): the label of each
// subject, the verb of each kind and the words of a dialog's title and description. A bank's own
// words (the challenge, the method, the options) are shown as given; an unknown subject too.
import type { PromptBody } from '#lib/api/sync.js';
import { promptItem, type TaskView } from './events.js';

const SUBJECTS: Record<string, string> = {
	pin: 'PIN',
	password: 'Password',
	tan_mechanism: 'TAN method',
	tan_medium: 'TAN medium',
	tan_medium_name: 'Name of the TAN medium'
};

/** The label of a subject; one this client does not know is shown as given. */
export function subjectLabel(subject: string): string {
	return SUBJECTS[subject] ?? subject;
}

/** The verb of the dialog: null where nothing is sent (a decoupled confirmation). */
export function promptVerb(body: PromptBody): string | null {
	switch (body.kind) {
		case 'secret':
			return 'Sign in';
		case 'tan':
			return body.medium === 'decoupled' ? null : 'Send TAN';
		case 'choice':
		case 'text':
			return 'Continue';
	}
}

/** What the dialog is titled by: what it asks, then the login. */
export function promptTitle(body: PromptBody, login: string): string {
	switch (body.kind) {
		case 'secret':
		case 'choice':
		case 'text':
			return `${subjectLabel(body.subject)} for ${login}`;
		case 'tan':
			return body.medium === 'decoupled' ? `Confirmation for ${login}` : `TAN for ${login}`;
	}
}

/** The label of the dialog's one field, or null where it has none (a choice has its own, a decoupled none). */
export function promptFieldLabel(body: PromptBody): string | null {
	switch (body.kind) {
		case 'secret':
		case 'text':
			return subjectLabel(body.subject);
		case 'tan':
			return body.medium === 'decoupled' ? null : 'TAN';
		case 'choice':
			return subjectLabel(body.subject);
	}
}

/** The moment, for the description: "Signing in." or "Fetching Giro." */
export function promptMoment(runId: number | null, what: string | null): string {
	return runId === null || what === null ? 'Signing in.' : `Fetching ${what}.`;
}

/** The moment of the open prompt of a view: the item of its run, or the sign-in. */
export function viewMoment(
	view: TaskView,
	accountName: (accountId: number) => string | null
): string {
	const prompt = view.prompt;
	if (!prompt) return '';
	const item = promptItem(view);
	if (!item) return promptMoment(prompt.runId, null);
	const what =
		item.kind === 'documents'
			? 'documents'
			: (item.accountId !== null && accountName(item.accountId)) || 'the account';
	return promptMoment(prompt.runId, what);
}

/** What cancelling does, said in the dialog. */
export const CANCEL_SENTENCE =
	'Cancelling stops this login; its accounts keep failed runs to run again.';
