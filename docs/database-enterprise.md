# PostgreSQL: capacity and enterprise deployment

This upgrade targets the existing single PostgreSQL control plane and ten browser workers. It reduces avoidable reads/writes, bounds resource usage and preserves transactional report delivery. It does not provide automatic failover or guarantee uptime after loss of the host/database.

## Findings from the local database

The initial inspection found approximately 4.9 GB: `stored_files` 1.67 GB, `job_events` 1.59 GB, `jobs` 1.23 GB. Exact sampling found about 45,000 jobs, 506,000 job events and 75,000 artifacts. Old job JSON still contains image bytes; most stored artifacts are historical CAPTCHA images or screenshots. No historical report, job, audit or artifact is deleted by this upgrade. Disk use may initially increase because indexes are added; compact new events prevent repeating entire job snapshots going forward.

## Implemented behavior

| Area | Implementation | Purpose |
|---|---|---|
| Job identity | Relational `case_id`, `retry_of_job_id`, `scenario_name`, `source`; migration backfills from existing payload | Group logical cases and resolve retries without loading image-bearing job JSON |
| Run history | Coalesced SQL summaries with a bounded 2-second cache; session listing defaults to 100, maximum 200; detail pages default to 100, maximum 500 | Avoid transferring every job/artifact on refresh; preserve counts and legacy retry grouping |
| Other lists | `/api/jobs` defaults to 100, max 1,000; `/api/files` defaults to 100, max 500; use `offset` and `limit` | Bound response size; callers must page to retrieve the full list |
| Queue | Lock/reconcile only processing/failed cases; status/error projections; checkpoint and final retry policy preserved | Shorten locked transactions and avoid transferring unrelated full filters/payloads |
| Job events | Version 2 compact status/error/checksum metadata; filter proof only on verification events | Preserve transaction/audit semantics with less write amplification |
| Excel | Repeatable-read, read-only snapshot; SQL batches of 1,000; write-only workbook; temporary FileResponse deleted after send or cancellation | Preserve every row, null/zero and safe text while avoiding an entire workbook in RAM |
| Heavy operations | At most 2 parses/exports per API process; busy admission returns 503 | Leave resources available for heartbeat, assignment and normal reads |
| Overload | Pool/statement/lock pressure returns 503 with `Retry-After: 3`; DB transaction rollback remains automatic | Fail promptly instead of holding requests indefinitely; never globally replay writes |
| Runner saves | Only checksum/idempotency-protected report commits retry explicit SQL-pressure codes; max 8 attempts, 15-second maximum backoff | Keep downloaded reports until SQL confirms the save; do not repeat Apply or ambiguous transport failures |
| Observability | Admin-only `/api/database/status`: pool use, connection/lock activity, estimated rows, table size, auto-vacuum/analyze timestamps | Identify capacity and storage pressure without returning SQL values or secrets |
| Runtime access | Short-lived administrative `migrate` service provisions a DML-only API role, grants default table permissions and owns schema migration; API receives no owner credential | Limit runtime database privilege; API starts only after successful migration |
| Maintenance | Migration 0013 adds targeted indexes, concurrent index construction, invalid-index recovery, and 5% vacuum/2% analyze thresholds on hot tables | Limit blocking and keep plans/statistics current |

Run-list summaries and annual report pages use namespace-separated, bounded 2-second caches. Display freshness also depends on query latency and the UI refresh interval. Detail pages and committed-save acknowledgements remain uncached; cached display data never authorizes a write. Delete/restore invalidates run lists; report import invalidates annual report pages. Concurrent requests for the same owner/page share one query.

Full report content/provenance stays in the existing main tables. `NO_DATA` remains a confirmed successful empty result; it is not converted into a retryable error. A failed database transaction cannot acknowledge a saved report.

## Connection budget

Default settings are per API process:

```dotenv
VAHAN_DB_POOL_SIZE=10
VAHAN_DB_MAX_OVERFLOW=5
VAHAN_DB_POOL_TIMEOUT_SECONDS=5
VAHAN_DB_STATEMENT_TIMEOUT_MS=60000
VAHAN_DB_LOCK_TIMEOUT_MS=5000
VAHAN_DB_IDLE_TRANSACTION_TIMEOUT_MS=30000
VAHAN_BULK_OPERATION_CONCURRENCY=2
```

Maximum API connections = process count × (pool size + overflow). With PostgreSQL `max_connections=100`, reserve at least 20 for migrations, monitoring and operational access. Do not add API processes/replicas without recalculating this budget. Browser workers connect to the API, not directly to PostgreSQL. Consider PgBouncer only when multiple API instances justify it; transaction pooling must first be tested with asyncpg prepared statements and the application's transaction-scoped advisory locks.

Timeouts apply to API connections, not global PostgreSQL settings or migration connections. Keep `fsync`, `full_page_writes`, WAL and `synchronous_commit` enabled. A longer legitimate import may have many individually bounded statements; the statement timeout is not a total transaction deadline.

## Operations

1. Build/test the deployment sources before changing the running service. If unrelated work is being edited in the shared checkout, use an isolated worktree with its own build context and the same intended deployment version.
2. Take a consistent custom-format backup with `python3 scripts/backup-docker.py`. It stores the dump and required encryption/signing configuration with restrictive permissions. Keep a second encrypted copy off the host.
3. Restore that dump into a uniquely named disposable `_test` database with `pg_restore --exit-on-error`. Verify row counts, migration, indexes and representative summaries there before upgrading the live database.
4. Before API/runner deployment, atomically change the SQL worker-pool phase from `ready` to `updating`. Let current jobs and option-planning leases finish; do not cancel cases merely to deploy.
5. Apply the additive migration with no unfinished jobs. Recreate only API/Web/runners when their source changed; preserve PostgreSQL and its named volume. Restore assignment only after services are ready. Previously paused batches must stay paused.
6. Verify `/api/ready`, Web HTTP status, runner connections, all indexes valid, stored payload/relational-key consistency and report counts. Record the applied revision and backup path.

The rollback strategy for this additive upgrade is to deploy the old compatible API and stop using the new endpoints. Leave added columns/indexes in place while investigating. Do not restore a full older dump over a live DB containing newer reports. A full recovery beyond the backup's timestamp requires WAL archiving/PITR, which this local Compose stack does not implement.

## Remaining requirements for a business production service

- Establish RPO/RTO, a PostgreSQL standby/failover plan, external WAL/archive storage and regular recovery drills. One Docker host remains a single point of failure.
- Runtime/migration roles are separated by this upgrade (`vahan_app` by default, owner `vahan` only in the short-lived migration container). Use a unique runtime role per database/deployment, enforce TLS between hosts and move local credentials to managed secrets when deploying beyond the local host.
- Send DB/container metrics to an external monitor. Alert on sustained pool exhaustion/503, lock wait, idle transactions, connection usage, replication lag, backup age and disk usage (warn around 70%, critical around 85%, tuned to the operational policy).
- Define retention for job events, screenshots and old CAPTCHA records before any archive/delete job is enabled. Move large immutable artifacts to object storage with checksum/authorization checks when growth warrants it. Avoid a blanket `VACUUM FULL` during service operation.
- Schedule normal VACUUM/ANALYZE and backup checks. Consider time partitions for audit/event history only after measuring query patterns and growth; partitioning existing history is not part of this additive upgrade.
- Migration execution takes a session advisory lock, and Compose waits for its successful completion before API startup. Pin/review dependency upgrades. Concurrent index builds can be rerun after interruption, but schema changes should not be launched by multiple API replicas simultaneously.

## Verification

Dedicated test databases exercise pool saturation/503 recovery, statement and row-lock timeout rollback, compact events, 2,500 image-bearing historical jobs, summary/detail paging and 20 simultaneous reads. Existing report/Excel tests verify full exports, formula-safe text, blanks/zero and saved-result invariants; existing retry/queue/schedule suites cover recovery and worker allocation. Browser fixtures verify bounded case paging and the existing account/monthly schedule UI. These checks do not constitute a live government-site crawl or high-availability proof.

Primary references: [PostgreSQL 17 concurrent indexes](https://www.postgresql.org/docs/17/sql-createindex.html), [PostgreSQL connection timeouts](https://www.postgresql.org/docs/17/runtime-config-client.html), [SQLAlchemy pool configuration](https://docs.sqlalchemy.org/en/20/core/pooling.html).

## Recorded recovery measurements (2026-10-08 UTC)

An actual 2.2 GB backup was restored into a separate PostgreSQL 17 container with 1 CPU/768 MB and no external network. The snapshot retained 46,363 jobs, 520,698 events, 75,580 stored files, 64,638 main report rows and all twelve monthly totals through the additive schema upgrade. All normalized job keys matched their original payloads and no index was invalid.

For a representative scope/year page of 100 rows, the plan without the new ordering index used a bitmap scan and sort (1,235.7 ms); with it, the plan used an index scan (2.373 ms). This is one query on the recovery clone, not a full crawler throughput measurement. Cold run-summary reads had a median near 508 ms, a cached read about 0.62 ms, and 20 coalesced reads about 406 ms. The 84-session response was 34,648 bytes and contained summary metadata only.

The built runtime image was then started against the clone with a DML-only role. It could neither create schema objects nor update Alembic's version table. Two authenticated HTTP bursts (20 annual-report requests and 20 run-summary requests) all returned 200; they completed in about 4.22 s and 2.48 s respectively in the resource-limited environment. The cache recorded two SQL loads and 38 coalesced callers. These timings are recovery-test measurements, not a production SLA.

Verification completed: 104 distinct backend tests, 1,600 unique cases allocated once across ten workers (160 each), account/monthly-schedule UI checks, case-pagination browser checks, and bounded/cancellable SQL-save retry tests. Full Excel exports retained blanks, zero values, names beginning with `=` and the expected row count.
