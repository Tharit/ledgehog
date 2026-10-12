<script lang="ts">
	import CategoryManager from '#lib/components/settings/category-manager.svelte';
	import { CategoriesStore } from '#lib/categories/store.svelte.js';

	const store = new CategoriesStore();
</script>

<svelte:head>
	<title>Categories · Settings · Ledgehog</title>
</svelte:head>

<CategoryManager {store} />
