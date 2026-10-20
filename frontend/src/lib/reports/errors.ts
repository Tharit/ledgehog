// How a failed report read is presented, routed by the error's `code` and never by its message
// (architecture §4.4, patterns §8).
import { describeLoadError, type LoadErrorPresentation } from '#lib/ledger/errors.js';

export function describeReportError(code: string): LoadErrorPresentation {
	if (code === 'validation_error') {
		return {
			title: 'This report could not be drawn',
			message:
				'The server did not accept this period or step: a range holds at most 120 months, quarters or years. Choose a shorter period or a longer step.',
			retryable: false
		};
	}
	const common = describeLoadError(code);
	return { ...common, title: 'The report could not be loaded' };
}
