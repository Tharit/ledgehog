/**
 * The size every report chart shares: the full width at a fixed 288px height, so a wide window
 * does not stretch the chart (and push the table away). `aspect-auto` unsets the container's
 * default 16:9. The donut keeps its own bounded square.
 */
export const CHART_SIZE = 'aspect-auto h-72 w-full';
