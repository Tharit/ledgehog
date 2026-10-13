<script lang="ts">
	import TagManager from '#lib/components/settings/tag-manager.svelte';
	import { TagsStore } from '#lib/tags/store.svelte.js';

	const store = new TagsStore();
</script>

<svelte:head>
	<title>Tags · Settings · Ledgehog</title>
</svelte:head>

<TagManager {store} />
