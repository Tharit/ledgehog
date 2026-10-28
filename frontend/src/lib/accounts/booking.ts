// How a booking says where it came from (spec §5.8; patterns §4.5): from its document, or from the
// charge on a clearance account it is the counter-leg of. Only navigation data is read here.
import type { Booking } from '#lib/types/domain.js';

/** "Booked from amazon order 304-1" or "Booked from Amazon clearing’s charge". */
export function bookedFromText(
	booking: Pick<Booking, 'kind' | 'provider' | 'reference'>,
	accountName: string | null
): string {
	if (booking.kind === 'transfer') return `Booked from ${accountName ?? 'an account'}’s charge`;
	if (!booking.provider) return 'Booked from a document';
	return `Booked from ${booking.provider} order${booking.reference ? ` ${booking.reference}` : ''}`;
}

/** Where a booking's source opens: its document's page; a charge has none (its unit opens in review). */
export function bookingDocumentHref(booking: Pick<Booking, 'kind' | 'id'>): string | null {
	return booking.kind === 'document' ? `/documents/${booking.id}` : null;
}
