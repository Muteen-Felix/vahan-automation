# Main manufacturer report

Exported Reports contains one full-width monthly table, with an overview and
Excel export controls. The Update history panel is removed from this interface;
its internal SQL ledger remains available for ingestion and coverage checks.
Its columns are S.No, STATE, RTO, RTOCode, Maker and JAN through DEC.
Available years start at 2026; State, RTO name and RTO code support partial search.
All manufacturer rows remain accessible through pagination. Run history and Files
are no longer separate views in this section.

## Each filter writes immediately

After Apply produces a fresh populated result, Playwright downloads the complete
workbook into temporary memory/storage and posts it once to
`POST /api/jobs/{id}/main-report`. The API reads every worksheet and writes the
manufacturer/month values directly into `main_reports`. This transaction also
writes one `report_update_history` item, marks the job COMPLETED and releases the
worker. The UI event is emitted after commit, so the monthly table refreshes after
each filter. The worker waits for SQL acknowledgement before accepting the next
case and deletes its temporary export even if saving fails.

The committed result emits the private `job:status` on the `/ui` namespace and
`reports:updated` to the authenticated `reports:shared` room. Every account
viewing the main table reloads immediately on that shared event, with polling
as a fallback. Reconnecting also refreshes the table. Notification transport
failure cannot change a committed filter into a failed SQL save.

A compact confirmation above the table shows the most recent saved filter
matching the selected year/scope/search, its full save date/time, new rows,
new month values and already saved month values. An unchanged repeat explicitly
shows Already saved in main table; confirmed no data shows No record found ·
Saved in SQL. This confirmation is not a separate history table. Its metadata
comes from the committed ledger, including after opening or reloading the page.

`main_reports` physically has 12 nullable bigint columns, `jan` through `dec`.
State, RTO/code, full manufacturer name, year, meaningful report filters
and full SQL timestamps are stored on the same row. `month_sources` stores the
original source key and collection timestamp inline for each populated month.
Fuel/category scopes remain distinct so unrelated filters cannot mix counts.
Report identities and values are shared by every authenticated account; the
main table has no owner column. There are no secondary Excel, DOM or monthly-cell data tables.

- Existing values, including zero, are retained. Equal incoming values are counted
  as already saved. Only new manufacturer rows and missing months are inserted.
- Different incoming values are recorded in update history for review; existing
  values remain unchanged.
- Missing source months stay NULL and display `—`; zero displays `0`.
- Full source manufacturer names are retained. Others/Unknown, invalid counts,
  conflicting source rows or ambiguous context reject the entire filter instead
  of silently skipping a manufacturer. Paginated DOM alone cannot complete a job.
- A fresh, confirmed `No record found` writes a no-data history item with State,
  RTO, filters and full collection/save timestamps, then marks the job NO_DATA.
  It creates no fictitious manufacturer or zero counts and stores no TXT file.
- SQL errors roll back facts, history, status and worker release together. Retrying
  the same job/workbook checksum cannot add duplicate data or history.
- Overlapping office/year imports use transaction locks in a stable order.
  Independent RTOs can write concurrently.

Collection, creation and update timestamps are timezone-aware. The UI shows full
date/time in GMT+7. Completed/no-data events, focus and polling refresh the table.
The original workbook and DOM rows are not retained in SQL. CAPTCHA and failure
artifacts remain available to the operational flow.

## Migration

`0006_shared_main_reports` removes account ownership from the main table and
re-keys report scopes using the actual filter values only. It merges duplicate
State/RTO/manufacturer/year rows across accounts, fills missing months and keeps
the first committed non-null value for each month. Overlapping source values,
including any conflicts, remain in `month_sources.mergedSources`; actors remain
in the internal update ledger for attribution. Original creation/source dates
and all history entries are retained. Reads, Excel export and coverage use the
same shared scope for every authenticated account. Private job control, account
settings and operational artifacts keep their existing access checks.

`0004_main_reports` copies previous manufacturer facts into the 12-column main
table and preserves the entire update history, original row IDs, filters, dates
and month provenance. It compares every old monthly value/source/time and both
record/history counts inside the migration transaction before dropping
`annual_datasets`, `annual_records`, `annual_cells`, `annual_imports`,
`report_results`, `report_rows` and `file_rows`. Old Excel/no-data files and success
screenshots are removed from `stored_files`; technical CAPTCHA/failure storage
remains. The deployment creates a private PostgreSQL dump first and verifies its
restoration in a disposable database. Recovering retired originals requires that
backup; downgrade cannot reconstruct raw workbooks from monthly facts.

## Data coverage and continuation

The compact Data coverage card below the year overview in the right column counts unique State–RTO reports for the selected
year, filter scope and State/RTO search. Matching committed imports and confirmed
no-data results count as covered. Failed, cancelled, unrun, partial-maker and
review-only results remain missing. Repeated downloads do not increase coverage,
and a later failure cannot erase already saved data. It refreshes every five
seconds and shows the last saved office and first missing office in matrix order.

Continue rechecks coverage before creating a new session and queues only missing
office indices, including gaps before the last saved office. Ten-report error
checkpoints, Stop and saved queue recovery remain in use. The main table also
shows any attended CAPTCHA requested by the runner. An active report, another
incompatible filter scope or a historical year disables continuation. An absent office
list can be loaded before continuing. This feature adds no migration.

`POST /api/annual-reports/coverage` accepts year, dataset, state, rto and the exact
planned scenarios, returning covered/missing counts, missing matrix indices,
last saved/first missing offices and continuation availability. Evidence comes
from committed import history linked to matching source-job filters, rather than
attempt counts or manufacturer row counts.

`node scripts/test-report-coverage.mjs` checks queue selection and guards.
`verification/test_report_coverage.py` requires an explicitly named disposable
`vahan_coverage_*_test` database and covers data/no-data evidence, deduplication,
shared evidence across accounts, filter/year isolation, earlier gaps, search indices, incomplete imports
and active-job guards.

## API and verification

`GET /api/annual-reports/export` produces an Excel workbook directly from the
same shared filter scope, year and State/RTO search as the main table. It exports every
matching row across all pages, with the same 17 columns and 12 months. Zero is
preserved; missing months remain blank. Export does not create a SQL file copy.
The UI disables export while the search is pending or the view is loading.

With no State/RTO search, the UI asks for confirmation before downloading all
rows in the selected report/year; the API requires `confirmAll=true`. A single
office uses the title and filename
`Maker Month Wise Data of Port Blair DTO - AN1, Andaman & Nicobar Island (2026).xlsx`.
Multiple-office exports use All RTOs or Selected RTOs and the matching State
or All States/Multiple States. Workbook filters and frozen identity columns
support inspecting large exports. Formula-looking names are stored as text.

`GET /api/annual-reports` accepts year, dataset, state, rto, offset and limit. It
reads only `main_reports`, returning 12 values per row, available years, coverage,
search options and summary counts. Filter scope metadata is derived inline.
`GET /api/annual-reports/history` reads only `report_update_history`, with the same
filters and independent pagination. Every authenticated account can view and
export the same shared report data. The deprecated upload-excel endpoint is a compatibility alias
for the same atomic direct-save operation.

Verification uses disposable `vahan_results_*_test` databases only:

```sh
docker compose --env-file .docker.env run --rm --no-deps \
  -v "$PWD/apps/api-server:/app:ro" \
  -e VAHAN_RESULT_TEST_DATABASE=vahan_results_main_test \
  api python verification/test_report_results.py
```

`verification/test_annual_reports.py` checks full years, preserved zero/missing
values, new/missing-only imports across accounts, concurrent reversed-order imports,
shared reads/exports, filter/year isolation, search, all worksheets and no-data history. The 20 report/API checks
cover direct HTTP save and immediate readback, authentication, malformed source
rejection, cancellation, idempotence, rollback and verified filter execution.
`verification/test_main_migration.py` compares an unchanged old snapshot against
its migrated copy, including every identity, value, history entry, timestamp and
source. `test_main_live_workbook.py` replays an actual populated Port Blair workbook
into the disposable migrated database.

Worker checks: `node apps/browser-runner/test-main-report-save.mjs`, plus the
existing lifecycle, result and filter-fill checks. The UI check is
`node apps/web-ui/scripts/test-annual-reports.mjs` with Vite at port 5174; it covers
12 months, years, State/RTO search, pagination, filtered export and filenames,
confirmation accept/cancel, removal of Update history and responsive width.

## Deployed verification, 02/10/2026

API, browser worker and web Docker images were rebuilt and restarted at an idle
boundary. All four services were healthy. The final pre-migration dump was
restored successfully before deployment. A read-only comparison of that restored
snapshot against the deployed database verified all 3,103 manufacturer rows,
31,030 monthly values and 793 history entries, including unchanged original
identities, filters, timestamps and month provenance; no missing/changed or extra
values were found. Seven retired report tables and SQL report file copies were
absent. Operational CAPTCHA artifacts were unchanged.

The actual Port Blair DTO - AN1 workbook replay completed in the disposable
migrated database with 3 manufacturers and 30 existing monthly values; it added
no duplicate rows or SQL file copies. The deployed dashboard displayed those
three manufacturers with a total of 64, all 12 month columns, the retained update
history and no Run history/Files/Download controls, with zero browser errors.
Native Chrome also displayed the updated main table and subsequent live
No record found history entries with full timestamps.

The later Excel export update removes that visible history panel while retaining
the internal ledger. Its disposable-database suite includes 12 annual report,
Excel and HTTP checks; the 20 direct-save/API checks also pass. The deployed
export API was enabled at an idle boundary and all four Docker services were
healthy. Actual dashboard downloads verified a 3-manufacturer Port Blair export
(total 64), plus all 2,707 manufacturer rows in the selected 2026 scope across
28 pages. Both workbooks had 17 columns, 12 months, the expected filenames and
matching worksheet titles. Missing November/December values remained blank and
zero values remained zero. Confirmation accept/cancel, unconfirmed export
rejection and authentication were checked; no history requests or browser errors
occurred. This is a point-in-time row count, not a fixed dataset limit.

The shared-data update was backed up, restored and replayed in a disposable
database before deployment. A read-only check against the final pre-deployment
backup verified the deployed 3,103 account-separated rows became 2,707 shared
rows; all 31,030 original monthly values were accounted for, with 3,960 overlapping
months and no conflicting values. All 990 pre-deployment history entries and
existing jobs, files and sessions were preserved; later imports may add history.
The main table's owner column is absent. Fourteen annual/shared/export checks,
seven coverage checks and twenty direct-save/API checks passed. A temporary
regular account was used to verify that its table/search results equal the
administrator's results and that it downloads both the 3-row Port Blair workbook
and all 2,707 shared rows with 12 months. The temporary account was removed.

The per-filter notification fix corrects Excel completion delivery to `/ui` and
adds a shared post-commit update. Twenty-one save/API checks, fifteen annual
checks, worker save checks and the dashboard socket test pass. The HTTP test
reads newly committed manufacturer/month values from another connection at the
notification boundary; transport-failure checks retain the successful SQL save.
The UI test verifies a missing month appears within two seconds of the socket
event and that a repeated filter shows Already saved without duplicate rows.
After deploying at an idle boundary, an authenticated regular-account observer
received a real AHMEDABAD EAST - GJ27 worker commit and refreshed its main table
confirmation in 375 ms. The SQL/API result contained 24 manufacturers, all 12
months and 240 already-saved monthly values, with no added duplicates or browser
errors. The temporary observer account was removed; all four services were healthy.
