# Round 4 security and packaging verification

Verified separately on the `release/pre-go-live` and `ocr` branches on 2026-10-12, using disposable Docker projects/databases. The results below predate the branch merge.
The running application stack was not redeployed.

| Check | Result |
| --- | --- |
| Release API core tests | 61 passed |
| Runner syntax and OCR rate-limit test | Passed |
| OCR branch API tests plus production/OCR/CAPTCHA verification | 133 passed, 8 subtests passed |
| Browser runner: all package test scripts | Passed |
| Dashboard type check, build and platform browser suite | Passed |
| Production container security integration | Passed |
| Restricted API role on fresh schema and upgrade from 0012 to head | Passed |
| Host requests to direct and Nginx-proxied `/api/ready` | HTTP 200 |
| Production `/docs`, `/redoc`, `/openapi.json` | HTTP 404 |
| HTTP and Socket.IO origin allowlists, CSP/security headers | Passed |
| Nginx login throttling | HTTP 429 after burst exhaustion |

At the time of Round 4 validation, automatic CAPTCHA OCR reserved each start in PostgreSQL under a shared row
lock. The rolling limit is 20 starts per ten minutes across all runners/API
processes. The window survives API reconnection; a repeated challenge cannot
consume a second slot. Exhaustion fails the current job with `OCR_RATE_LIMIT`,
releases its runner and displays the reason on the dashboard. A concurrent
submission cannot be overwritten by quota failure. Raw OCR text is no longer
logged by the production runner. The OCR start quota was removed after this
validation; these quota results do not describe the merged application's current behavior.

Every Docker base image is pinned by digest. The PostgreSQL base is the
official PostgreSQL 17 image; its data layout remains unchanged. Python runtime
and development dependencies have transitive version/hash locks, including the
POSIX-only uvloop dependency. Builds generate SBOM/provenance attestations.

## Vulnerability scan

Trivy 0.66.0, pinned by digest, scanned all four built runtime images.
CycloneDX SBOMs and full vulnerability JSON reports are retained locally under
`diagnostics/round4-security/` and uploaded as CI artifacts for 30 days.

| Image | HIGH | CRITICAL | HIGH/CRITICAL with vendor fix |
| --- | ---: | ---: | ---: |
| PostgreSQL | 65 | 3 | 0 |
| API | 55 | 2 | 0 |
| Web | 0 | 0 | 0 |
| Runner | 107 | 4 | 0 |

The scan is **not clean**: 236 HIGH/CRITICAL findings remain without vendor
fixes in the scan database. They are retained in full, including affected
packages/CVEs. The CI policy rejects HIGH/CRITICAL findings with an available
vendor fix and any scan error. It scans every image and writes every report
before failing, so findings from later images are not lost.

Reproduce:

```sh
python scripts/test_container_security.py
python scripts/scan_container_images.py --output-dir diagnostics/round4-security
```

Behind an enterprise TLS proxy, the scanner supports an explicit local trust
root through `--ca-cert PATH`; the certificate is not included in this commit.

`.github/workflows/platform.yml` runs on pushes to `main`, `ocr`, `release`
and `release/**`, all pull requests, and manual dispatch. It includes the new
OCR, production boundary, restricted-role lifecycle and scan/SBOM checks.
This report records local evidence; GitHub workflow status is separate.

## CI completion audit

On the release branch, the expanded database CI command set covered the release schema, restricted-role
startup, the 1,600-case queue check and populated legacy/shared/workbook migration
comparisons. Worker lifecycle checks use explicit disposable administrator
credentials and the job identifier supported by the release API. Obsolete tests
were corrected for the removed schedule year input, ignored legacy case cap,
member navigation and normalized migration filters.

On the OCR branch, the expanded database CI command set was exercised locally: 276 database-backed
tests, plus restricted-role startup, the 1,600-case queue check and populated
legacy/shared/workbook migration comparisons. Every command passed after
correcting obsolete test expectations. The year-boundary test accepts next year
and rejects the following year; schedule control tests use the supported monthly
repeat; lifecycle tests supply explicit disposable administrator credentials.
The worker-capacity and UI-drift diagnostic unit checks are also included.

CI installs Docker Compose 5.6.0 explicitly and enables the containerd image
store so SBOM/provenance builds do not depend on the GitHub runner's older
Compose installation. At the time of Round 4 validation, the release branch
ported the security changes and adapted fixtures without the other `ocr` features.

The scanner mounts the active Docker context's socket, including the isolated
daemon created by CI. Unit checks verify that fixable findings fail the gate
after all four images have reports and that unfixed findings remain visible.
