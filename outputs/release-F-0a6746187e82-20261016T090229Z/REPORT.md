# Release F cuối — kiểm chứng mới và staging trước D3

- Candidate: `origin/release/pre-go-live`, SHA `0a6746187e820efd23e2e8e96f37eb3aa1efcba6`; version/tag `1.0.0`.
- Local và remote khớp SHA; worktree build sạch `C:\Users\huyvv12\AppData\Local\Temp\vahan-release-F-clean-20261016T090229Z`.
- Báo cáo UTC: `2026-10-16T09:31:17.757552+00:00`.
- Kết luận: **PASS phần chuẩn bị trước D3; sẵn sàng để người dùng review/chốt digest cuối. D3 vẫn NOT_RUN.**
- Mọi PASS của candidate này được kiểm mới trên đúng source/artifact. Không mang kết quả PASS của candidate trước sang.

| Mục trước D3 | Kết quả | Thời gian UTC | Evidence |
| --- | --- | --- | --- |
| CI đúng SHA | PASS — 6/6 | 2026-10-16T09:09:03.734935+00:00 | [GitHub run](https://github.com/Muteen-Felix/vahan-automation/actions/runs/38877597636), [raw check-runs](ci-checks.json) |
| Build từ worktree sạch | PASS | 2026-10-16T09:09:07.113777+00:00 → 2026-10-16T09:09:55.090338+00:00 | [build log](package-build.log), [worktree](worktree-clean.json), [HEAD](final-source-head.log), [remote](final-remote-head.log) |
| Manifest, revision/version, checksum | PASS | 2026-10-16T09:10:03.414153+00:00 | [package validation](package-validation.json), [loaded images](fresh-loaded-images.json), [source integrity](fresh-extracted-source-integrity.json) |
| Cài offline trên daemon trống | PASS — đủ 4 image | 2026-10-16T09:11:24.896269+00:00 | [empty store](clean-engine.json), [load](fresh-docker-load.log), [runtime image IDs](fresh-installed-image-identity.json) |
| Smoke cài mới và DB role | PASS — 14/14, 0 fail/skip | 2026-10-16T09:10:52Z | [smoke](fresh-smoke.json), [migration](fresh-initial-migration.log), [schema](fresh-schema.log) |
| Migration cài mới lần hai | PASS | 2026-10-16T09:10:54.549433+00:00 | [log](fresh-migration-rerun.log) |
| compose stop → launcher | PASS — script nguyên bản từ gói | 2026-10-16T09:11:23.891033+00:00 | [restart](fresh-restart.log), [data/session persistence](fresh-persistence.json) |
| Guard sau khi mở lại DB | PASS — vẫn chặn lịch hoạt động | 2026-10-16T09:11:41.260573+00:00 | [structured result](fresh-safety-result.json), [active-work rejection](fresh-active-work-guard.log), [read-only rejection](fresh-readonly-when-stopped.log) |
| Chromium sandbox/Tesseract | PASS | 2026-10-16T09:10:55.378136+00:00 | [runtime](fresh-chromium-tesseract.log), [versions/dependencies](fresh-build-fingerprint.json) |
| T45b: bản cũ có dữ liệu → F cuối | PASS — 0012 → 0016 | 2026-10-16T09:13:56.958136+00:00 | [result](t45b-result.json), [old API data](t45b-old-application-data.json), [migration](t45b-upgrade-migration.log) |
| T45b: backup và restore | PASS | Xem timestamp từng lệnh | [backup verification](t45b-backup-verification.json), [archive list](t45b-backup-list.log), [restored data](t45b-restored-data.log) |
| T45b: bảo toàn dữ liệu | PASS — 10 bảng khớp số dòng/nội dung | Xem timestamp từng lệnh | [before](t45b-data-before.log), [after](t45b-data-after.log), [after second migration](t45b-data-after-second-migration.log) |
| T45b: Once/Monthly, Daily và lịch sử | PASS — giữ Once/Monthly, xóa đúng 1 Daily có audit | Xem timestamp từng lệnh | [schedule before](t45b-schedules-before.log), [after](t45b-schedules-after.log), [audit](t45b-daily-removal-audit.log), [reports/history](t45b-reports-history-api.json) |
| T45b: idempotent và cấu hình | PASS | Xem timestamp từng lệnh | [rerun](t45b-migration-idempotent.log), [audit unchanged](t45b-audit-after-second-migration.log), [old keys preserved](t45b-config-preservation.json), [credential failure safety](t45b-negative-credential-safety.json) |
| Smoke sau nâng cấp | PASS — 14/14, 0 fail/skip | 2026-10-16T09:13:52Z | [smoke](t45b-smoke.json), [installed images](t45b-installed-image-identity.json) |
| Staging riêng từ chính gói cuối | PASS — 3 runner healthy | 2026-10-16T09:18:58.708323+00:00 | [staging result](staging-result.json), [image identity](staging-image-identity.json), [clean data](staging-final-clean-data.log) |
| Smoke staging | PASS — 14/14, 0 fail/skip | 2026-10-16T09:18:56Z | [smoke](staging-smoke.json) |
| Kết nối VAHAN thật trước D3 | PASS — 3/3 HTTPS navigation, TLS bật | 2026-10-16T09:19:10.049028+00:00 | [navigation only](staging-network-readiness.json); không phải CAPTCHA/report/UI Health/D3 |
| Gate SHA/digest/stack | PASS với danh tính gói vừa tạo | Xem timestamp lệnh | [read-only gate](final-staging-identity-gate.log); chưa phải xác nhận digest của người dùng |
| D3 R1–R15/R17, S3/S5/S6/S7/S8/S10/O1 | NOT_RUN | Chưa có startedAt/finishedAt | [checklist](D3-checklist.md), [ledger từng mục](D3-checklist.json) |

## Gói cuối để chốt

[Thư mục package](package/) — source ZIP, images TAR, manifest, SHA256SUMS. **Không sửa hoặc build lại gói sau các kiểm chứng này.**

| File | SHA-256 |
| --- | --- |
| [vahan-0a6746187e82-images.tar](package/vahan-0a6746187e82-images.tar) | `9d2a1004d2dad762cc087c705590692eb5aaee49ebc7f498c5ae267811a45cc4` |
| [vahan-0a6746187e82-manifest.json](package/vahan-0a6746187e82-manifest.json) | `53692e7e05f587595628a37fa338ce1508f79847b07ff09d051feeb51591a3c4` |
| [vahan-0a6746187e82-source.zip](package/vahan-0a6746187e82-source.zip) | `df6d8ce613c75be875a737894963cfac3582b17738b5a0ba44f1540ca8fc53ac` |
| [SHA256SUMS](package/SHA256SUMS) | `11a841ee1fd08d50547e589cc733a7713b98725d8b013e190df24fa8f67b33d6` |

[Danh tính gói và trạng thái chờ duyệt](candidate-lock.json). Chưa có digest nào được tự coi là người dùng đã chốt.

## Staging đã chuẩn bị

- Web: [http://127.0.0.1:15187](http://127.0.0.1:15187); API: `http://127.0.0.1:18087`.
- Project: `vahan-d3-0a67-20261016t090229`, 3 runner; chỉ stack này dành cho D3.
- Installed root: `C:\Users\huyvv12\AppData\Local\Temp\vahan-d3-0a67-staging-p0kyko6t`; cấu hình riêng được bảo vệ, không đính kèm credential.
- Dữ liệu nghiệp vụ sạch: 0 báo cáo/job/session/queue/profile/file/lịch sau smoke và navigation; chỉ có bootstrap admin và tài khoản smoke đã vô hiệu hóa.
- Snapshot cuối ghi đúng `runner.replicas = 3`: [staging config](staging-config-snapshot.json). [Fresh config](fresh-config-snapshot.json) và [T45b config](t45b-config-snapshot.json) được lưu riêng theo môi trường.
- Các daemon thử cài mới/nâng cấp và service con đã dừng; volume và backup riêng được giữ để review. Staging tiếp tục chạy để chờ D3.

## Phạm vi và các vấn đề đã xử lý

- Lỗi restart gốc đã sửa trong source và kiểm lại từ script **không chỉnh tay** giải nén từ gói cuối. Không dùng workaround mở PostgreSQL riêng trong ca stop → launcher đạt.
- Lỗi mất reference PostgreSQL khi save/load trên store trống đã sửa. Gói cuối nạp được chính reference pin digest, không nhờ image có sẵn.
- Hai test browser phụ thuộc thứ tự/timing đã sửa theo hợp đồng: Maker so sánh đúng bộ giá trị, thử hai thứ tự phản hồi; reader chỉ nhận body sau khi bắt đầu đọc. Không bỏ assertion về giá trị thiếu/thừa/trùng hoặc kết quả data/no-data.
- Bản nền T45b là B `2bc878e…`, có dữ liệu kiểm thử lưu thật trong PostgreSQL từ trước khi build gói cuối: 3 report rows, job/session/queue, stored file, profile và Once/Monthly/Daily. **Nội dung synthetic, không phải kết quả VAHAN thật**; [asset provenance](baseline-resource-provenance.json). Tất cả phép kiểm nâng cấp cho gói cuối được chạy mới.
- Cài sạch dùng daemon/store/container/volume ban đầu rỗng trên cùng Windows host, không phải VM/máy vật lý riêng. Đã kiểm đường offline độc lập với Docker store cũ và tạo staging riêng đúng lựa chọn của người dùng.
- Mẫu RAM ngay sau Docker restart chưa đủ; staging chưa được tạo lúc đó. [Recheck](staging-host-headroom-recheck.json) xác nhận đủ headroom trước khi tạo 3 runner. Đây là chờ môi trường ổn định, không thay source/artifact.
- Ca DB runtime password ngắn bị từ chối trên DB restore riêng; 10 bảng nghiệp vụ không đổi. Schema migration diễn ra trước bước kiểm credential; chi tiết được giữ trong [negative case](t45b-negative-credential-safety.json).
- S8/S10 giữ Deferred theo D-02 trong scope release đã có; không tính PASS.

## Điều kiện còn lại trước D3

Người dùng review và chốt **SHA + digest gói cuối** ở trên, rồi ra lệnh bắt đầu D3 trên staging này. Trước khi bắt đầu, chạy lại identity gate với đúng các giá trị người dùng đã chốt. Nếu lệch, dừng; trong D3 không sửa source/build lại gói.

## Lịch sử candidate bị loại

- `6a0d197…`: CI xanh nhưng fresh offline phát hiện mất reference PostgreSQL; không dùng gói đó. [Rejection](../release-F-6a0d1975d6e9-20261016T083407Z/REJECTED.md).
- `5680ab5…`: CI bị chặn bởi test Maker phụ thuộc thứ tự; chưa build gói. [Rejection](../release-F-5680ab506697-20261016T084505Z/REJECTED.md).
- `965a9ec…`: CI bị chặn bởi test streaming body phụ thuộc 300 ms; chưa build gói. [Rejection](../release-F-965a9eca42ef-20261016T085232Z/REJECTED.md).
- Chỉ gói `0a67461…` trong thư mục này là candidate cuối được đề nghị review. D3 chưa chạy trên bất kỳ candidate nào trong lượt chuẩn bị này.

Evidence có SHA-256 riêng trong `evidence-SHA256SUMS`. Private dump/env và giá trị/hash credential không nằm trong evidence/package.
