import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getDocument, getUnit, listRules, previewUnit } from '#lib/api/index.js';
import { documentDetail } from '#lib/documents/fixtures.js';
import { entry } from '#lib/ledger/fixtures.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { unit } from './fixtures.js';
import { UnitPanel, type PanelNav } from './panel.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getUnit: vi.fn(),
	getDocument: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));

function fakeNav(start = '/documents/7'): PanelNav {
	const stack = [start];
	let at = 0;
	return {
		url: () => new URL(stack[at], 'http://x.test'),
		push: (url) => {
			stack.splice(at + 1);
			stack.push(url);
			at++;
		},
		replace: (url) => (stack[at] = url),
		back: () => at--
	};
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const loaded = unit({
	anchor_entry_id: 4,
	entries: [entry({ id: 4, version: 2, unit_key: 4, source_transaction_id: 40 })]
});

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(previewUnit).mockImplementation(() => new Promise(() => {}));
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([]);
	vi.mocked(getUnit).mockResolvedValue(loaded);
});

describe('opening the panel from the documents pages', () => {
	it('reads the document for its version and starts the draft with the pick', async () => {
		vi.mocked(getDocument).mockResolvedValue(documentDetail({ id: 7, version: 5 }));
		const panel = new UnitPanel(fakeNav());

		panel.open(4, null, 7);
		await flush();

		expect(getDocument).toHaveBeenCalledWith(7, expect.any(AbortSignal));
		expect(panel.status).toBe('ready');
		expect(panel.flow.draft?.documentEdit(4)).toEqual({
			mode: 'pick',
			documentId: 7,
			version: 5
		});
		// the first preview already carries it: the link is written only by the commit
		expect(vi.mocked(previewUnit).mock.calls[0][0].entries![0]).toMatchObject({
			id: 4,
			document: { mode: 'pick', document_id: 7, document_version: 5 }
		});
		expect(panel.flow.isDirty).toBe(true);
	});

	it('opens without a pick when no document is named', async () => {
		const panel = new UnitPanel(fakeNav());

		panel.open(4);
		await flush();

		expect(getDocument).not.toHaveBeenCalled();
		expect(panel.flow.draft?.documentEdit(4)).toBeUndefined();
	});

	it('opens the unit without the pick, and says so, when the document cannot be read', async () => {
		vi.mocked(getDocument).mockRejectedValue(new ApiError(404, 'not_found', 'x'));
		const panel = new UnitPanel(fakeNav());

		panel.open(4, null, 7);
		await flush();

		expect(panel.status).toBe('ready');
		expect(panel.flow.draft?.documentEdit(4)).toBeUndefined();
		expect(panel.flow.notice).toMatchObject({ kind: 'error' });
		expect(panel.flow.notice?.text).toMatch(/document could not be read/);
	});

	it('does not repeat the pick when the unit is loaded again', async () => {
		vi.mocked(getDocument).mockResolvedValue(documentDetail({ id: 7, version: 5 }));
		const panel = new UnitPanel(fakeNav());
		panel.open(4, null, 7);
		await flush();

		await panel.reload();

		expect(getDocument).toHaveBeenCalledTimes(1);
		expect(panel.flow.draft?.documentEdit(4)).toBeUndefined();
	});

	it('adds the pick to the draft of the unit that is open already', async () => {
		vi.mocked(getDocument).mockResolvedValue(documentDetail({ id: 7, version: 5 }));
		const panel = new UnitPanel(fakeNav());
		panel.open(4);
		await flush();

		panel.open(4, null, 7);
		await flush();

		expect(getUnit).toHaveBeenCalledTimes(1);
		expect(panel.flow.draft?.documentEdit(4)).toEqual({
			mode: 'pick',
			documentId: 7,
			version: 5
		});
	});
});
