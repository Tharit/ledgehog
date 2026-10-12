// One call to a write: its answer or the failure it came to, classified by code. Never throws.
import { ApiError } from '#lib/api/index.js';
import { classifyDimensionError, type Outcome } from './errors.js';

export async function attempt<T>(call: () => Promise<T>): Promise<Outcome<T>> {
	try {
		return { ok: true, value: await call() };
	} catch (error) {
		const e =
			error instanceof ApiError
				? error
				: new ApiError(0, 'network_error', 'The server could not be reached.');
		return { ok: false, failure: classifyDimensionError(e) };
	}
}
