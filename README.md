# VAHAN Report Automation

MVP attended RPA dùng Web UI để chọn bộ lọc VAHAN, chuyển CAPTCHA hiện tại cho
người dùng nhập thủ công và điều khiển Chrome Extension tạo/tải báo cáo Excel.

```text
React Web UI  <── Socket.IO/REST ──>  FastAPI Backend  <── Socket.IO ──>  Chrome Extension  <──>  VAHAN
```

## Thành phần

| Thành phần | Thư mục | Công nghệ | Cổng mặc định |
|---|---|---|---|
| Backend | `apps/api-server` | Python, FastAPI, python-socketio | `8000` |
| Web UI | `apps/web-ui` | React, TypeScript, Vite | `5173` |
| Runner | `vahan-chrome-extension` | Chrome Extension Manifest V3 | Không có |

## Yêu cầu

- Windows 10/11 và PowerShell.
- Python 3.11 trở lên.
- Node.js 20.19+ hoặc 22.12+.
- Google Chrome 116 trở lên.
- Có thể truy cập `https://analytics.parivahan.gov.in`.
- Các cổng `8000` và `5173` chưa bị ứng dụng khác sử dụng.

Kiểm tra phiên bản:

```powershell
python --version
node --version
npm.cmd --version
```

## 1. Chuẩn bị Backend

Mở PowerShell thứ nhất:

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\apps\api-server

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

File `.env.example` ghi lại các giá trị mặc định:

```dotenv
VAHAN_API_HOST=127.0.0.1
VAHAN_API_PORT=8000
VAHAN_API_DEBUG=false
VAHAN_API_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
VAHAN_API_EXTENSION_IDS=ooplajjjjphdcaolokpaenmkjlbcmlhk
VAHAN_API_SOCKETIO_CORS_ORIGINS=*
VAHAN_API_RUNNER_TOKEN=change-me
VAHAN_API_RUNNER_DISCONNECT_GRACE_SECONDS=30
VAHAN_UI_HEALTH_LOG_DIR=runtime/ui-health-logs
VAHAN_CAPTCHA_IMAGE_DIR=runtime/images1
```

Backend hiện đọc biến môi trường của process và chưa tự load file `.env`. Nếu
muốn dùng giá trị khác mặc định, đặt biến trong cùng PowerShell trước khi chạy:

```powershell
$env:VAHAN_API_RUNNER_TOKEN = "your-secret-token"
$env:VAHAN_CAPTCHA_IMAGE_DIR = "runtime/images1"
```

Backend mặc định cho phép Web UI và extension unpacked hiện tại gọi REST API.
Nếu Chrome tạo extension ID khác, đặt `VAHAN_API_EXTENSION_IDS` bằng một hoặc
nhiều ID cách nhau bằng dấu phẩy rồi khởi động lại backend.

## 2. Chạy Backend

Trong PowerShell thứ nhất:

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\apps\api-server
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:application --host 127.0.0.1 --port 8000 --reload
```

Kiểm tra:

- Health: `http://127.0.0.1:8000/api/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

Health response hợp lệ:

```json
{"status":"ok"}
```

## 3. Build và cài Chrome Extension

Mở PowerShell thứ hai:

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\vahan-chrome-extension
npm.cmd install
npm.cmd run build
npm.cmd run check
```

Cài extension:

1. Mở `chrome://extensions`.
2. Bật **Developer mode**.
3. Chọn **Load unpacked**.
4. Chọn thư mục `vahan-chrome-extension`.
5. Chấp nhận quyền `storage`, `downloads` và truy cập trang VAHAN chính thức.

Không chọn thư mục `src`. Chrome phải load toàn bộ thư mục
`vahan-chrome-extension` chứa `manifest.json`.

### Cấu hình Runner

Bấm biểu tượng extension, mở phần kết nối backend và đặt:

```text
Server URL: http://127.0.0.1:8000
Runner name: VAHAN Chrome
Runner token: change-me
```

Token phải giống `VAHAN_API_RUNNER_TOKEN` của backend. Bấm **Lưu & Kết nối
lại**. Popup phải hiển thị trạng thái backend đã kết nối.

Mở VAHAN:

```text
https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en
```

Nếu VAHAN yêu cầu đăng nhập, cookie, disclaimer hoặc xác nhận ban đầu, hoàn
thành trực tiếp trên tab này trước.

## 4. Chạy Web UI

Mở PowerShell thứ ba:

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\apps\web-ui
npm.cmd install
npm.cmd run dev
```

Mở:

```text
http://127.0.0.1:5173
```

Web UI mặc định gọi backend tại `http://127.0.0.1:8000`. Có thể thay đổi bằng
file `apps/web-ui/.env`:

```dotenv
VITE_API_URL=http://127.0.0.1:8000
```

Sau khi sửa `.env`, phải khởi động lại Vite.

## 5. Chạy full flow

Trong Web UI, phần **Lịch kiểm tra giao diện** cho phép nhập số ngày giữa hai
lần kiểm tra. Khi bấm **Lưu lịch kiểm tra**, backend lưu cấu hình và báo ngay cho
extension đang kết nối để đặt lại `chrome.alarm`. Health-check định kỳ và nút
**Kiểm tra ngay** chỉ kiểm tra tab VAHAN chính thức đang mở đúng URL
`https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en`.
Extension không tự mở tab và không bị ảnh hưởng khi Web UI đang là tab active; nếu
chưa mở đúng trang hoặc URL thay đổi sau khi tải, lượt kiểm tra ghi `CHECK_ERROR`
kèm URL thực tế để Dev biết nguyên nhân.

Extension gửi kết quả PASS, DATA_CHANGED hoặc lỗi giao diện về backend; backend
ghi CSV để xem theo ngày và tải lại từ Web UI.

Phần **Báo cáo kiểm tra theo ngày** cho phép chọn ngày, xem diagnostic của từng
lần kiểm tra và tải các file `report-YYYY-MM-DD-to-YYYY-MM-DD*.csv` chứa ngày đó.
Backend lưu file tại `apps/api-server/runtime/ui-health-logs` mặc định, tự
rollover sau tối đa 10 ngày hoặc 512 KiB.

1. Xác nhận backend đang chạy.
2. Xác nhận popup extension báo đã kết nối backend.
3. Mở Web UI và kiểm tra có runner `VAHAN Chrome` khả dụng.
4. Bấm **Load State–RTO matrix**. Web UI đọc danh sách State và RTO trực tiếp từ
   runner, kiểm tra các lựa chọn filter cố định, rồi hiển thị số văn phòng theo
   từng bang. Nếu không đọc được một bang, ma trận sẽ không được lưu.
5. Bấm **Run all** để chạy lần lượt mọi cặp State–RTO. Có thể chọn một văn phòng
   rồi bấm **Run from here** hoặc **Run one**. Bộ lọc cố định gồm bốn Active/Archive
   type, Calendar Year, Two Wheeler và ba Sub-Category, hai Fuel `ELECTRIC(BOV)`
   và `PURE EV`, Y-Axis `Maker`, X-Axis `Month Wise`. Năm bắt đầu/kết thúc lấy
   từ năm hiện tại khi bắt đầu lượt chạy.
6. Với mỗi báo cáo, người dùng đọc CAPTCHA và nhập sáu ký tự trên Web UI.
   Extension tự Apply và tải Excel. Trường hợp không có dữ liệu được ghi là
   `No data`; lỗi được ghi riêng và có nút thử lại các báo cáo lỗi.
7. Excel được lưu tại backend theo cấu trúc
   `<session>/<State>/Maker Month Wise Data  of <RTO> , <State> (<Year>).xlsx`.
   Nếu chạy lại đúng văn phòng trong cùng session, tên file có thêm số thứ tự.
   Có thể tải từng file tại **Exported Reports**.

Luồng trạng thái chuẩn:

```text
ASSIGNED
  → OPENING_VAHAN
  → FILLING_FILTERS
  → WAITING_CAPTCHA
  → SUBMITTING
  → WAITING_RESULT
  → COMPLETED
```

CAPTCHA sai quay lại `WAITING_CAPTCHA`; tối đa ba lần liên tiếp. Lỗi xử lý
chuyển job sang `FAILED`. Người dùng có thể chuyển job sang `CANCELLED` bằng
nút hủy.

## 6. Chạy kiểm thử

### Backend

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\apps\api-server
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

### Extension

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\vahan-chrome-extension
npm.cmd run build
npm.cmd run check
```

### Web UI

```powershell
cd I:\MinhDuc\Coding\VinAI\VSF\Vahan-RPA-Team\vahan-rpa\apps\web-ui
npm.cmd run check
npm.cmd run build
```

## 7. Quy trình sau khi sửa code

### Sửa Extension

`src/background.js` là source của service worker. `background.js` ở thư mục
gốc là bundle được sinh ra.

Sau mỗi lần sửa extension:

```powershell
cd vahan-chrome-extension
npm.cmd run build
npm.cmd run check
```

Sau đó vào `chrome://extensions`, bấm **Reload** và refresh tab VAHAN. Nếu sửa
`manifest.json` hoặc thêm permission, Chrome có thể yêu cầu xác nhận lại quyền.

### Sửa Backend

Uvicorn `--reload` thường tự restart. Khi dependency hoặc biến môi trường thay
đổi, nên dừng bằng `Ctrl+C` rồi chạy lại hoàn toàn.

### Sửa Web UI

Vite hỗ trợ hot reload. Nếu sửa `.env`, dependency hoặc gặp state cũ, restart
Vite và refresh trình duyệt.

## 8. Troubleshooting

### WebSocket trả về 403

```text
Unexpected response code: 403
```

- Restart backend để nhận cấu hình Socket.IO CORS mới.
- Kiểm tra biến môi trường `VAHAN_API_SOCKETIO_CORS_ORIGINS` hoặc để mặc định `*`.
- Đảm bảo không có process Uvicorn cũ đang chiếm cổng 8000.

Kiểm tra process:

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
```

### Web UI báo chưa có extension khả dụng

- Mở popup extension và kiểm tra trạng thái kết nối.
- Server URL và token phải trùng backend.
- Reload extension tại `chrome://extensions`.
- Refresh Web UI.
- Runner ở trạng thái `BUSY` hoặc `RECONNECTING` sẽ tạm thời không khả dụng.

### Không tải được option động

- Tab VAHAN phải tải hoàn chỉnh.
- Kiểm tra VAHAN có hiển thị form report hay trang đăng nhập/disclaimer.
- Refresh tab VAHAN rồi chọn lại runner trên Web UI.
- Mở DevTools của tab VAHAN để xem lỗi content script.

### RTO không có dữ liệu

- Chọn đúng một State. VAHAN không trả RTO khi chọn nhiều State.
- Chờ State tải xong trước khi mở dropdown RTO.
- Không nhập label thủ công; chọn option do VAHAN trả về.

### Maker không có gợi ý

- Nhập ít nhất hai ký tự.
- Chờ trạng thái tìm kiếm hoàn tất.
- VAHAN phải còn phiên truy cập hợp lệ vì endpoint Maker dùng cookie của tab.

### CAPTCHA trên Web UI không đổi

- Đảm bảo extension và tab VAHAN đã được reload sau lần build mới nhất.
- Job phải đang ở `WAITING_CAPTCHA`.
- Refresh CAPTCHA trên VAHAN; Web UI sẽ xóa mã đang nhập khi nhận ảnh mới.

### Không tự tải Excel

- Kiểm tra `Tự động tải Excel` đã bật.
- Extension phải có permission `downloads`.
- Kiểm tra download có bị Chrome chặn hoặc chuyển sang `interrupted` không.
- Job sẽ `FAILED` nếu download không hoàn tất trong 60 giây.

### Extension báo Receiving end does not exist

Content script chưa có trong tab hiện tại. Reload extension, sau đó refresh tab
VAHAN. Background cũng sẽ thử reload tab và gửi lại message tự động.

## 9. Giới hạn của MVP

- Job và runner được lưu in-memory; restart backend sẽ mất trạng thái.
- Web UI chưa có đăng nhập/phân quyền.
- Socket.IO cho Web UI chưa có authentication.
- Log UI health được lưu ở backend và tải CSV từ Web UI; Excel được lưu theo
  thư mục session và State trên backend.
- Một runner chỉ xử lý một job tại một thời điểm.

## 10. Dừng hệ thống

Trong terminal Backend và Web UI, nhấn:

```text
Ctrl+C
```

Extension có thể giữ nguyên trong Chrome. Khi backend dừng, popup/widget sẽ báo
mất kết nối và tự reconnect khi backend chạy lại.
