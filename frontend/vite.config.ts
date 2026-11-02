import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { directives } from './csp.ts';

export default defineConfig(({ command }) => ({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// SPA: one index.html answers every route (architecture §6.1)
			adapter: adapter({ fallback: 'index.html' }),

			// Dev server only: send the production Content-Security-Policy (csp.ts, architecture §6.7) so a violation
			// shows up while developing. SvelteKit adds what dev needs: a nonce on its bootstrap script and 'unsafe-inline'
			// on style-src for Vite's <style> elements. Not set for the build: its output must stay unchanged.
			csp: command === 'serve' ? { mode: 'nonce', directives } : undefined
		})
	],
	server: {
		// 127.0.0.1, not localhost: the OIDC provider accepts only this redirect address, and localhost may resolve to ::1
		host: '127.0.0.1',
		// same origin as the page, so the SameSite=Lax session cookie is sent (architecture §6.7)
		proxy: { '/api': process.env.LEDGEHOG_API ?? 'http://127.0.0.1:8000' }
	},
	test: {
		expect: { requireAssertions: true },
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			},
			{
				extends: './vite.config.ts',
				resolve: { conditions: ['browser'] },
				test: {
					name: 'client',
					environment: 'jsdom',
					include: ['src/**/*.svelte.{test,spec}.{js,ts}'],
					setupFiles: ['./src/vitest-setup-client.ts']
				}
			}
		]
	}
}));
