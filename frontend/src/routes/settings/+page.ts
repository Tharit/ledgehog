import { redirect } from '@sveltejs/kit';

// Settings is a set of screens: the first is the start page.
export function load() {
	redirect(307, '/settings/categories');
}
