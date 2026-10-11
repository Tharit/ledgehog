import { request } from './http.js';
import type { SessionUser } from './types.js';

export function login(loginName: string, password: string): Promise<SessionUser> {
	return request('POST', '/api/session', { body: { login: loginName, password } });
}

export function logout(): Promise<void> {
	return request('DELETE', '/api/session');
}

export function me(): Promise<SessionUser> {
	return request('GET', '/api/session');
}
