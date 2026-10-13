export const RULES_PATH = '/settings/rules';

export const NEW_RULE_PATH = `${RULES_PATH}/new`;

export function ruleUrl(id: number): string {
	return `${RULES_PATH}/${id}`;
}
