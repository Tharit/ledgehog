// The client id an entry is created with (architecture §4.1): random, `[A-Za-z0-9_-]{1,100}`. The
// server answers a repeated id with the row already entered, so a submission keeps its id.

export function newClientId(): string {
	const crypto = globalThis.crypto;
	if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID();
	const bytes = new Uint8Array(16);
	if (typeof crypto?.getRandomValues === 'function') crypto.getRandomValues(bytes);
	else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
	return 'e' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}
