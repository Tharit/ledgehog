// Small wording helpers the category and payee consequence lists share.

export function plural(n: number, one: string, many: string): string {
	return `${n} ${n === 1 ? one : many}`;
}
