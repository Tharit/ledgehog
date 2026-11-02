// Mirrors `_POLICY` in app/api/frontend.py (architecture §6.7); tests/api/test_frontend_api.py asserts it.
// Keywords are written without quotes, as SvelteKit's `csp` setting expects; one directive per line.
import type { sveltekit } from '@sveltejs/kit/vite';

type Csp = NonNullable<NonNullable<Parameters<typeof sveltekit>[0]>['csp']>;

export const directives: NonNullable<Csp['directives']> = {
	'default-src': ['none'],
	'script-src': ['self'],
	'style-src': ['self'],
	'style-src-attr': ['unsafe-inline'],
	'img-src': ['self'],
	'font-src': ['self'],
	'connect-src': ['self'],
	'manifest-src': ['self'],
	'base-uri': ['none'],
	'form-action': ['none'],
	'frame-ancestors': ['none'],
	'require-trusted-types-for': ['script'],
	'trusted-types': ['svelte-trusted-html']
};
