// The rule shapes the components may name. Components never import `lib/api` (they take data as
// props); the shapes they receive are re-exported here so they can still be typed.
export type {
	Rule,
	RuleError,
	RuleFields,
	RulePreview,
	RulePreviewList,
	RulePreviewRow,
	RuleSets
} from '#lib/api/rules.js';
