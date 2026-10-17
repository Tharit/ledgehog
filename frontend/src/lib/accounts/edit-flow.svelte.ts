// "Edit" on the account (spec §3.3): name, external reference, note, icon and colour in one form
// dialog; only what changed is sent. The kind and the currency are not edited here.
import { updateAccount } from '#lib/api/index.js';
import type { AccountUpdateBody, AccountWriteOut } from '#lib/api/types.js';
import { isKnownIcon } from '#lib/theme/icons.js';
import { isKnownColor } from '#lib/theme/resolve.js';
import type { Account } from '#lib/types/domain.js';
import { classifyAccountError, describeAccountFailure, failureField } from './errors.js';

const orNull = (text: string): string | null => (text.trim() === '' ? null : text.trim());

export class EditAccountFlow {
	account = $state.raw<Account | null>(null);
	name = $state('');
	externalRef = $state('');
	note = $state('');
	icon = $state<string | null>(null);
	color = $state<string | null>(null);
	errors = $state.raw<{ name?: string; externalRef?: string }>({});
	failure = $state<string | null>(null);
	busy = $state(false);

	start(account: Account): void {
		this.account = account;
		this.name = account.name;
		this.externalRef = account.external_ref ?? '';
		this.note = account.note ?? '';
		this.icon = isKnownIcon(account.icon) ? account.icon : null;
		this.color = isKnownColor(account.color) ? account.color : null;
		this.errors = {};
		this.failure = null;
		this.busy = false;
	}

	/** The fields that differ from the account held; empty when nothing changed. */
	get changes(): AccountUpdateBody {
		const account = this.account;
		if (!account) return {};
		const body: AccountUpdateBody = {};
		if (this.name.trim() !== account.name) body.name = this.name.trim();
		if (orNull(this.externalRef) !== account.external_ref)
			body.external_ref = orNull(this.externalRef);
		if (orNull(this.note) !== account.note) body.note = orNull(this.note);
		if (this.icon !== (isKnownIcon(account.icon) ? account.icon : null)) body.icon = this.icon;
		if (this.color !== (isKnownColor(account.color) ? account.color : null))
			body.color = this.color;
		return body;
	}

	get canSubmit(): boolean {
		return this.account !== null && this.name.trim() !== '';
	}

	/** The saved account's answer; null when nothing changed or with the refusal said in the dialog. */
	async submit(): Promise<AccountWriteOut | null> {
		const account = this.account;
		if (!account || this.busy || !this.canSubmit) return null;
		const body = this.changes;
		if (Object.keys(body).length === 0) return null;
		this.busy = true;
		this.errors = {};
		this.failure = null;
		try {
			return await updateAccount(account.id, body);
		} catch (error) {
			const failure = classifyAccountError(error);
			const text = describeAccountFailure(failure);
			if (failure.kind === 'duplicate_external_ref') this.errors = { externalRef: text };
			else if (failureField(failure) === 'name') this.errors = { name: text };
			else this.failure = text.replace('could not be added', 'could not be saved');
			return null;
		} finally {
			this.busy = false;
		}
	}
}
