import { redirect } from '@sveltejs/kit';

// Reports is three tabs: the first is the start page.
export function load() {
	redirect(307, '/reports/by-category');
}
