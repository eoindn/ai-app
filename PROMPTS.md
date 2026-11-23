# Prompt sequence for Claude Code

Run these in order inside the repo with Claude Code. Use **Plan mode** for step 1 and 2
(read-only until you approve the plan). Save every prompt + anything Claude got wrong
in `docs/ai-log.md` – that log is gold for the "critical reflection on AI outputs" marks.

---

## Step 0 – repo setup (humans, 10 mins)
- Create GitHub repo, add all group members, protect `main` (require PR + 1 approving review + passing checks).
- Copy in `CLAUDE.md`, `.claude/`, and put the brief PDF in `docs/brief.pdf`.
- Create labels: `requirement`, `task`, `defect`, `test`, `sev:high`, `sev:med`, `sev:low`.

## Step 1 – spec (Plan mode)
```
Read docs/brief.pdf and CLAUDE.md. Write docs/SPEC.md for the LEMMS system.

For each of the 8 application areas in the brief, write numbered requirements
(REQ-INV-01, REQ-BOOK-01, REQ-FAULT-01, REQ-MAINT-01, REQ-STAT-01, REQ-ROLE-01,
REQ-REP-01, REQ-DATA-01 ...). Each requirement must be testable: state the exact
rule, inputs, limits and expected result.

Be explicit about the rules that need decisions, and list them under
"Open decisions" for us to confirm rather than silently choosing:
- Booking: min/max duration, how far ahead, is end==next start a conflict, timezone.
- Status: full state-transition table (from, event, to, who may trigger it). Mark illegal transitions.
- Permissions: a role x action matrix for admin / technician / academic.
- Maintenance: what "overdue" means exactly (date boundary, inclusive/exclusive).
- Validation: field lengths, formats (equipment ID pattern), required fields.

Keep scope small: this is a system under test, not a product. No email, no file upload.
```
→ Humans review SPEC.md, resolve every open decision, commit on `docs/1-spec`, PR, review, merge.

## Step 2 – issues + plan (Plan mode)
```
From docs/SPEC.md, create one GitHub issue per feature slice using gh, labelled
"requirement", each listing its REQ IDs and acceptance criteria. Suggested slices:
1 project skeleton + clock + logging + health
2 auth + roles + permission matrix
3 equipment inventory CRUD + search
4 status state machine
5 bookings + conflict detection
6 fault reporting
7 maintenance scheduling + overdue
8 reporting summaries
9 seed data + README run instructions
Then output an implementation plan. Do not write code yet.
```

## Step 3 – build, one slice at a time (normal mode)
Repeat per issue (assign different issues to different group members so the
commit/PR history shows real collaboration – each person drives Claude for their slices):
```
Implement issue #<n> on a new branch following CLAUDE.md exactly.
Small conventional commits. Do not write tests. When done, run ruff and mypy,
then open a PR with gh that says "Closes #<n>" and lists the REQ IDs.
```
Then:
```
Use the code-reviewer subagent to review this branch against SPEC.md.
```
→ Paste the reviewer's table as a PR comment. A *human* group member reviews too, then merges.
Reviewer findings that are real bugs → `defect-report` skill → issues. Do NOT fix before writing a failing test.

## Step 4 – CI skeleton (one prompt, then iterate)
```
On branch ci/<n>-pipeline, create .github/workflows/ci.yml with these stages as
separate jobs, with needs: dependencies so failures are easy to read:
1 lint (ruff) + type check (mypy)
2 unit tests + coverage (pytest-cov, fail under a threshold we will set, upload HTML report as artifact, JUnit XML)
3 integration tests (FastAPI TestClient against a temp SQLite DB)
4 security: bandit + pip-audit
5 e2e + accessibility: start the app, run Playwright tests incl. axe-core scans, upload traces/screenshots on failure
6 DAST: OWASP ZAP baseline scan against the running app (on push to main)
Plus a separate workflow mutation.yml (workflow_dispatch + weekly schedule) running mutmut on app/domain
and uploading the report. Pin action versions. No secrets needed.
```

## Step 5 onward – testing (humans design, Claude helps implement)
Pattern that keeps the oracle independent of the code:
```
Here is my test design for REQ-BOOK-03 (boundary value analysis table below).
Implement exactly these cases as parametrised pytest tests in tests/unit/test_booking.py.
Derive expected results from my table and SPEC.md only – do NOT read app/ to decide what
the expected value should be. If a case fails, do not change the app or the test: report it.
<paste your BVA / EP / decision table>
```
