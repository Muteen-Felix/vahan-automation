# VAHAN RPA Web UI — MVP Phase 3

React control center for creating VAHAN filter jobs, viewing extension runners,
tracking job status and entering CAPTCHA challenges forwarded by the backend.

The **Lịch kiểm tra giao diện** section lets an operator set the UI health-check
interval from 1 to 365 days. The value is saved through the backend and sent to
connected extensions, which reset their alarm and send health results back to the
backend. The connected extension checks the currently visible official VAHAN Public
Report tab at `https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en`;
the manual **Kiểm tra ngay** request never falls back to a background tab, opens a
tab, or probes a different URL. If the visible tab is missing or redirects to
another URL, the check is recorded as `CHECK_ERROR`. Scheduled alarm checks may
use an already-open official tab because they run without a user click.
**Báo cáo kiểm tra theo ngày** reads the backend CSV log, shows detailed
diagnostics for the selected day and provides a download link for each matching
CSV file. The small **Kiểm tra ngay** button sends an immediate read-only check
request to a connected extension runner; the runner uses the visible official tab and
pushes the result back to the report panel automatically. If no official tab is
open, the request is recorded as a check error so it can be fixed explicitly.

## Run

Start the backend first, then:

```powershell
cd apps/web-ui
npm.cmd install
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. The backend URL defaults to
`http://127.0.0.1:8000` and can be changed with `VITE_API_URL`.

The main screen shows the admin login configured in the API. Set
`VAHAN_UI_AUTH_USERNAME`, `VAHAN_UI_AUTH_PASSWORD` (at least 12 characters), and
`VAHAN_UI_AUTH_TOKEN_SECRET` (at least 32 characters) in the API process before
starting it. Access tokens do not expire automatically and remain in browser local
storage across tab and browser restarts. Signing out or changing the server signing
secret returns the browser to the login screen.
