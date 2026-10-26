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
		[error(409, 'conflict', { reason: 'provider_taken', provider: 'amazon' }), 'provider_taken'],
		[error(422, 'validation_error', { reason: 'invalid_provider' }), 'invalid_provider'],
		[error(422, 'validation_error', { reason: 'start_required' }), 'start_required'],
		[error(422, 'validation_error', { reason: 'not_clearance' }), 'not_clearance'],
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

	it('puts the clearance refusals under their fields and names the account that holds a provider', () => {
		const taken = classifyAccountError(
			error(409, 'conflict', {
				reason: 'provider_taken',
				provider: 'amazon',
				account: { id: 4, name: 'Amazon clearing' }
			})
		);
		expect(failureField(taken)).toBe('providers');
		expect(describeAccountFailure(taken)).toContain('Amazon clearing');
		expect(failureField({ kind: 'invalid_provider' })).toBe('providers');
		expect(failureField({ kind: 'not_clearance' })).toBe('providers');
		expect(failureField({ kind: 'start_required' })).toBe('start');
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
