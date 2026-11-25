# Q4 defect log

Summary of defects found by Q4 testing. Full details, evidence and root cause are in each GitHub issue.

| ID | Defect | REQ | Severity | Found by | Found in commit | Status | Fix PR | Regression test |
|---|---|---|---|---|---|---|---|---|
| [#13](https://github.com/eoindn/ai-app/issues/13) | Logout returns 204 without a session | REQ-ROLE-01 | Low | S2 endpoint sweep | `a43b255` | Open: team to decide fix code or amend spec | | `test_s2_s3_authentication.py::test_api_requires_session[POST /api/auth/logout]` |
| [#15](https://github.com/eoindn/ai-app/issues/15) | 500 responses missing `X-Request-ID` header | REQ-DATA-06 | Low | S6 fault injection | `5a372b2` | Open | | `test_s5_s12_hardening.py::test_500_carries_request_id_header` |
| [#16](https://github.com/eoindn/ai-app/issues/16) | Search cannot find accented names, even typed exactly | REQ-INV-07 | Medium | S12 input tests | `5a372b2` | Open | | `test_s5_s12_hardening.py::test_search_treats_input_as_literal_text` (3 accented cases) |

## Status key
Open → Triaged (team agreed severity and owner) → In fix (`fix/` branch) → Fixed (PR merged, regression test passes) → Closed

## Test faults found along the way (not app defects)
These were mistakes in the AI generated tests, caught before they gave false results.

| Where | Problem | How it was caught | Fix |
|---|---|---|---|
| S2 route sweep | Found 0 API routes, so every check would pass while testing nothing | Guard test `test_route_discovery_is_not_empty` failed | Read routes from the routers instead of `app.routes` |
| S6 error test | Checked the header first; when that failed the leak checks never ran | Reviewing why only one assertion was reported | Split into two tests, one per requirement |
