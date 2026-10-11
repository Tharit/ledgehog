<script lang="ts">
	import { formatDate } from '#lib/format/index.js';

	// A calendar date in the locale's format; never shifted by a time zone (patterns §3).
	let { date, locale = 'en' }: { date: string; locale?: string } = $props();
</script>

<time datetime={date} class="whitespace-nowrap tabular-nums">{formatDate(date, locale)}</time>
