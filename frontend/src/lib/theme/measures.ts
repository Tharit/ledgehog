// The fixed icons of the measures (design.md §6): the app's own vocabulary, never configurable. A
// measure's lead tile is `stone` wherever it is drawn, so it cannot be read for a category or an
// account of the same glyph; a chart's series colour does not change it. `review` is `inbox`, or
// `check` at zero: the review card handles the zero case itself.

import { DEFAULT_DIMENSION_COLOR } from './dimensions.js';
import type { ResolvedLook } from './resolve.js';

export const MEASURE_ICONS = {
	net_worth: 'sigma',
	income: 'hand-coins',
	expense: 'receipt',
	savings: 'piggy-bank',
	savings_rate: 'percent',
	unclassified: 'circle-question-mark',
	reconciliations: 'scale',
	transfers: 'arrow-left-right',
	openings: 'flag',
	valuations: 'gauge',
	review: 'inbox'
} as const satisfies Record<string, string>;

export type Measure = keyof typeof MEASURE_ICONS;

/** A measure's lead tile: its fixed icon, always on `stone`. */
export function measureLook(measure: Measure): ResolvedLook {
	return { icon: MEASURE_ICONS[measure], color: DEFAULT_DIMENSION_COLOR };
}
