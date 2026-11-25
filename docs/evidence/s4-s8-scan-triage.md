# S4 and S8: static scan results and triage

Run on 2026-11-25, branch `test/2-nfr-security`.

## S4: pip-audit (dependency CVEs, OWASP A06)

| Scope | Command | Result |
|---|---|---|
| Pinned direct deps | `pip-audit -r requirements.txt --desc` | No known vulnerabilities |
| Full installed env (68 packages, incl. transitive) | `pip-audit --desc --skip-editable` | No known vulnerabilities |

Interpretation: no dependency has a published advisory in the PyPI/OSV database today.
Limits: only finds *known, published* CVEs; a clean result is a snapshot that can change tomorrow,
so it belongs in CI. Transitive deps are not pinned in `requirements.txt`, so a fresh install
may resolve different versions than the ones audited.

Raw output: `s4-pip-audit.txt`, `s4-pip-audit-installed-env.txt`

## S8: bandit (SAST, OWASP A02/A03/A05)

`bandit -r app`: 2,895 lines scanned. **0 High, 0 Medium, 1 Low.**

| ID | Location | Finding | Triage |
|---|---|---|---|
| B101 | `app/db.py:35` | `assert isinstance(value, datetime)` is removed under `python -O` | **Accepted, false positive.** The assert only narrows the type for mypy; the SQLite driver always returns a `datetime` for this column. No security decision depends on it. |

Interpretation: no hard coded secrets, no raw SQL string building, no unsafe deserialisation,
no weak hashing found. This agrees with S11 (bcrypt) and S12 (parameterised queries).
Limits: bandit matches code patterns; it cannot see logic flaws such as missing authorisation.
Defect #13 (logout without a session) is exactly that kind of flaw and bandit did not flag it,
which is why S1 and S2 are dynamic tests.

Note: `pyproject.toml` already enables ruff's `S` rules (the same checks as bandit) but ignores
`S101` globally, so ruff hides this finding while bandit reports it.

Raw output: `s8-bandit.txt`
