<script lang="ts">
	import { formatMoney } from '#lib/format/index.js';
	import { cn } from '#lib/utils.js';

	// An amount as stored: its sign written (a true minus), tabular, right aligned. Green and red
	// follow the sign only, never the category (design §2, patterns §2).
	let {
		minor,
		currency,
		locale = 'en',
		showCurrency = false,
		showPlus = true,
		class: className
	}: {
		minor: number;
		currency: string;
		locale?: string;
		showCurrency?: boolean;
		showPlus?: boolean;
		class?: string;
	} = $props();

	const text = $derived(formatMoney(minor, currency, { locale, showCurrency, showPlus }));
</script>

<span
	class={cn(
		'block amount',
		minor < 0 && 'text-amount-negative',
		minor > 0 && 'text-amount-positive',
		className
	)}>{text}</span
>
