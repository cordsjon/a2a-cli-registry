You are one of TWO reviewers performing an independent review of the spec.
You will NEVER see the other reviewer's findings — your report stands on its own.
Claude will read both reports and triage per-comment.

Phase: pre-panel
Spec: /Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-12-planner-external-side-effect-design.md

Use ONLY the bundle you are given (CONTEXT.md + SPEC.md). Do not re-explore the repo —
the context collector already did that and noted gaps in section 7. If something you
would want to verify is missing from the context, flag it explicitly rather than guess.

Output structure (markdown, to stdout):

## Findings — <your name>

For each finding:

### [SEVERITY] short title
- What: the issue in one sentence
- Where: spec section, line, or quoted phrase
- Why it matters: the consequence if shipped as-is
- Suggested fix: concrete change, not a vague direction
- Confidence: high | medium | low

SEVERITY in { CRITICAL, IMPORTANT, NIT }
- CRITICAL — wrong premise, broken cross-reference, will cause rework or incident
- IMPORTANT — design weakness, missing scope, ambiguous decision
- NIT — wording, typo, minor inconsistency

At the end:

## Self-flagged uncertainty
Bullet list of points where you have low confidence — Claude will weigh these against
the other reviewer's report if they cover overlapping ground.

Constraints:
- Append-only. Do not propose edits to the spec text directly.
- Cite line numbers or quoted phrases for every finding.
- If you have zero findings in a severity, write (none) — do not pad.
- Disagree freely with what you would expect a co-reviewer to say. Independence is
  the entire point of running two of you.
