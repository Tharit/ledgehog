// Proves the module-boundary rules of eslint.config.js: each snippet is linted as if it lived at
// the given path, and the rule must fire there and stay quiet where the code is allowed.
import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

const eslint = new ESLint({ overrideConfigFile: 'eslint.config.js' });

async function rulesFired(code: string, filePath: string): Promise<string[]> {
	const [result] = await eslint.lintText(code, { filePath });
	return result.messages.filter((m) => m.severity === 2).map((m) => String(m.ruleId));
}

const FETCH = 'export const load = () => fetch("/api/x");\n';
const COMPONENT = 'src/lib/components/common/example.ts';

describe('module boundary lint rules', { timeout: 60_000 }, () => {
	it('bans fetch outside src/lib/api', async () => {
		expect(await rulesFired(FETCH, COMPONENT)).toContain('no-restricted-globals');
		expect(await rulesFired(FETCH, 'src/routes/example.ts')).toContain('no-restricted-globals');
		expect(await rulesFired(FETCH, 'src/lib/api/example.ts')).not.toContain(
			'no-restricted-globals'
		);
	});

	it('bans window.fetch and globalThis.fetch outside src/lib/api', async () => {
		const code = 'export const a = () => window.fetch("/x");\nexport const b = globalThis.fetch;\n';
		expect(await rulesFired(code, COMPONENT)).toEqual([
			'no-restricted-properties',
			'no-restricted-properties'
		]);
		expect(await rulesFired(code, 'src/lib/api/example.ts')).toEqual([]);
	});

	it('bans Intl and toLocale* outside src/lib/format', async () => {
		const intl = 'export const f = new Intl.NumberFormat("en");\n';
		const date = 'export const f = (d: Date) => d.toLocaleDateString();\n';
		const text = 'export const f = (n: number) => n.toLocaleString();\n';
		for (const code of [intl, date, text]) {
			expect(await rulesFired(code, 'src/routes/example.ts')).toContain('no-restricted-properties');
			expect(await rulesFired(code, 'src/lib/api/example.ts')).toContain(
				'no-restricted-properties'
			);
			expect(await rulesFired(code, 'src/lib/format/example.ts')).toEqual([]);
		}
	});

	it('allows bits-ui only under src/lib/components/ui', async () => {
		const code = 'import { Dialog } from "bits-ui";\nexport const d = Dialog;\n';
		expect(await rulesFired(code, 'src/lib/components/ui/dialog/example.ts')).toEqual([]);
		expect(await rulesFired(code, COMPONENT)).toContain('no-restricted-imports');
		expect(await rulesFired(code, 'src/routes/example.ts')).toContain('no-restricted-imports');
		const sub = 'import { x } from "bits-ui/internal";\nexport const d = x;\n';
		expect(await rulesFired(sub, COMPONENT)).toContain('no-restricted-imports');
	});

	it('keeps the API out of components', async () => {
		for (const specifier of ['#lib/api/index.js', '$lib/api', '../../api/http.js']) {
			const code = `import { request } from "${specifier}";\nexport const r = request;\n`;
			expect(await rulesFired(code, COMPONENT)).toContain('no-restricted-imports');
		}
		const code = 'import { request } from "#lib/api/index.js";\nexport const r = request;\n';
		expect(await rulesFired(code, 'src/lib/stores/example.ts')).toEqual([]);
		expect(await rulesFired(code, 'src/routes/example.ts')).toEqual([]);
	});
});
