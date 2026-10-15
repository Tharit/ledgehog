// THE "Add account" dialog: one controller for the whole app, its dialog mounted once in the root
// layout (components/accounts), so the review queue and the work panel's counter-account picker
// open the same dialog (`openAdd`). The caller learns of the new account through `onadded`.
import type { AccountKind } from '#lib/api/types.js';
import type { Account } from '#lib/types/domain.js';

export type AddAccountOptions = {
	/** the currency the account must have: the dialog shows it locked */
	currency?: string;
	/** the kind to preselect (default `cash`) */
	kind?: AccountKind;
	/** called with the account once it exists and is in the shared lookups */
	onadded?: (account: Account) => void;
	/** where focus goes when the dialog closes, when the opener is gone (a closed popover's item) */
	returnFocus?: HTMLElement | null;
};

export class AccountController {
	adding = $state(false);
	options = $state.raw<AddAccountOptions>({});
	/** the element that opened the dialog: focus returns there */
	opener: HTMLElement | null = null;

	openAdd(options: AddAccountOptions = {}): void {
		this.opener =
			options.returnFocus ??
			(document.activeElement instanceof HTMLElement ? document.activeElement : null);
		this.options = options;
		this.adding = true;
	}

	close(): void {
		this.adding = false;
	}

	/** The account was added: the caller hears of it, the dialog closes. */
	added(account: Account): void {
		const callback = this.options.onadded;
		this.adding = false;
		callback?.(account);
	}
}

export const accounts = new AccountController();
