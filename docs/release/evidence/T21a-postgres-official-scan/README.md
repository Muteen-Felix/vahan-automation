# T21a — quét image PostgreSQL chính thức (13/10/2026)

- Ref: `docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826` (linux/amd64)
- Công cụ: `scripts/scan_container_images.py` (Trivy 0.66.0 pin digest), policy T21: fail HIGH/CRITICAL **có bản vá**.
- Kết quả (`summary.json`): high 89, critical 4, **fixableHighCritical 25** → **vượt ngưỡng**.
- Cả 25 finding có bản vá nằm ở một file: `usr/local/bin/gosu` (Go stdlib v1.24.6; sửa ở 1.24.13 / 1.25.7 / 1.26.0). Không có finding có bản vá ở gói Debian hay PostgreSQL.
- Bản tự build cũ (đã bỏ theo D-33) đạt 65 high / 3 critical / **0 fixable** (`docs/evidence/round1-5/scan-summary.json`) vì dựng lại `gosu` bằng Go đã vá.

**Trạng thái: DEVIATION đã được Felix quyết định A ngày 13/10/2026 (PLAN §11 D-36, KI-25):** chấp nhận ngoại lệ hẹp cho `gosu`; không quay lại image tự build, không hạ ngưỡng chung. Scanner phân loại 25 finding này là `acceptedFixable` (vẫn nằm trong báo cáo); ngoại lệ chỉ có hiệu lực với digest `sha256:3645570c…3826`.

Tệp: `summary.json` (kết quả policy), `fixable-findings.json` (25 finding có bản vá), `postgres.vulnerabilities.json.gz` và
`postgres.cdx.json.gz` (báo cáo Trivy đầy đủ và SBOM CycloneDX, nén gzip để repo không phình; `gunzip` để đọc).
Tái tạo: `python scripts/scan_container_images.py --output-dir <thư mục>` (cần Docker + mạng tải Trivy DB).
