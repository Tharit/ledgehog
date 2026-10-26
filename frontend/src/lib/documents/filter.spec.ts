import { describe, expect, it } from 'vitest';
import {
	describeDocumentFilter,
	documentFilterFromParams,
	documentFilterKey,
	documentSearchParams,
	emptyDocumentFilter,
	isEmptyDocumentFilter,
	normalizeDocumentFilter
} from './filter.js';

describe('documents filter URL', () => {
	it('an empty filter is an empty query', () => {
		expect(documentSearchParams(emptyDocumentFilter()).toString()).toBe('');
		expect(isEmptyDocumentFilter(emptyDocumentFilter())).toBe(true);
	});

	it('round-trips every dimension with the API names', () => {
		const filter = {
			provider: ['paypal', 'amazon'],
			from: '2026-10-01',
			to: '2026-10-31',
			amount_min: 100,
			amount_max: 900,
			currency: 'EUR',
			q: 'rewe'
		};
		const query = documentSearchParams(filter).toString();
		expect(query).toBe(
			'provider=amazon&provider=paypal&from=2026-10-01&to=2026-10-31&amount_min=100&amount_max=900&currency=EUR&q=rewe'
		);
		expect(documentFilterFromParams(query)).toEqual({ ...filter, provider: ['amazon', 'paypal'] });
	});

	it('ignores what it cannot understand', () => {
		const filter = documentFilterFromParams(
			'from=2026-02-30&to=nope&amount_min=-4&amount_max=x&currency=EUR&provider=%20'
		);
		expect(filter).toEqual({
			provider: [],
			from: undefined,
			to: undefined,
			amount_min: undefined,
			amount_max: undefined,
			currency: 'EUR',
			q: ''
		});
	});

	it('swaps reversed ranges and drops bounds without a currency', () => {
		const filter = normalizeDocumentFilter({
			provider: [],
			q: '',
			from: '2026-10-31',
			to: '2026-10-01',
			amount_min: 5,
			amount_max: 1
		});
		expect(filter.from).toBe('2026-10-01');
		expect(filter.amount_min).toBeUndefined();
		expect(
			normalizeDocumentFilter({
				provider: [],
				q: '',
				currency: 'eur',
				amount_min: 5,
				amount_max: 1
			})
		).toMatchObject({ currency: 'EUR', amount_min: 1, amount_max: 5 });
	});

	it('keys equal filters equally', () => {
		expect(documentFilterKey({ provider: ['b', 'a', 'a'], q: ' x ' })).toBe(
			documentFilterKey({ provider: ['a', 'b'], q: 'x' })
		);
	});

	it('keeps a provider once whatever its case, with the first spelling', () => {
		expect(
			normalizeDocumentFilter({
				...emptyDocumentFilter(),
				provider: ['Amazon', 'amazon', 'PayPal']
			}).provider
		).toEqual(['Amazon', 'PayPal']);
	});
});

describe('describeDocumentFilter', () => {
	it('names the active parts in a fixed order', () => {
		const parts = describeDocumentFilter(
			{
				provider: ['amazon'],
				from: '2026-10-01',
				q: 'rewe',
				currency: 'EUR',
				amount_min: 1000
			},
			'en'
		);
		expect(parts.map((p) => p.key)).toEqual(['provider', 'date', 'amount', 'text']);
		expect(parts[0].label).toBe('amazon');
	});

	it('says nothing for an empty filter', () => {
		expect(describeDocumentFilter(emptyDocumentFilter(), 'en')).toEqual([]);
	});
});
