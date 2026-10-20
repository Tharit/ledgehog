import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/svelte';
import { afterEach } from 'vitest';

// jsdom has neither; popovers, command lists and the ledger cursor look for them
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
if (typeof ResizeObserver === 'undefined') {
	globalThis.ResizeObserver = class {
		observe() {}
		unobserve() {}
		disconnect() {}
	};
}

// LayerChart reads `prefers-reduced-motion` when it loads
if (typeof window.matchMedia !== 'function') {
	window.matchMedia = (query: string) =>
		({
			matches: false,
			media: query,
			onchange: null,
			addEventListener() {},
			removeEventListener() {},
			addListener() {},
			removeListener() {},
			dispatchEvent: () => false
		}) as MediaQueryList;
}

afterEach(cleanup);
