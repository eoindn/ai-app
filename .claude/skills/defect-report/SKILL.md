---
name: defect-report
description: File a defect as a GitHub issue in the team's standard format. Use whenever a bug, failing test, or unexpected behaviour is found.
---

# Filing a defect

Create the issue with:
`gh issue create --label defect --label "sev:<high|med|low>" --title "DEF: <short summary>" --body-file <tmpfile>`

Body template (fill every section; write "unknown" rather than guessing):

```
## Summary
One sentence.

## Related
- Requirement: REQ-...
- Risk: RISK-... (from docs/risk-register.md, if listed)
- Found by: <test name / exploratory session / reviewer agent / CI job>

## Environment
Commit SHA, branch, OS, browser (if UI).

## Steps to reproduce
1.
2.

## Expected (per spec)

## Actual

## Evidence
Failing test output, log lines (include request_id), screenshots.

## Severity / Priority
Severity = impact if it happens. Priority = how soon to fix. Justify both in one line.

## Root cause analysis
(Filled in after investigation: what in the code causes it, and why the existing tests missed it.)

## Fix & regression
- Fix PR: #
- Regression test: path::test_name (must fail before the fix, pass after)
```

Rules: do not fix the bug while filing it. Do not weaken or delete a test to hide it.
