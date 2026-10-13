import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import LoginForm from './login-form.svelte';

describe('LoginForm', () => {
	it('submits the trimmed login and the password', async () => {
		const onsubmit = vi.fn();
		render(LoginForm, { props: { onsubmit } });

		await fireEvent.input(screen.getByLabelText('Login'), { target: { value: ' ada ' } });
		await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'secret' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

		expect(onsubmit).toHaveBeenCalledExactlyOnceWith('ada', 'secret');
	});

	it('does not submit empty fields', async () => {
		const onsubmit = vi.fn();
		render(LoginForm, { props: { onsubmit } });

		await fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

		expect(onsubmit).not.toHaveBeenCalled();
	});

	it('shows an error inline, as an alert', () => {
		render(LoginForm, { props: { onsubmit: vi.fn(), error: 'Wrong login or password.' } });

		expect(screen.getByRole('alert')).toHaveTextContent('Wrong login or password.');
	});

	it('shows no alert without an error', () => {
		render(LoginForm, { props: { onsubmit: vi.fn() } });

		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});

	it('disables the button while pending and says what it is doing', () => {
		render(LoginForm, { props: { onsubmit: vi.fn(), pending: true } });

		expect(screen.getByRole('button', { name: 'Logging in…' })).toBeDisabled();
	});

	it('masks the password and names the fields for the browser', () => {
		render(LoginForm, { props: { onsubmit: vi.fn() } });

		expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
		expect(screen.getByLabelText('Login')).toHaveAttribute('autocomplete', 'username');
	});
});
