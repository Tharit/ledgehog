// What an entry type (spec §3.9) is called and which icon stands for it: the rows and the type
// filter use the same ones. Flow has no icon of its own in a row (it shows its category).

export const ENTRY_TYPE_INFO: Readonly<Record<string, { name: string; icon: string }>> = {
	flow: { name: 'Flow', icon: 'coins' },
	transfer: { name: 'Transfer', icon: 'arrow-left-right' },
	opening: { name: 'Opening', icon: 'flag' },
	valuation: { name: 'Valuation', icon: 'gauge' },
	reconciliation: { name: 'Reconciliation', icon: 'scale' }
};
