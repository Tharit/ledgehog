import { describe, expect, it } from 'vitest';
import { ApiError } from '#lib/api/index.js';
import { classifyAccountError, describeAccountFailure, failureField } from './errors.js';

const error = (status: number, code: string, details: unknown = null) =>
	new ApiError(status, code, 'x', details);

describe('classifyAccountError', () => {
	it.each([
		[error(409, 'conflict', { reason: 'duplicate_external_ref' }), 'duplicate_external_ref'],
		[error(409, 'conflict', { reason: 'account_refused' }), 'other'],
		[error(422, 'validation_error', { reason: 'unknown_currency' }), 'unknown_currency'],
		[error(422, 'validation_error', [{ message: 'must not be blank' }]), 'validation'],
		[error(0, 'network_error'), 'network'],
		[error(401, 'unauthenticated'), 'unauthenticated'],
		[error(500, 'internal'), 'other'],
		[new TypeError('boom'), 'network']
	])('%#', (given, kind) => {
		expect(classifyAccountError(given).kind).toBe(kind);
	});
});

describe('where and how a failure is said', () => {
	it('puts a validation message under the name and an unknown currency under the currency', () => {
		expect(failureField({ kind: 'validation' })).toBe('name');
		expect(failureField({ kind: 'unknown_currency' })).toBe('currency');
		expect(failureField({ kind: 'network' })).toBeNull();
		expect(failureField({ kind: 'duplicate_external_ref' })).toBe('externalRef');
	});

	it('says something for every kind', () => {
		for (const kind of [
			'duplicate_external_ref',
			'unknown_currency',
			'validation',
			'network',
			'unauthenticated',
			'other'
		] as const)
			expect(describeAccountFailure({ kind }).length).toBeGreaterThan(10);
	});
});
