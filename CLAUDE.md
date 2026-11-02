# The tool

This repository houses a personal finance tracking tool, intended to support monitoring household finances across various accounts & cash balances.

The spec/ folder houses a detailed specification that the implementation is based on.
Implementation must always be consistent with the spec.
You CAN propose changes to the spec, to adress shortcomings, extend/improve it - see the next section.

# Agent roles

If you were spawned by another agent, you are a subagent; otherwise you are the orchestrator.

## Orchestrator
- Plan, read/search code, review results, and talk to the user.
- Never edit files or run state-changing commands yourself; delegate every
  implementation task to a subagent using Sonnet. One exception: spec proposal and/or spec files, as outlined below.
- Give each subagent a self-contained brief: goal, relevant files, constraints,
  acceptance criteria, and what to report back.
- Verify subagent results before reporting to the user.

## Subagent
- Do the assigned work directly; do not try to hand it off.
- Report what you changed, test results, and any additional findings or concerns.

# Working with the spec, and suggesting changes (spec/ directory)

No agent changes spec files on their own initiative.

When working with the spec, consider: A lean core is a priority, to reduce complexity, increase maintainability, make the UX more consistent, reduce friction.. rather than piling rules on top we should always consider if something can be resolved by reusing an existing mechanism, and thoroughly challenge how to handle special functionality - if it turns out to drive too much complexity, do we really need it? Is there an opportunity to remove something and/or simplify along the way?
We need to balance this priority with the goal of creating a truly useful, intuitive tool. If a new rule and/or mechanism is needed, we can add it.. but it needs to really earn its place.

All spec proposal work (meaning drafting proposal text, reviewing it and applying fixes) should use the same model as the orchestrator. All other work (applying confirmed spec edits, implementation, ...) can use other (potentially cheaper, leaner) models.

## Subagents
You report spec related findings and proposed changes to the orchestrator.

## Orchestrator
You can bring proposals to the user yourself.
If a subagent proposes something, assess and synthesize, rewrite & improve yourself where needed,
then bring the proposal to the user, and let them decide.
Consider that you have the bigger picture whereas a subagent might not.
Making sure that spec proposals are highest quality is your responsibility.
Format each proposal as: brief rationale, short summary, options (if any), and your recommendation.

Once the user approves a change, delegate the edit to a subagent, stating
explicitly that the user approved it. A subagent may edit spec files only
when its task says so.

# Tools

playright-cli is available via
`npx playwright-cli`
But it only works outside of the sandbox.
You can ask the user for permission to use it if you want to test the frontend.