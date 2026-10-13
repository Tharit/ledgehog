<script lang="ts">
	import { beforeNavigate, goto } from '$app/navigation';
	import type { UnitPanel } from '#lib/units/panel.svelte.js';

	// Leaving the app's page with a draft open and changed asks first (patterns §11.2), through the
	// panel's own "Discard changes?" decision: any navigation inside the app (the browser's Back, a
	// link, a keyboard shortcut) stops there; closing the tab or following an outside link gets
	// the browser's own question. Mounted once in the layout, beside the panel.
	let { panel }: { panel: UnitPanel } = $props();

	let discarding = false;

	beforeNavigate((navigation) => {
		if (discarding || !panel.flow.isDirty) return;
		navigation.cancel();
		if (navigation.willUnload || !navigation.to) return;
		const url = navigation.to.url;
		panel.requestLeave(async () => {
			discarding = true;
			try {
				await goto(url);
			} finally {
				discarding = false;
			}
		});
	});
</script>
