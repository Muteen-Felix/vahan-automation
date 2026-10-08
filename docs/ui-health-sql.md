# SQL-backed UI Health and crawl preflight

UI Health appears inside Settings only when there is an unresolved check error. Its error table shows
unresolved check failures that prevent the run from continuing. The same error
across workers/retries appears once, with the affected workers and detection
time. Copy for dev copies that issue; Copy all errors copies the full alert list,
including error codes, selectors, expected/actual DOM metadata, SQL revision,
check IDs and retry information. Successful automatic repairs do not raise a
blocking alert. Errors remain in SQL after a page reload and update live when
the check fails or recovers. A successful check hides the entire UI Health section.
There is no check schedule, manual Check now button, success report, history panel
or CSV interface in Settings. Workers no longer run checks from a periodic timer.
Old `#health` links open the UI Health section in Settings.

## Run order

1. Start only the selected Docker workers and wait for their API registration.
2. Check every selected worker in an isolated browser context. At most two
   checks run concurrently; each worker gets at most two attempts.
3. Store each observation in SQL, validate it against the last approved DOM
   version, and save a grouped preflight record for the current user.
4. Only a successful preflight permits loading live filter/Maker options,
   compiling a filter profile, creating a queue or starting Maker Update.
5. Bind the successful preflight to the run. Check this binding before claiming
   further tasks. A later failed check prevents new assignments.

The same checks apply to manual runs and backend scheduled runs. Restarting a
stopped queue or starting another session requires a new preflight. Missing-case
continuation and manual failed-case retry discard the preceding run's check.
A passed check must be less than five
minutes old when starting a new run; this expiry does not interrupt a healthy
run already bound to that check.

## What is checked and updated

The initial contract covers the report form's 21 native select controls, four
year/date inputs and Apply button. The observation includes selectors, IDs,
semantic names/labels, tags, selection mode, input type, classes, roles and a
hash of option labels, values and disabled state.

A changed ID can be recovered automatically only when its existing name or
label identifies exactly one control and the expected control type and
single/multiple selection behavior still match. Approved selectors are read
from SQL by the crawler and used by the browser driver. Structural changes
create a new immutable DOM version. Option-data changes update the latest SQL
hashes and retain their observations without creating a selector version.

Missing controls, ambiguous matches, incompatible control types, unverified
semantic changes, page redirects and failed checks prevent a new run. Failed
observations never replace the last approved DOM version. Errors are tracked
per worker, so a successful check on another worker cannot erase the failure.
Errors from Docker workers outside the selected pool remain in the diagnostics
but do not block a successfully checked smaller pool.

This form check supplements the existing runtime filter verification, CAPTCHA
handling, result checks and SQL import validation. It does not prove that a
downloaded report contains correct figures or validate every possible change
to VAHAN's scripts, CAPTCHA or export controls.

## SQL records

| Store | Purpose |
| --- | --- |
| `ui_contract_versions` | Immutable approved DOM definitions and revisions. |
| `app_settings.vahan_ui_contract_active` | Active version, latest option hashes, worker errors and last check. |
| `ui_health_checks` | Individual check observations, validation and daily report data. |
| `ui_preflight_checks` | Owner, selected workers, version, PASS/BLOCKED and per-worker diagnostics. |
| `app_settings.ui_gate:<session_id>` | Preflight bound to the queue/report session. |

The API approves preflight from the stored check evidence, not from a worker's
acknowledgement alone. Approval is bound to the authenticated user, selected
workers and current SQL version. Diagnostics include the failing worker,
control, expected/observed metadata, check ID, timestamp and retry result.

## Recovery

Open Settings → UI Health, inspect Website change alerts and use Copy for dev.
After correcting the affected control or worker, retry the run to check the
selected pool again. A new successful preflight
is required before dispatch continues. Report data already saved is retained.

## Focused verification

Browser tests cover unique semantic recovery, actual driver selector aliases,
ambiguous controls, wrong types and changed option values. SQL tests cover
versioning, failed evidence, worker-specific failures, bounded retries,
ownership and blocking before Maker/options/queue creation. UI tests cover
blocked runs before Maker/queue creation, grouped alerts in Settings, persisted
diagnostics after reload, recovery, clipboard success/denial and mobile layout.
