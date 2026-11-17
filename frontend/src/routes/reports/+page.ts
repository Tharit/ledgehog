import { redirect } from '@sveltejs/kit';

// Reports is four tabs: the first is the start page.
export function load() {
	redirect(307, '/reports/by-category');
}
