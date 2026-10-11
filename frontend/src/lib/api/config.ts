import { request } from './http.js';
import type { AppConfig } from './types.js';

export function getConfig(): Promise<AppConfig> {
	return request('GET', '/api/config');
}
