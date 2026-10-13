<script lang="ts" module>
	/** What a failed or moved write says in the dialog's feedback slot (patterns §11.5). */
	export type DialogFeedback = {
		/** `error`: nothing was written. `conflict`: the world moved, ask again. `report`: partly done. */
		kind: 'error' | 'conflict' | 'report';
		text: string;
		/** the lines of a report */
		lines?: readonly string[];
		/** "Reload" and the like */
		action?: { label: string; onclick: () => void };
	};
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import ActionButton from './action-button.svelte';

	// The one dialog shape (patterns §11.1, §11.2): title, a body, a feedback slot above the footer,
	// and Cancel plus the verb at the right of the footer, Cancel first.
	//  - `form`: a small reversible add or edit. The body is a <form>; Enter submits from any field
	//    (the verb button is its submit button); focus starts in the first field.
	//  - `decision`: a decision about named consequences (delete, merge). Enter never confirms;
	//    a destructive one starts with focus on Cancel, any other on its find box or the verb.
	//  - `pick`: a pick from a menu item. Cancel only; choosing is the body's own act.
	// While `busy` both buttons are disabled and nothing dismisses it. Esc, Cancel, the close button
	// and a click outside all end in `onclose`. The caller owns `open`.
	let {
		open,
		onclose,
		title,
		description,
		mode = 'form',
		verb,
		busyVerb,
		destructive = false,
		busy = false,
		disabled = false,
		onsubmit,
		feedback = null,
		width = 'md',
		oncloseautofocus,
		children
	}: {
		open: boolean;
		onclose: () => void;
		/** the question or the action with its object: "Delete Food?" */
		title: string;
		description?: string;
		mode?: 'form' | 'decision' | 'pick';
		/** the verb of the action: "Add", "Save", "Delete", "Merge", "Tag 214 entries" */
		verb?: string;
		/** the verb while it runs: "Saving…" */
		busyVerb?: string;
		/** the action deletes: the verb button is destructive and focus starts on Cancel */
		destructive?: boolean;
		busy?: boolean;
		/** the verb button cannot be pressed yet (nothing to do, still loading) */
		disabled?: boolean;
		onsubmit?: () => void;
		feedback?: DialogFeedback | null;
		width?: 'sm' | 'md' | 'lg';
		/** what happens to focus when the dialog has closed; `preventDefault` to place it yourself */
		oncloseautofocus?: (event: Event) => void;
		/** the body: fields, a picker, a consequence list */
		children: Snippet;
	} = $props();

	const WIDTH = { sm: 'sm:max-w-sm', md: 'sm:max-w-md', lg: 'sm:max-w-lg' } as const;

	let content = $state<HTMLElement | null>(null);

	function request(next: boolean) {
		if (!next && !busy) onclose();
	}

	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!busy && !disabled) onsubmit?.();
	}

	// Initial focus (patterns §11.2): the first field of the body (the form's first field, a find
	// box), except that a destructive decision starts on Cancel; a decision without a field starts
	// on its verb. Set here rather than left to the focus trap's "first tabbable", so that it is
	// the same everywhere.
	function autofocus(event: Event) {
		if (!content) return;
		const cancel = content.querySelector<HTMLElement>('[data-role="cancel"]');
		const confirm = content.querySelector<HTMLButtonElement>('[data-role="verb"]');
		const field = content.querySelector<HTMLElement>(
			'[data-slot="dialog-body"] :is(input:not([type="hidden"]), textarea, select)'
		);
		if (mode === 'decision' && destructive) {
			event.preventDefault();
			cancel?.focus();
		} else if (field) {
			event.preventDefault();
			field.focus();
		} else if (mode === 'decision') {
			event.preventDefault();
			(confirm && !confirm.disabled ? confirm : cancel)?.focus();
		}
	}
</script>

{#snippet inner()}
	<div class="flex flex-col gap-3 text-sm" data-slot="dialog-body">{@render children()}</div>

	{#if feedback}
		<div data-slot="dialog-feedback" data-kind={feedback.kind} class="flex flex-col gap-1 text-sm">
			{#if feedback.kind === 'conflict'}
				<p role="status">{feedback.text}</p>
			{:else if feedback.kind === 'report'}
				<div role="alert" class="flex flex-col gap-1">
					<p>{feedback.text}</p>
					{#if feedback.lines && feedback.lines.length > 0}
						<ul class="flex list-disc flex-col gap-0.5 pl-5">
							{#each feedback.lines as line, i (i)}<li>{line}</li>{/each}
						</ul>
					{/if}
				</div>
			{:else}
				<p role="alert" class="text-destructive">{feedback.text}</p>
			{/if}
			{#if feedback.action}
				<div>
					<ActionButton variant="link" class="h-auto p-0" onclick={feedback.action.onclick}>
						{feedback.action.label}
					</ActionButton>
				</div>
			{/if}
		</div>
	{/if}

	<Dialog.Footer>
		<ActionButton variant="outline" data-role="cancel" disabled={busy} onclick={() => onclose()}>
			Cancel
		</ActionButton>
		{#if mode !== 'pick' && verb}
			<ActionButton
				type={mode === 'form' ? 'submit' : 'button'}
				variant={destructive ? 'destructive' : 'primary'}
				data-role="verb"
				{busy}
				busyLabel={busyVerb}
				{disabled}
				onclick={mode === 'form' ? undefined : () => onsubmit?.()}
			>
				{verb}
			</ActionButton>
		{/if}
	</Dialog.Footer>
{/snippet}

<Dialog.Root {open} onOpenChange={request}>
	<Dialog.Content
		bind:ref={content}
		class={WIDTH[width]}
		data-mode={mode}
		onOpenAutoFocus={autofocus}
		onCloseAutoFocus={oncloseautofocus}
	>
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			{#if description}<Dialog.Description>{description}</Dialog.Description>{/if}
		</Dialog.Header>
		{#if mode === 'form'}
			<form class="contents" onsubmit={submit}>{@render inner()}</form>
		{:else}
			{@render inner()}
		{/if}
	</Dialog.Content>
</Dialog.Root>
