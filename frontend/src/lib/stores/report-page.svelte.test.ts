import { describe, expect, it, vi } from 'vitest';
import type { ReportParams } from '#lib/reports/params.js';
import { ReportController } from './report-page.svelte.js';

function setup(search = '', pathname = '/reports/over-time') {
	const state = { search };
	const navigate = vi.fn((path: string) => {
		state.search = path.split('?')[1] ?? '';
	});
	const fetcher = vi.fn(async (params: ReportParams) => {
		void params;
		return 'answer';
	});
	const controller = new ReportController('over-time', fetcher, {
		search: () => state.search,
		navigate,
		today: () => '2026-10-20',
		pathname: () => pathname
	});
	return { controller, navigate, fetcher };
}

describe('ReportController', () => {
	it('reads the answer for the controls the address says', async () => {
		const { controller, fetcher } = setup('from=2026-01-01&to=2026-06-30&step=quarter&tag_id=7');

		await controller.sync();

		expect(fetcher).toHaveBeenCalledOnce();
		expect(fetcher.mock.calls[0][0]).toMatchObject({
			from: '2026-01-01',
			to: '2026-06-30',
			step: 'quarter',
			tagIds: [7]
		});
		expect(controller.view.data).toBe('answer');
	});

	it("opens on the report's default period when the address names none", async () => {
		const { controller, fetcher } = setup();

		await controller.sync();

		expect(fetcher.mock.calls[0][0]).toMatchObject({ from: '2025-10-01', to: '2026-09-30' });
	});

	it('a change of a control is a navigation to the address that says it', () => {
		const { controller, navigate } = setup('step=quarter');

		controller.change({ mode: 'category', kind: 'income' });

		expect(navigate).toHaveBeenCalledWith(
			'/reports/over-time?kind=income&step=quarter&mode=category'
		);
	});

	it('a change back to the defaults leaves the query out', () => {
		const { controller, navigate } = setup('step=year');

		controller.change({ step: 'month' });

		expect(navigate).toHaveBeenCalledWith('/reports/over-time');
	});

	it('a change of the address is read as the new controls, and a reload reads the same ones', async () => {
		const { controller, fetcher, navigate } = setup();
		await controller.sync();

		controller.change({ accountIds: [2, 3] });
		expect(navigate).toHaveBeenCalledOnce();
		await controller.sync();
		await controller.view.reload();

		expect(fetcher).toHaveBeenCalledTimes(3);
		expect(fetcher.mock.calls[1][0].accountIds).toEqual([2, 3]);
		expect(fetcher.mock.calls[2][0].accountIds).toEqual([2, 3]);
	});
});
