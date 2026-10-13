# R8 — đo sai số ETA (T15, D-28)

- row: R8
- sha: 8865cecb0d017a1ec29a6b29fa9fced5b18de3bc

**Loại bằng chứng:** E-local, **workload SYNTHETIC** (3 worker giao thức thật qua HTTP/Socket.IO/SQL, mỗi case 54 s, case giả `NO_RECORD`; không phải trình duyệt/VAHAN). Đây là phép đo hành vi estimator + API + UI-helper, **không thay D3 R8 trên VAHAN thật** (Not verified).

## Điều kiện lượt đo (T15(1)) — đủ điều kiện
| Điều kiện | Giá trị |
| --- | --- |
| Số case / attempt | 100 / 100 (không retry) |
| Thời lượng | 2186 s (≥ 1800 s) |
| Worker song song tối đa | 3 |
| Gián đoạn (pause, mất mạng, đổi worker, restart tiến trình đo, heartbeat lỗi) | **0** (`interruptions: []`, harness không dùng `--resume`) |
| Chu kỳ lấy mẫu | 60 s (trung vị thực tế 60.1 s), 37 snapshot, 1 mẫu ETA `null` (đầu run, chưa đủ mẫu) |
| Định nghĩa | `ETA(t)` = `remainingMs` hiển thị; `e = (ETA − thực còn lại) / thực còn lại`; bỏ mẫu thực còn lại ≤ 0 |

## Kết quả theo cửa sổ tiến độ (abs(e))
| Cửa sổ | Số mẫu | Trung vị | Lớn nhất | Ngưỡng D-28 (trung vị) |
| --- | --- | --- | --- | --- |
| 25-50% | 9 | 5.81% | 10.68% | không ngưỡng |
| 50-75% | 9 | 9.78% | 22.54% | ≤ 25% |
| 75-100% | 9 | 7.97% | 33.07% | ≤ 15% |

(Cửa sổ 0–25% bị loại khỏi D-28: 9 mẫu, trung vị 10.03%, lớn nhất 184.18% do chưa đủ mẫu.)

**Kết luận:** trung vị abs(e) ở 50–75% = 9.78% (≤ 25%) và ở 75–100% = 7.97% (≤ 15%) → **đạt D-28 trên workload synthetic**. Giá trị lớn nhất (không có ngưỡng) được báo ở bảng trên.

## Nguyên nhân của lần đo trước (43,50% / 35,17%)
`outputs/audit-round3/eta-measurement.json` không đủ điều kiện: tiến trình đo bị restart giữa chừng (done=49 → 50 cách nhau ~600 s), harness bản cũ gán `PASS` vô điều kiện. Replay offline chuỗi đó qua estimator tại thời điểm đó khớp 43,5/35,2%; loại đoạn dừng thì còn ~3–9%. Estimator (`batch-timing.ts`, commit `5ad6686`) **không bị sửa** trong đợt này; số liệu trên là của code ở `8865cecb0d01`. Lượt thử đầu tiên của đợt này (dừng ở 93/100 do `Runner is not registered` khi chạy song song test khác) bị bỏ, không dùng.

## Giới hạn
- Synthetic; số mẫu mỗi cửa sổ nhỏ (9) do chu kỳ 60 s theo D-28.
- Cửa sổ 75–100% max 33.1%: ETA gần cuối nhạy với việc case cuối đang chạy dở.
- D3 R8 trên VAHAN thật chưa chạy → RG1 chưa đạt phần này.
- Dữ liệu thô: `R8-eta/eta-measurement.json`, `eta-observations.jsonl`, `eta-run.log`.
