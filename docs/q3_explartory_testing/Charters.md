# Q3 Exploratory, Usability and Accessibility Testing: Charters

**Tester:** Luca Hamblen (2413720)
**Module:** CPS6002, Assessment 2, Q3
**Application:** LEMMS (Laboratory Equipment & Maintenance Management System)
**Source of requirements:** docs/SPEC.md
**Branch:** q3-exploratory-accessibility

## Purpose
One or two sentences on what this document is: the plan for my exploratory,
usability and accessibility testing, written from the spec before running sessions.

## Approach
- Session-based exploratory testing: one charter per time-boxed session (30-60 min)
- Charter format: Explore [area] with [approach] to discover [risk]
- Usability judged against Nielsen's 10 heuristics
- Accessibility judged against WCAG 2.2 AA, using axe, Lighthouse, WAVE and keyboard/screen reader checks
- Every defect is filed as a GitHub issue and linked back to its charter

## Environment (fill in when you run the sessions)
- Build / commit hash:
- Browser and version:
- Start-up: python -m app.seed, then uvicorn app.main:app --reload
- Test users / roles: admin, technician, academic (Not Logged In)


## Charter overview
| ID | Mission (short) | REQ IDs | Status |
|----|-----------------|---------|--------|
| LH-01 | ... | ... | Not started |


## LH-01 = access level control
**mission**: Explore access controls by attempting forbidden actions as each role to discover whether access controls work and restricted actions are not able to be executed.
**Req ID's** REQ-ROLE-01, 05, 06, REQ-INV-09, REQ-BOOK-11, 12, 13, REQ-FAULT-04, REQ-MAINT-01
**Risks**  user can see or change data they shouldn't be able to access, even if teh button is hidden in the UI.
**Role / data:** admin. technician, academic, Fresh seed data.

### ideas to try(expected results from the spec):
| # | Action | Role | Expected |
|---|--------|------|----------|
|1|open any page while logged out|none|redirect to login page|
|2|create edit or delete equipment|academic|Refused (403)|
|3|create,edit or delete equipment|technician |Refused (403)|
|4|open users page by typing url|academic|Refused (403)|
|5|View all bookings (scope=all)|academic|Refused (403)|
|6|Open another user's booking by ID|academic|Refused (403)|
|7|Cancel another user's booking|academic|Refused (403)|
|8|Change a fault's status | academic | Refused (403)|
|9|Schedule maintenance|technician|Refused (403)|
|10|Use the back button after logging out|any|No private data shown, redirect to login|

### Session Details
## Notes *to be filled out when build is run!!!!!!!!



## LH-02 = fault reporting

**Mission**: Explore the fault reporting form and fault lifecycle by entering empty, very long and special-character input and attempting restricted status changes, to discover whether invalid faults are accepted, valid faults are lost or displayed wrong, and whether illegal status changes are blocked.

**Req IDs**: REQ-FAULT-01, 02, 03, 04, 05, 06

**Risks**: Invalid or unsafe text is saved or displayed wrongly, faults are lost or listed in the wrong order, a user without permission changes a fault's status, or reporting a fault changes the equipment status when it shouldn't.

**Role**: academic, technician, admin. 
**data**: Fresh seed data.
### Ideas to try (expected results from the spec):
| # | Action | Role | REQ | Expected |
|---|--------|------|-----|----------|
|1|Report a fault with valid title, description and severity|academic|FAULT-01|201, status OPEN, reported by and time recorded|
|2|Report a fault with an empty title|academic|FAULT-01| 422, message names the field|
|3|Report a fault with an empty description |academic| FAULT-01|422|
|4|Report a fault with a very long title or description|academic|FAULT-01| 422|
|5|Enter special characters and quotes in the description| academic|FAULT-01|Saved or rejected safely, text shown as plain text, no script runs|
|6|Report a fault with each severity (LOW, MEDIUM, HIGH, CRITICAL)|academic|FAULT-01|All accepted|
|7|Report a fault with an invalid severity |academic|FAULT-01|422|
|8|Report a fault against an equipment ID that doesn't exist|academic|FAULT-02|404|
|9|Report a fault against equipment that is OUT_OF_SERVICE|academic|FAULT-02|Accepted|
|10|Open the fault list|academic|FAULT-03|Faults sorted oldest first|
|13|Change a fault's status|academic|FAULT-04|403|
|14|Move a fault through its lifecycle|technician|FAULT-04|Each legal step accepted|
|15|Try an illegal status change|technician|FAULT-04|409 ILLEGAL_TRANSITION, status unchanged|
|16|Resolve a fault with no notes|technician|FAULT-05|422|


### Session Details


### Notes 



## LH-03 = usability: error messages and feedback

**Mission**: Explore the error messages and feedback across the app by deliberately triggering each error type (401, 403, 404, 409, 422) as each role, to discover messages that are unclear, unhelpful, inconsistent or that leak internal details.

**Req IDs**: REQ-DATA-02, REQ-DATA-04, REQ-ROLE-02, REQ-BOOK-07, REQ-INV-02, REQ-ROLE-05

**Risks**: Users can't tell what went wrong or how to fix it, errors look different on each page, entered data is lost after an error, or an error shows internal details (stack traces, SQL, file paths).

**Heuristics used**: Nielsen's #1 visibility of system status, #5 error prevention, #9 help users recognise, diagnose and recover from errors, #4 consistency.

**Role**: admin, technician, academic.
**data**:  Fresh seed data.

### Ideas to try (expected results from the spec and heuristics):
|#|Action|Role|REQ|Expected|
|-|------|----|---|--------|
|1|Log in with a wrong password|none|ROLE-02|Refused (401), message does not say whether the username or password was wrong|
|2|Log in with an unknown username|none|ROLE-02|Same message as row 1 (no user enumeration)|
|3|Submit a booking with end before start|academic|DATA-02|422, message names the field and says what is wrong|
|4|Submit a form with several invalid fields at once|academic|DATA-02|One message per invalid field|
|5|After a validation error, check the form|academic|Heuristic 9|Values I typed are still there|
|6|Create equipment with an ID that already exists|admin|INV-02|409, message says the ID is taken|
|7|Book a slot that overlaps another booking|academic|BOOK-07|409, message says the slot is unavailable|
|8|Do a forbidden action (for example create equipment)|academic|ROLE-05|403, message says I'm not allowed, not a blank page|
|9|Open a page for equipment that doesn't exist (bad ID in the URL)|any|DATA-02|404, clear "not found" page with a way back|
|10|Compare error styling across booking, fault, equipment and maintenance forms|any|Heuristic 4|Same look, position and wording style on every page|
|11|Check that errors are visible without relying on colour alone|any|Heuristic 1|Text or icon as well as colour|
|12|After a successful action (booking, fault report, status change)|any|Heuristic 1|Clear confirmation shown|
|13|Look at every error for technical details|any|DATA-04|No stack trace, SQL, file path or internal names|
|14|Check the error page navigation|any|Heuristic 9|A link back to somewhere useful|

### Session Details


### Notes

## LH-04 = usability: first-time academic journey

**Mission**: Explore the main journey of a first-time academic user (log in, find equipment, book it, check and cancel the booking, report a fault) without instructions, to discover confusing navigation, unclear labels, missing guidance or feedback that stops a new user completing their task.

**Req IDs**: REQ-ROLE-02, REQ-INV-07, REQ-BOOK-01, REQ-BOOK-13, REQ-BOOK-14, REQ-FAULT-01

**Risks**: A new user can't find or complete a core task, doesn't know whether an action worked, or makes mistakes because the interface is unclear.

**Heuristics used**: Nielsen's #1 visibility of system status, #2 match between system and real world, #3 user control and freedom, #4 consistency, #6 recognition rather than recall, #7 flexibility and efficiency of use.

**Role** :academic, Act as someone who has never seen the app: no reading the spec or code first.

**data**:  Fresh seed data. 

### Ideas to try (expected results from the spec and heuristics):
|#|Action|Role|REQ|Expected|
|---|---|---|---|---|
|1|Open the app for the first time and log in|academic|ROLE-02|Login page is obvious, fields are labelled, a successful login lands on a useful page|
|2|Look at the dashboard without clicking anything|academic|Heuristic 1|I can tell where I am and what I can do next|
|3|Find a specific piece of equipment using search|academic|INV-07|Search is easy to find, results are clear, "no results" is explained|
|4|Open an equipment page|academic|Heuristic 2|Status and details are in plain language, a booking option is easy to find|
|5|Book the equipment for tomorrow|academic|BOOK-01|I can complete the form without help, the format of date and time is clear|
|6|Check what happens straight after submitting|academic|Heuristic 1|Clear confirmation that the booking was made, with the details|
|7|Find my booking afterwards|academic|BOOK-01|Easy to find from the navigation, shows my booking correctly|
|8|Cancel my booking|academic|BOOK-13|Cancel is easy to find, there is a confirmation or clear result|
|9|Try to cancel a booking that has already started|academic|BOOK-14|Refused, and the message explains why|
|10|Report a fault on a piece of equipment|academic|FAULT-01|Form is clear, severity options are understandable, confirmation shown|
|11|Check navigation labels and menu across pages|academic|Heuristic 4|Same names and positions everywhere, nothing for other roles shown|
|12|Make a mistake and try to go back or undo it|academic|Heuristic 3|There is a clear way to go back or correct it|
|13|Log out|academic|Heuristic 1|Logout is easy to find and clearly ends the session|
|14|Record how long the whole journey takes and where I hesitated|academic|Heuristic 7|Each hesitation is a possible usability issue, so note where it happened|

### Session Details


### Notes
