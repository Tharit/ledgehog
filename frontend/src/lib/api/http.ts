// The only place that calls `fetch` (architecture §6.2). JSON in and out, same-origin cookie
// session, and the error envelope of architecture §4.4 turned into an ApiError.

export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue | readonly QueryValue[]>;

export type RequestOptions = {
	body?: unknown;
	query?: Query;
	signal?: AbortSignal;
};

/** An error answer. Route on `code`, never on `message` (architecture §4.4). */
export class ApiError extends Error {
	readonly status: number;
	readonly code: string;
	readonly details: unknown;

	constructor(status: number, code: string, message: string, details: unknown = null) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.code = code;
		this.details = details;
	}
}

let unauthenticatedHandler: (() => void) | null = null;

/** Called for every `unauthenticated` answer (a session that ended); one handler, set by the app shell. */
export function setUnauthenticatedHandler(handler: (() => void) | null): void {
	unauthenticatedHandler = handler;
}

function queryString(query: Query | undefined): string {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(query ?? {})) {
		for (const item of Array.isArray(value) ? value : [value]) {
			if (item !== null && item !== undefined) params.append(key, String(item));
		}
	}
	const text = params.toString();
	return text ? `?${text}` : '';
}

function networkError(): ApiError {
	return new ApiError(0, 'network_error', 'The server could not be reached.');
}

async function errorFrom(response: Response): Promise<ApiError> {
	try {
		const payload = await response.json();
		const error = payload?.error;
		if (error && typeof error.code === 'string') {
			return new ApiError(response.status, error.code, String(error.message ?? ''), error.details);
		}
	} catch {
		// not JSON: fall through
	}
	return new ApiError(response.status, 'http_error', response.statusText || 'Request failed.');
}

export async function request<T>(
	method: string,
	path: string,
	{ body, query, signal }: RequestOptions = {}
): Promise<T> {
	const headers: Record<string, string> = { Accept: 'application/json' };
	// a FormData body (a file upload) is sent as it is: the browser writes its multipart type and boundary
	const multipart = typeof FormData !== 'undefined' && body instanceof FormData;
	if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
	let response: Response;
	try {
		response = await fetch(path + queryString(query), {
			method,
			credentials: 'same-origin',
			headers,
			body: body === undefined ? undefined : multipart ? (body as FormData) : JSON.stringify(body),
			signal
		});
	} catch (error) {
		if (signal?.aborted) throw error;
		throw networkError();
	}

	if (!response.ok) {
		const error = await errorFrom(response);
		if (error.code === 'unauthenticated') unauthenticatedHandler?.();
		throw error;
	}
	if (response.status === 204) return undefined as T;
	try {
		return (await response.json()) as T;
	} catch {
		throw networkError();
	}
}
