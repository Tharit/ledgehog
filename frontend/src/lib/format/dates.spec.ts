import { describe, it, expect } from 'vitest';
import {
	formatDate,
	formatDateRange,
	formatInstant,
	formatMonth,
	relativeDay,
	todayIso
} from './dates.js';

describe('formatDate', () => {
	it('formats a calendar date in the locale', () => {
		expect(formatDate('2026-10-11', 'en')).toBe('Oct 11, 2026');
		expect(formatDate('2026-10-11', 'de')).toBe('11.10.2026');
	});

	it('does not depend on the process time zone', () => {
		const saved = process.env.TZ;
		try {
			for (const tz of ['Pacific/Kiritimati', 'Pacific/Pago_Pago', 'UTC']) {
				process.env.TZ = tz;
				expect(formatDate('2026-03-01', 'de')).toBe('01.03.2026');
				expect(formatDate('2026-12-31', 'de')).toBe('31.12.2026');
			}
		} finally {
			if (saved === undefined) delete process.env.TZ;
			else process.env.TZ = saved;
		}
	});

	it('accepts a leap day and rejects impossible dates', () => {
		expect(formatDate('2028-02-29', 'de')).toBe('29.02.2028');
		expect(() => formatDate('2026-02-29', 'de')).toThrow(RangeError);
		expect(() => formatDate('2026-13-01', 'de')).toThrow(RangeError);
		expect(() => formatDate('2026-10-11T00:00:00Z', 'de')).toThrow(RangeError);
		expect(() => formatDate('11.10.2026', 'de')).toThrow(RangeError);
	});
});

describe('formatInstant', () => {
	it('renders the household zone, with date and time', () => {
		expect(formatInstant('2026-10-11T13:30:00Z', 'Europe/Berlin', 'de')).toBe('11.10.2026, 15:30');
		expect(formatInstant('2026-10-11T13:30:00Z', 'UTC', 'de')).toBe('11.10.2026, 13:30');
	});

	it('moves the date across midnight with the zone', () => {
		expect(formatInstant('2026-10-11T23:30:00Z', 'Europe/Berlin', 'de')).toBe('12.10.2026, 01:30');
		expect(formatInstant('2026-10-11T01:30:00Z', 'America/Los_Angeles', 'de')).toBe(
			'10.10.2026, 18:30'
		);
	});

	it('rejects a non-instant', () => {
		expect(() => formatInstant('yesterday', 'UTC')).toThrow(RangeError);
	});
});

describe('todayIso', () => {
	it('is the day in the household zone', () => {
		const now = new Date('2026-10-11T23:30:00Z');
		expect(todayIso('UTC', now)).toBe('2026-10-11');
		expect(todayIso('Europe/Berlin', now)).toBe('2026-10-12');
		expect(todayIso('America/Los_Angeles', now)).toBe('2026-10-11');
	});
});

describe('relativeDay', () => {
	it('counts days back from today, with the absolute date as title', () => {
		expect(relativeDay('2026-10-08', '2026-10-11', 'en')).toEqual({
			text: '3 days ago',
			title: 'Oct 8, 2026'
		});
		expect(relativeDay('2026-10-08', '2026-10-11', 'de')).toEqual({
			text: 'vor 3 Tagen',
			title: '08.10.2026'
		});
	});

	it('says today, yesterday and tomorrow', () => {
		expect(relativeDay('2026-10-11', '2026-10-11', 'en').text).toBe('today');
		expect(relativeDay('2026-10-10', '2026-10-11', 'en').text).toBe('yesterday');
		expect(relativeDay('2026-10-12', '2026-10-11', 'en').text).toBe('tomorrow');
		expect(relativeDay('2026-10-10', '2026-10-11', 'de').text).toBe('gestern');
	});

	it('counts across a month and a year boundary', () => {
		expect(relativeDay('2026-02-28', '2026-03-02', 'en').text).toBe('2 days ago');
		expect(relativeDay('2025-12-30', '2026-01-02', 'en').text).toBe('3 days ago');
		expect(relativeDay('2026-10-14', '2026-10-11', 'en').text).toBe('in 3 days');
	});

	it('is not moved by a daylight-saving change', () => {
		expect(relativeDay('2026-03-28', '2026-03-30', 'en').text).toBe('2 days ago');
		expect(relativeDay('2026-10-24', '2026-10-26', 'en').text).toBe('2 days ago');
	});
});

describe('formatDateRange', () => {
	it('labels an inclusive range without the year when it is one year', () => {
		expect(formatDateRange('2026-03-01', '2026-03-31', 'en-GB')).toBe('1 Mar \u2013 31 Mar');
		expect(formatDateRange('2026-03-01', '2026-03-31', 'de')).toBe('1. März \u2013 31. März');
	});

	it('writes both years when the range spans two', () => {
		expect(formatDateRange('2025-12-15', '2026-01-14', 'en-GB')).toBe(
			'15 Dec 2025 \u2013 14 Jan 2026'
		);
	});

	it('collapses a one-day range', () => {
		expect(formatDateRange('2026-03-01', '2026-03-01', 'en-GB')).toBe('1 Mar');
	});
});

describe('formatMonth', () => {
	it('names the month and year, whatever the day', () => {
		expect(formatMonth('2026-03-31', 'en')).toBe('Mar 2026');
		expect(formatMonth('2026-03-01', 'en')).toBe('Mar 2026');
	});
});
