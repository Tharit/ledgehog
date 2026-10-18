// What the task says about itself in words: the second line of the Sync item of the navigation, and
// the one line at the head of an ended sync (ux/views/sync.md).
import type { TaskKind } from '#lib/api/sync.js';
import type { TaskEnd, TaskView } from './events.js';

export type TaskPhase = 'idle' | 'attaching' | 'running' | 'ended' | 'interrupted';

export type StatusInput = {
	phase: TaskPhase;
	kind: TaskKind | null;
	view: TaskView;
	/** the sync page was opened since the task ended */
	seen: boolean;
};

export type NavStatus = { text: string; busy: boolean };

function counts(end: TaskEnd): string {
	const parts = [
		end.ok > 0 ? `${end.ok} ok` : null,
		end.failed > 0 ? `${end.failed} failed` : null
	];
	return parts.filter(Boolean).join(', ');
}

/**
 * The status line of the Sync item: "Syncing…", "Needs your input" when the task is blocked and the
 * page that can answer is not the one shown, "Refreshing accounts…" for a discovery, and after a
 * sync's end "Finished · 3 ok, 1 failed" until the sync page is opened.
 */
export function navStatus(
	input: StatusInput,
	currentPath: string,
	homePath: string
): NavStatus | null {
	const { phase, kind, view } = input;
	if (phase === 'attaching' || phase === 'running') {
		if (view.prompt && currentPath !== homePath) return { text: 'Needs your input', busy: true };
		return { text: kind === 'discovery' ? 'Refreshing accounts…' : 'Syncing…', busy: true };
	}
	if (phase === 'ended' && kind === 'sync' && view.end && !input.seen) {
		if (view.end.outcome === 'aborted') return { text: 'Stopped', busy: false };
		const text = counts(view.end);
		return { text: text ? `Finished · ${text}` : 'Finished', busy: false };
	}
	return null;
}

/** The lines at the head of an ended sync: how it ended, and the logins it did not reach, by name. */
export function endLines(end: TaskEnd, labelOf: (instanceId: number) => string): string[] {
	const lines: string[] = [];
	switch (end.outcome) {
		case 'completed':
			lines.push(
				`Finished: ${end.ok} ${end.ok === 1 ? 'run' : 'runs'} ok` +
					(end.failed > 0 ? `, ${end.failed} failed` : '')
			);
			break;
		case 'aborted':
			lines.push('Stopped. Nothing more was written.');
			break;
		case 'abandoned':
			lines.push('The sync stopped because no tab was attached. Run it again.');
			break;
		case 'crashed':
			lines.push('The sync failed unexpectedly. Runs still open were marked failed; run again.');
			break;
	}
	if (end.notStarted.length > 0) {
		lines.push(`Not reached: ${end.notStarted.map(labelOf).join(', ')}`);
	}
	return lines;
}
