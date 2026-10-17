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
  implementation task to a subagent.
- Give each subagent a self-contained brief: goal, relevant files, constraints,
  acceptance criteria, and what to report back.
- Verify subagent results before reporting to the user.

## Subagent
- Do the assigned work directly; do not try to hand it off.
- Report what you changed, test results, and any additional findings or concerns.

# Working with the spec, and suggesting changes (spec/ directory)

- Nobody changes spec files on their own initiative.
- Subagents: report findings and proposed changes to the orchestrator.
- Orchestrator: assess and synthesize proposals, bring them to the user, and let
  them decide. Format each as: brief rationale, short summary, options (if any),
  and your recommendation.
- Once the user approves a change, delegate the edit to a subagent, stating
  explicitly that the user approved it. A subagent may edit spec files only
  when its task says so.

Consider: A lean core is a priority, to reduce complexity, increase maintainability, make the UX more consistent, reduce friction.. rather than piling rules on top we should always consider if something can be resolved by reusing an existing mechanism, and thoroughly challenge how to handle special functionality - if it turns out to drive too much complexity, do we really need it? Is there an opportunity to remove something and/or simplify along the way?
We need to balance this priority with the goal of creating a truly useful, intuitive tool. If a new rule and/or mechanism is needed, we can add it.. but it needs to really earn its place.

# Tools

playright-cli is available via
`npx playwright-cli`