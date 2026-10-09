# The tool

This repository houses a personal finance tracking tool, intended to support monitoring household finances across various accounts & cash balances.

The spec/ folder houses a detailed specification that the implementation is based on.
Implementation must always be consistent with the spec.
You CAN propose changes to the spec, to adress shortcomings, extend/improve it - see the next section.

# Working with the spec, and suggesting changes

You must not change the spec files on your own independently.
Instead, first present your proposal to the user, and let them decide.
Proposal should be formatted to include a brief rationale for the desired change, a short summary, and different options if there are any.

Consider: A lean core is a priority, to reduce complexity, increase maintainability, make the UX more consistent, reduce friction.. rather than piling rules on top we should always consider if something can be resolved by reusing an existing mechanism, and thoroughly challenge how to handle special functionality - if it turns out to drive too much complexity, do we really need it? Is there an opportunity to remove something and/or simplify along the way?
We need to balance this priority with the goal of creating a truly useful, intuitive tool. If a new rule and/or mechanism is needed, we can add it.. but it needs to really earn its place.