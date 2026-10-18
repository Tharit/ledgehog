// What the sync page reads while nothing runs: the plan, the starts the user changed, and the
// refusal of a start (ux/views/sync.md "Starting"). Page-scoped; the task itself is `sync`.
import { readSyncPlan, type PlanInstance, type SyncItem } from '#lib/api/index.js';
import { refusalText, type StartRefusal } from '#lib/sync/entry.js';
import { narrowPlan, planItems, startable, type Narrowing } from '#lib/sync/plan.js';

export type PlanStatus = 'loading' | 'ready' | 'error';

export class SyncPlanStore {
	plan = $state.raw<PlanInstance[]>([]);
	status = $state<PlanStatus>('loading');
	/** the part of the plan the address names */
	narrowing = $state.raw<Narrowing>({ instanceId: null, accountId: null });
	/** the starts the user typed, by account id (only editable accounts have a field) */
	starts = $state<Record<number, string>>({});
	/** a refused start, above the button */
	refusal = $state<string | null>(null);
	starting = $state(false);

	readonly visible = $derived(narrowPlan(this.plan, this.narrowing));
	/** the logins the start would run: busy ones are shown and left out */
	readonly runnable = $derived(startable(this.visible));
	readonly items = $derived(planItems(this.visible, this.starts));

	#generation = 0;

	async load(): Promise<void> {
		const generation = ++this.#generation;
		this.status = 'loading';
		try {
			const plan = await readSyncPlan();
			if (generation !== this.#generation) return;
			this.plan = plan;
			this.starts = {};
			this.status = 'ready';
		} catch {
			if (generation !== this.#generation) return;
			this.status = 'error';
		}
	}

	/** The label of a login, for the cards of a running task (which the plan still lists). */
	labelOf = (instanceId: number): string =>
		this.plan.find((i) => i.instance_id === instanceId)?.label ?? `Login ${instanceId}`;

	/** Start with what the plan shows; `start` is the store's, which returns a refusal. */
	async begin(start: (items: SyncItem[]) => Promise<StartRefusal | null>): Promise<void> {
		this.starting = true;
		this.refusal = null;
		const refusal = await start(this.items);
		this.starting = false;
		if (refusal) this.refusal = refusalText(refusal);
	}

	dispose(): void {
		this.#generation++;
	}
}
