# VAHAN RPA API — MVP Phase 1

Backend control plane for the React Web UI and VAHAN browser extension.

## Included

- FastAPI REST endpoints: health, runners, create/get/cancel jobs.
- UI health schedule REST endpoints: read/update the interval used by the extension.
- UI health log/report REST endpoints: receive extension checks, review by day and
  download backend CSV files.
- Socket.IO namespaces: `/ui` and `/runner`.
- In-memory runner registry and job repository.
- Runner registration, heartbeat and disconnect handling.
Runner/job/schedule state is intentionally lost when the process restarts.
UI health CSV reports are persisted on disk so they survive a backend restart.
PostgreSQL, Redis and Celery are outside Phase 1. The Web UI uses a configured
single-admin account and signed bearer tokens that do not expire automatically.

The UI health schedule is available at `GET/PUT /api/ui-health/schedule`.
`intervalDays` accepts an integer from 1 to 365, defaults to 3, and every update
is broadcast to connected runners as `ui-health:schedule-updated`.

`POST /api/ui-health/run-now` requests one immediate read-only check from a
connected runner and returns `202` with a `requestId`. It returns `409` when no
runner is connected. The runner checks the currently visible official VAHAN
Public Report tab at
`https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en`; it
never opens a tab, falls back to a background tab for the manual request, or
accepts a local/other URL. If the visible official tab is not open or its URL
changes after loading, the extension records a `CHECK_ERROR`. Scheduled alarm
checks may select another already-open official tab. The runner sends the result
through the existing log endpoint, and the backend broadcasts
`ui-health:log-received` to `/ui`.

Health logs are accepted at `POST /api/ui-health/logs`. Daily review is available
at `GET /api/ui-health/reports?date=YYYY-MM-DD`; a report file can be downloaded
from `GET /api/ui-health/reports/{fileName}/download`. Files are stored in
`runtime/ui-health-logs` by default (override with `VAHAN_UI_HEALTH_LOG_DIR`),
with the extension-compatible 25-column CSV schema. The backend starts a new
file after 10 calendar days or 512 KiB.

## Run locally

Set the dashboard credentials and a private signing secret in the ignored
`apps/api-server/.env` file or in the API process environment. Do not commit these
values or reuse the runner token as the UI token secret. The password must be at
least 12 characters and the signing secret at least 32 characters.

```powershell
cd apps/api-server
python -m pip install -e ".[dev]"
$env:VAHAN_API_RUNNER_TOKEN = "change-me"
$env:VAHAN_UI_AUTH_USERNAME = "admin"
$env:VAHAN_UI_AUTH_PASSWORD = "choose-a-password-with-12-or-more-characters"
$env:VAHAN_UI_AUTH_TOKEN_SECRET = (python -c "import secrets; print(secrets.token_hex(32))")
# ID extension xem tại chrome://extensions; mặc định đã có ID của workspace này.
$env:VAHAN_API_EXTENSION_IDS = "ooplajjjjphdcaolokpaenmkjlbcmlhk"
python -m uvicorn app.main:application --host 127.0.0.1 --port 8000 --reload
```

On macOS/Linux, configure and start the API in one terminal:

```bash
cd apps/api-server
export VAHAN_UI_AUTH_USERNAME="admin"
export VAHAN_UI_AUTH_PASSWORD="choose-a-password-with-12-or-more-characters"
export VAHAN_UI_AUTH_TOKEN_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
python3 -m uvicorn app.main:application --host 127.0.0.1 --port 8000 --reload
```

The API must inherit these values from that terminal.

`POST /api/auth/login` returns a signed access token without an automatic expiry.
The Web UI keeps it in browser local storage and sends it as `Authorization: Bearer ...`
for REST calls, authenticated downloads and the `/ui` Socket.IO namespace. Protected
API routes return `401` for a missing or invalid token. `/api/health` and
`/api/auth/status` remain available without login. The extension continues to use
its separate runner token for schedule reads, health-log uploads and Excel uploads;
an Excel upload must also match the runner assigned to that job.

OpenAPI is available at `http://127.0.0.1:8000/docs` and health at
`http://127.0.0.1:8000/api/health`.

## Test

```powershell
cd apps/api-server
python -m pytest
```
