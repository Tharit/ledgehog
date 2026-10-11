import prettier from 'eslint-config-prettier';
import path from 'node:path';
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig, includeIgnoreFile } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';

const gitignorePath = path.resolve(import.meta.dirname, '.gitignore');

// The frontend's module boundaries (architecture §6.2), enforced the way import-linter does it
// for the backend. Each override below re-states a rule, because a later config replaces an
// earlier one rather than merging with it.
const bitsUi = {
	regex: '^bits-ui(/|$)',
	message: 'Bits UI is imported only under src/lib/components/ui/ (architecture §6.2).'
};
const api = {
	regex: '(^|/)api(/|$)',
	message: 'Components take data as props and never import the API (architecture §6.2).'
};
const noFetch = [
	{
		name: 'fetch',
		message: 'Only src/lib/api/ calls fetch (architecture §6.2).'
	}
];
const fetchViaObject = ['window', 'globalThis'].map((object) => ({
	object,
	property: 'fetch',
	message: 'Only src/lib/api/ calls fetch (architecture §6.2).'
}));
const locale = [
	{ object: 'Intl', message: 'Locale formatting lives in src/lib/format/ (architecture §6.6).' },
	...['toLocaleString', 'toLocaleDateString', 'toLocaleTimeString'].map((property) => ({
		property,
		message: 'Locale formatting lives in src/lib/format/ (architecture §6.6).'
	}))
];

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	js.configs.recommended,
	ts.configs.recommended,
	svelte.configs.recommended,
	prettier,
	svelte.configs.prettier,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },
		rules: {
			// typescript-eslint strongly recommend that you do not use the no-undef lint rule on TypeScript projects.
			// see: https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
			'no-undef': 'off'
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser
			}
		}
	},
	{
		// The app is served at the root and has no `paths.base`, so links need no `resolve()`.
		rules: { 'svelte/no-navigation-without-resolve': 'off' }
	},
	{
		files: ['src/**'],
		rules: {
			'no-restricted-globals': ['error', ...noFetch],
			'no-restricted-properties': ['error', ...fetchViaObject, ...locale],
			'no-restricted-imports': ['error', { patterns: [bitsUi] }]
		}
	},
	{
		files: ['src/lib/components/**'],
		rules: { 'no-restricted-imports': ['error', { patterns: [bitsUi, api] }] }
	},
	{
		files: ['src/lib/components/ui/**'],
		rules: { 'no-restricted-imports': 'off' }
	},
	{
		files: ['src/lib/api/**'],
		rules: {
			'no-restricted-globals': 'off',
			'no-restricted-properties': ['error', ...locale]
		}
	},
	{
		files: ['src/lib/format/**'],
		rules: { 'no-restricted-properties': ['error', ...fetchViaObject] }
	}
);
