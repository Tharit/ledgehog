<script lang="ts">
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import ActionButton from '#lib/components/common/action-button.svelte';
	import ActionDialog, { type DialogFeedback } from '#lib/components/common/action-dialog.svelte';
	import ChoiceSelect from '#lib/components/common/choice-select.svelte';
	import Field from '#lib/components/common/field.svelte';
	import { Input } from '#lib/components/ui/input/index.js';
	import { formatTime } from '#lib/format/index.js';
	import type { OpenPrompt } from '#lib/sync/events.js';
	import { CANCEL_SENTENCE, promptFieldLabel, promptTitle, promptVerb } from '#lib/sync/prompts.js';

	// The dialog that asks when a task is blocked (ux/views/sync.md "Prompts"): a form dialog titled by
	// what it asks and the login, described by the moment, showing the bank's own words as given. It is
	// rendered by the page that hosts the task, and only while the prompt is open: it closes when the
	// server says the prompt is resolved, never on the answer's own reply. "Cancel" and Esc cancel the
	// prompt, which ends that login's sync; a sync's dialog also offers "Stop sync…".
	let {
		prompt,
		login,
		moment,
		timeZone = 'UTC',
		locale = 'en',
		sending = false,
		fieldError = null,
		sendError = null,
		canStop = false,
		onanswer,
		oncancel,
		onstop
	}: {
		prompt: OpenPrompt;
		/** the label of the login the prompt belongs to */
		login: string;
		/** "Signing in." or "Fetching Giro." */
		moment: string;
		timeZone?: string;
		locale?: string;
		/** the answer is on its way, or accepted and not yet resolved */
		sending?: boolean;
		/** the server's refusal of the answer, under the field */
		fieldError?: string | null;
		/** a failure to send, above the buttons */
		sendError?: string | null;
		/** a sync's prompt offers "Stop sync…"; a discovery's does not */
		canStop?: boolean;
		onanswer: (value: string) => void;
		oncancel: () => void;
		onstop?: () => void;
	} = $props();

	const body = $derived(prompt.body);
	const verb = $derived(promptVerb(body));
	const fieldLabel = $derived(promptFieldLabel(body));
	const decoupled = $derived(body.kind === 'tan' && body.medium === 'decoupled');
	let value = $state('');

	const feedback = $derived<DialogFeedback | null>(
		sendError ? { kind: 'error', text: sendError } : null
	);
	const image = $derived(
		body.kind === 'tan' && body.medium === 'image' && body.image_b64
			? `data:${body.image_mime ?? 'image/png'};base64,${body.image_b64}`
			: null
	);
</script>

<ActionDialog
	open={true}
	onclose={oncancel}
	title={promptTitle(body, login)}
	description={moment}
	verb={verb ?? undefined}
	busyVerb="Sending…"
	busy={sending}
	onsubmit={() => onanswer(value)}
	{feedback}
>
	{#if body.kind === 'tan'}
		<p class="whitespace-pre-wrap text-muted-foreground" data-slot="prompt-challenge">
			{body.challenge}
		</p>
		{#if body.method}
			<p data-slot="prompt-method">TAN method: {body.method}</p>
		{/if}
		{#if image}
			<img
				src={image}
				alt="photoTAN challenge"
				class="max-h-64 max-w-full self-start rounded-md border border-border"
				data-slot="prompt-image"
			/>
		{/if}
	{/if}

	{#if decoupled}
		<p class="flex items-center gap-2" role="status" data-slot="prompt-waiting">
			<LoaderCircleIcon
				size={16}
				strokeWidth={1.75}
				class="shrink-0 animate-spin text-muted-foreground"
				aria-hidden="true"
			/>
			<span> Confirm in your banking app. This closes when the bank has your confirmation. </span>
		</p>
	{:else if body.kind === 'choice' && fieldLabel}
		<Field label={fieldLabel} error={fieldError}>
			{#snippet children(control)}
				<ChoiceSelect
					{...control}
					label={fieldLabel}
					options={body.options.map((o) => ({ value: o.id, label: o.label }))}
					{value}
					disabled={sending}
					onchange={(next) => (value = next)}
				/>
			{/snippet}
		</Field>
	{:else if fieldLabel}
		<Field label={fieldLabel} error={fieldError}>
			{#snippet children(control)}
				<Input
					{...control}
					type={body.kind === 'secret' ? 'password' : 'text'}
					bind:value
					readonly={sending}
					autocomplete="off"
				/>
			{/snippet}
		</Field>
	{/if}

	<p class="text-xs text-muted-foreground" data-slot="prompt-expiry">
		Expires at {formatTime(prompt.expiresAt, timeZone, locale)}
	</p>
	<p class="text-xs text-muted-foreground" data-slot="prompt-cancel-note">{CANCEL_SENTENCE}</p>

	{#snippet secondary()}
		{#if canStop}
			<ActionButton variant="outline" disabled={sending} onclick={onstop}>Stop sync…</ActionButton>
		{/if}
	{/snippet}
</ActionDialog>
