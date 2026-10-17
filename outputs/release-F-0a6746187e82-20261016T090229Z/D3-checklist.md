# Checklist D3 — chờ chốt digest

- SHA: `0a6746187e820efd23e2e8e96f37eb3aa1efcba6`.
- Staging: `http://127.0.0.1:15187`; project `vahan-d3-0a67-20261016t090229`, 3 runner.
- Manifest SHA-256: `53692e7e05f587595628a37fa338ce1508f79847b07ff09d051feeb51591a3c4`.
- Images TAR SHA-256: `9d2a1004d2dad762cc087c705590692eb5aaee49ebc7f498c5ae267811a45cc4`.
- Thời gian ở từng dòng hiện là thời điểm ghi nhận NOT_RUN; startedAt/finishedAt để null vì chưa chạy. Xem JSON để có SHA, digest và lý do riêng từng mục.

| Mục | Nội dung | Trạng thái | Lý do |
| --- | --- | --- | --- |
| R1 | Health, restart API và giữ dữ liệu | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R2 | Login/logout, phân quyền và hết hạn phiên | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R3 | VAHAN options, filter và preview | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R4 | Lịch sử, xóa và khôi phục | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R5 | Export all và export có lọc | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R6 | UI Health trên VAHAN thật | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R7 | Once/Monthly, từ chối Daily | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R7b | Múi giờ Việt Nam/Ấn Độ | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R8 | VAHAN ≥100 case, ≥30 phút, ETA mỗi 60 giây | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R9 | Pause/resume, không mất hoặc chạy trùng case | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R9b | Worker động và giới hạn theo runner thực tế | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R10 | Tắt lịch, dừng và xóa | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R11 | Retry, NO_DATA và dừng runner | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R12 | Mất/phục hồi mạng, kiểm mất/trùng case | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R13 | Maker Update bị từ chối | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R14 | CAPTCHA/OCR không lộ dữ liệu nhạy cảm trong log | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R15 | API đã gỡ bị từ chối | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| R17 | Run History đúng quyền và kết quả | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| S3 | Giới hạn đăng nhập | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| S5 | Socket.IO origin | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| S6 | Security headers | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| S7 | API docs và SPA shell | NOT_RUN | Chờ review/chốt gói và digest cuối. |
| S8 | Runner identity theo scope đã duyệt | NOT_RUN | Deferred theo D-02. |
| S10 | Container hardening theo scope đã duyệt | NOT_RUN | Deferred theo D-02. |
| O1 | Health probe ngoài stack | NOT_RUN | Chờ review/chốt gói và digest cuối. |

[Ledger có timestamp và danh tính gói ở từng dòng](D3-checklist.json).

R8 giữ ngưỡng đã duyệt: ≥100 case, ≥30 phút, mẫu mỗi 60 giây; trung vị |e| ≤25% ở 50–75%, ≤15% ở 75–100%. Ghi rõ downtime VAHAN và tính vào sai số; không chèn các fault injection R9–R12 vào lượt R8. Tất cả các case thu thập phải qua VAHAN thật.

Sau khi người dùng chốt gói, kiểm lại danh tính bằng lệnh dưới đây. Lệnh chỉ đọc và không chạy D3:

```powershell
py -3 "C:\Users\huyvv12\Desktop\vahan-automation\outputs\release-F-0a6746187e82-20261016T090229Z\d3-package-gate.py" `
  --expected-sha 0a6746187e820efd23e2e8e96f37eb3aa1efcba6 `
  --expected-manifest-digest 53692e7e05f587595628a37fa338ce1508f79847b07ff09d051feeb51591a3c4 `
  --expected-images-digest 9d2a1004d2dad762cc087c705590692eb5aaee49ebc7f498c5ae267811a45cc4
```

Nếu gate không PASS, dừng trước D3. Khi D3 đã bắt đầu, không sửa source hoặc build lại artifact; lỗi cần đổi source/artifact phải dừng và báo người dùng.
