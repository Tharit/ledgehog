import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import InlineEdit from './inline-edit.svelte';

function edit(onsave = vi.fn<(value: string) => Promise<string | null>>().mockResolvedValue(null)) {
	const ondone = vi.fn();
	const oncancel = vi.fn();
	render(InlineEdit, { props: { value: 'Food', label: 'Name of Food', onsave, ondone, oncancel } });
	return {
		onsave,
		ondone,
		oncancel,
		input: screen.getByLabelText('Name of Food') as HTMLInputElement
	};
}

describe('InlineEdit', () => {
	it('starts focused with its text selected', async () => {
		const { input } = edit();

		await waitFor(() => expect(input).toHaveFocus());
		expect(input.value).toBe('Food');
		expect(input.selectionStart).toBe(0);
		expect(input.selectionEnd).toBe(4);
	});

	it('commits on Enter, trimmed, and is done', async () => {
		const { input, onsave, ondone } = edit();

		await fireEvent.input(input, { target: { value: '  Eating ' } });
		await fireEvent.keyDown(input, { key: 'Enter' });

		await waitFor(() => expect(ondone).toHaveBeenCalledOnce());
		expect(onsave).toHaveBeenCalledWith('Eating');
	});

	it('cancels on Esc without saving', async () => {
		const { input, onsave, oncancel } = edit();

		await fireEvent.input(input, { target: { value: 'Eating' } });
		await fireEvent.keyDown(input, { key: 'Escape' });

		expect(oncancel).toHaveBeenCalledOnce();
		expect(onsave).not.toHaveBeenCalled();
	});

	it('commits a changed non-empty value on blur', async () => {
		const { input, onsave, ondone } = edit();

		await fireEvent.input(input, { target: { value: 'Eating' } });
		await fireEvent.blur(input);

		await waitFor(() => expect(ondone).toHaveBeenCalledOnce());
		expect(onsave).toHaveBeenCalledWith('Eating');
	});

	it('cancels an unchanged value on blur', async () => {
		const { input, onsave, oncancel } = edit();

		await fireEvent.blur(input);

		expect(oncancel).toHaveBeenCalledOnce();
		expect(onsave).not.toHaveBeenCalled();
	});

	it('cancels an empty value on blur', async () => {
		const first = edit();
		await fireEvent.input(first.input, { target: { value: '   ' } });
		await fireEvent.blur(first.input);
		expect(first.oncancel).toHaveBeenCalledOnce();
		expect(first.onsave).not.toHaveBeenCalled();
	});

	it('stays open with the refusal under the field', async () => {
		const { input, onsave, ondone, oncancel } = edit(
			vi.fn<(value: string) => Promise<string | null>>().mockResolvedValue('Taken.')
		);

		await fireEvent.input(input, { target: { value: 'Travel' } });
		await fireEvent.keyDown(input, { key: 'Enter' });

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('Taken.');
		expect(alert).toHaveClass('text-destructive');
		expect(input).toHaveAttribute('aria-invalid', 'true');
		expect(onsave).toHaveBeenCalledOnce();
		expect(ondone).not.toHaveBeenCalled();
		expect(oncancel).not.toHaveBeenCalled();
		expect(screen.getByLabelText('Name of Food')).toBeInTheDocument();
	});

	it('clears the refusal when the value is edited again, and can then save', async () => {
		const onsave = vi
			.fn<(value: string) => Promise<string | null>>()
			.mockResolvedValueOnce('Taken.')
			.mockResolvedValueOnce(null);
		const { input, ondone } = edit(onsave);

		await fireEvent.input(input, { target: { value: 'Travel' } });
		await fireEvent.keyDown(input, { key: 'Enter' });
		await screen.findByRole('alert');
		await fireEvent.input(input, { target: { value: 'Trips' } });
		expect(screen.queryByRole('alert')).toBeNull();
		await fireEvent.keyDown(input, { key: 'Enter' });

		await waitFor(() => expect(ondone).toHaveBeenCalledOnce());
		expect(onsave).toHaveBeenLastCalledWith('Trips');
	});

	it('saves once when Enter is followed by the blur of its own unmounting', async () => {
		const { input, onsave } = edit();

		await fireEvent.input(input, { target: { value: 'Eating' } });
		await fireEvent.keyDown(input, { key: 'Enter' });
		await fireEvent.blur(input);

		await waitFor(() => expect(onsave).toHaveBeenCalledOnce());
	});
});
