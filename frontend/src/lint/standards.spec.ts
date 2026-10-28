// The interaction standards (spec patterns §11.4, design §5) that a reviewer would otherwise
// check by eye, as a test over the .svelte sources of components/ and routes/ (not ui/, which is
// the vendored kit). A violation is fixed in the source, never allowed here.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const files = ['src/lib/components', 'src/routes'].flatMap((dir) =>
	(readdirSync(dir, { recursive: true }) as string[])
		.map((name) => join(dir, name))
		.filter((path) => path.endsWith('.svelte') && !path.includes(join('components', 'ui')))
		.map((path) => ({ path, text: readFileSync(path, 'utf8') }))
);

// an opening tag's attributes: braces may nest twice ({() => { … }}), `>` inside them is no end
const ATTRS = String.raw`(?:[^>{}]|\{(?:[^{}]|\{[^{}]*\})*\})*`;
const BUTTON = new RegExp(
	String.raw`<(Button|ActionButton|button)\b(${ATTRS})(?<!/)>([\s\S]*?)</\1>`,
	'g'
);
const BAD_LABEL = /^(Create\b|New\b|OK$|Confirm$|Submit$)/;
// the one approved exception: the product wording of the source strip's icon, as the rule nudge link says it
const APPROVED = new Set(['Create rule from this transaction']);

function offences(test: (text: string) => string[]): string[] {
	return files.flatMap(({ path, text }) => test(text).map((what) => `${path}: ${what}`));
}

describe('interaction standards', () => {
	it('has sources to check', () => {
		expect(files.length).toBeGreaterThan(40);
	});

	it('labels buttons with verbs: never Create, New …, OK, Confirm or Submit', () => {
		const found = offences((text) => {
			const labels: string[] = [];
			for (const [, , , inner] of text.matchAll(BUTTON)) {
				labels.push(
					inner
						.replace(/\{[^}]*\}/g, '')
						.replace(/<[^>]*>/g, '')
						.trim()
				);
				for (const [, , literal] of inner.matchAll(/(['"`])((?:(?!\1).)*)\1/g))
					labels.push(literal);
			}
			for (const [, value] of text.matchAll(/\b(?:verb|actionLabel)="([^"]*)"/g))
				labels.push(value);
			return labels.filter((label) => BAD_LABEL.test(label) && !APPROVED.has(label));
		});
		expect(found).toEqual([]);
	});

	it('uses one button size: no size="sm" or size="lg"', () => {
		const found = offences((text) =>
			[...text.matchAll(new RegExp(String.raw`<(?:Button|ActionButton)\b(${ATTRS})>`, 'g'))]
				.filter(([, attrs]) => /\bsize="(sm|lg)"/.test(attrs))
				.map(() => 'a Button with size sm or lg')
		);
		expect(found).toEqual([]);
	});

	it('leaves the pointer cursor to the base rule: no cursor-pointer class', () => {
		expect(offences((text) => (text.includes('cursor-pointer') ? ['cursor-pointer'] : []))).toEqual(
			[]
		);
	});

	it('writes placeholders as an imperative ending in "…"', () => {
		const found = offences((text) =>
			[...text.matchAll(/\bplaceholder=(?:"([^"]*)"|\{(['"`])((?:(?!\2).)*)\2\})/g)]
				.map((m) => m[1] ?? m[3])
				.filter((value) => value !== '' && !value.endsWith('…'))
		);
		expect(found).toEqual([]);
	});

	it('draws a card only through card.svelte: no shadow-card, no rounded-xl with bg-card', () => {
		const found = files
			.filter(({ path }) => !path.endsWith(join('common', 'card.svelte')))
			.filter(
				({ text }) =>
					text.includes('shadow-card') || (/\brounded-xl\b/.test(text) && /\bbg-card\b/.test(text))
			)
			.map(({ path }) => path);
		expect(found).toEqual([]);
	});
});
