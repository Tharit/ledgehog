<script lang="ts">
	import { beforeNavigate, goto } from '$app/navigation';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';

	// Leaving a draft with changes asks first (patterns §11.2): any navigation inside the app (the
	// back link, Cancel, the settings tabs, the browser's Back) stops at "Discard changes?"; closing
	// the tab or following an outside link gets the browser's own question. The page says `dirty`
	// is false once it saves or deletes, so its own way out is not stopped.
	// `subject` says what the draft is ("this rule", "this importer").
	let { dirty, subject = 'this rule' }: { dirty: boolean; subject?: string } = $props();

	let open = $state(false);
	let target = $state<URL | null>(null);
	let discarding = false;

	beforeNavigate((navigation) => {
		if (discarding || !dirty) return;
		if (navigation.willUnload || !navigation.to) {
			navigation.cancel();
			return;
		}
		navigation.cancel();
		target = navigation.to.url;
		open = true;
	});

	function keepEditing() {
		open = false;
		target = null;
	}

	async function discard() {
		const url = target;
		open = false;
		target = null;
		if (!url) return;
		discarding = true;
		try {
			await goto(url);
		} finally {
			discarding = false;
		}
	}
</script>

<Dialog.Root
	{open}
	onOpenChange={(next) => {
		if (!next) keepEditing();
	}}
>
	<Dialog.Content class="sm:max-w-sm">
		<Dialog.Header>
			<Dialog.Title>Discard changes?</Dialog.Title>
			<Dialog.Description>The changes to {subject} have not been saved.</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" onclick={keepEditing}>Cancel</Button>
			<Button variant="destructive" onclick={discard}>Discard</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
