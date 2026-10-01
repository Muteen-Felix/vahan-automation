# Test UI health trên trang VAHAN chính thức

Tài liệu này kiểm tra toàn bộ đường đi `trang VAHAN → extension → backend → Web UI`:
extension có chọn đúng tab hay không, DOM/data có thay đổi hay không, nhiều lỗi có
được giữ đủ trong `reports[]` hay không và lịch sử/CSV có hiển thị đúng hay không.

File chạy trực tiếp trên tab thật là [`official-devtools-test.js`](./official-devtools-test.js).
Các case trong file chỉ sửa DOM tạm thời; không nhập CAPTCHA, không bấm Apply,
không submit form và không gọi API sản xuất. Case không có trong file được đánh dấu
`Elements`, `Flow`, `API`, `Web UI` hoặc `Auto` và không được gọi bằng
`VahanOfficialDevTools.run()`.

## 1. Quy tắc an toàn và tiêu chí chung

Chỉ chạy trên URL chính thức đã được ủy quyền:

```text
https://analytics.parivahan.gov.in/analytics/vahanpublicreport
```

Query string như `?lang=en` được phép. `http`, `localhost`, port khác, host khác,
path khác, trang đăng nhập hoặc iframe khác đều là case URL không hợp lệ.

Mỗi case là một lượt độc lập:

1. Mở hoặc reload trang VAHAN chính thức và chờ DOM tải xong.
2. Kiểm tra `snapshot()` trước khi sửa.
3. Chạy đúng một mutation/case.
4. Trong Web UI bấm **Kiểm tra ngay** đúng một lần.
5. Lưu `checkId`, `logId`, `status`, `errorCount`, `reports[]`, URL, thời gian,
   selector và diagnostic.
6. Reload trang hoặc chạy `restore()` trước case tiếp theo.

Không bấm **Kiểm tra ngay** giữa các mutation của một case nhiều lỗi. Mục tiêu là
đưa nhiều thay đổi vào cùng một DOM rồi tạo đúng một health-check.

Các bất biến bắt buộc:

```text
status=UI_DRIFT  => errorCount === reports.length
UI_DRIFT         => reports.length === uiDrifts.length
UI_DRIFT         => mỗi reports[i] có diagnostic riêng; không gộp thành một lỗi
UI_DRIFT         => không được chỉ lưu report đầu tiên
PASS             => errorCount=0 và reports=[]
DATA_CHANGED     => diagnostics.changes[] chứa đủ control thay đổi
CHECK_ERROR      => phải có nguyên nhân và URL/trạng thái runner liên quan
```

`report` hoặc `uiDrift` là trường lỗi đầu tiên để tương thích ngược. Luồng mới
phải dùng `reports[]` hoặc `uiDrifts[]` làm danh sách đầy đủ. Một dòng Web UI có
`N lỗi` phải mở ra được đủ `N` diagnostic con; không được nhân đôi cùng một lỗi
chỉ vì retry hoặc refresh.

Timestamp có hậu tố `Z` là UTC. Ví dụ `2026-01-12T03:00:00.000Z` là `10:00:00`
ở Việt Nam (UTC+7). Khi đối chiếu ảnh chụp màn hình, luôn nhìn cả nhãn `GMT+7`.

## 2. Chuẩn bị và chạy harness DevTools

1. Khởi động backend tại `http://127.0.0.1:8000` và Web UI tại
   `http://127.0.0.1:5173/#configure`.
2. Mở Chrome, vào trang VAHAN chính thức và chờ các control tải xong.
3. Mở DevTools → **Console**, dán toàn bộ nội dung
   `official-devtools-test.js`, rồi chạy một lần.
4. Kiểm tra harness đã được nạp:

   ```js
   typeof VahanOfficialDevTools
   // Expected: "object"
   ```

5. Kiểm tra contract sạch và danh sách case:

   ```js
   VahanOfficialDevTools.snapshot()
   console.table(VahanOfficialDevTools.list())
   ```

6. Chạy baseline trước khi phá DOM:

   ```js
   VahanOfficialDevTools.run("baseline")
   ```

7. Trên Web UI bấm **Kiểm tra ngay**. Baseline phải tạo `PASS`.
8. Chạy case cần kiểm tra, ví dụ:

   ```js
   VahanOfficialDevTools.run("two-drift", { confirm: true })
   ```

9. Bấm **Kiểm tra ngay** một lần nữa và kiểm tra cả dòng lịch sử lẫn diagnostic.

Nếu `typeof VahanOfficialDevTools` trả về `"undefined"`, script chưa được nạp
đầy đủ vào page context. Không chạy riêng câu `VahanOfficialDevTools.run(...)`.
Hãy reload tab, dán lại toàn bộ file hoặc dùng **Sources → Snippets** như ở mục
6. `official-devtools-test.js` không tự được tạo thành global chỉ vì extension
đã cài.

## 3. Các case có sẵn trong `official-devtools-test.js`

Đây là danh sách case có thể gọi trực tiếp bằng `VahanOfficialDevTools.run()`.
Case có `confirm: true` sẽ hỏi xác nhận vì mutation làm hỏng DOM của tab hiện tại.

### 3.1. Control bắt buộc và selector

| Case | Mutation | Kỳ vọng |
| --- | --- | --- |
| `baseline` | Không mutation | `PASS`, `errorCount=0`, `reports=[]` |
| `missing-form` | Xóa form VAHAN | Một hoặc nhiều `UI_DRIFT_REQUIRED_CONTROL` tùy DOM thực tế |
| `missing-category` | Xóa `#vehicleCategoryGroup` | `UI_DRIFT_REQUIRED_CONTROL`, count=0 |
| `missing-fuel` | Xóa `#vehicleFuel` | `UI_DRIFT_REQUIRED_CONTROL`, count=0 |
| `missing-yaxis` | Xóa `#yAxis` | `UI_DRIFT_REQUIRED_CONTROL`, count=0 |
| `missing-xaxis` | Xóa `#xAxis` | `UI_DRIFT_REQUIRED_CONTROL`, count=0 |
| `missing-captcha` | Xóa `#externalCaptcha` | `UI_DRIFT_REQUIRED_CONTROL`, count=0 |
| `missing-apply` | Xóa `#applyTrigger` | `UI_DRIFT_REQUIRED_CONTROL`, count=0 |
| `renamed-category` | Đổi ID Category | Selector cũ count=0, `UI_DRIFT_REQUIRED_CONTROL` |
| `renamed-fuel` | Đổi ID Fuel | Selector cũ count=0, `UI_DRIFT_REQUIRED_CONTROL` |

Lệnh:

```js
VahanOfficialDevTools.run("missing-form", { confirm: true })
VahanOfficialDevTools.run("missing-category", { confirm: true })
VahanOfficialDevTools.run("missing-fuel", { confirm: true })
VahanOfficialDevTools.run("missing-yaxis", { confirm: true })
VahanOfficialDevTools.run("missing-xaxis", { confirm: true })
VahanOfficialDevTools.run("missing-captcha", { confirm: true })
VahanOfficialDevTools.run("missing-apply", { confirm: true })
VahanOfficialDevTools.run("renamed-category", { confirm: true })
VahanOfficialDevTools.run("renamed-fuel", { confirm: true })
```

### 3.2. Trùng control và sai kiểu control

| Case | Mutation | Kỳ vọng |
| --- | --- | --- |
| `duplicate-category` | Nhân bản Category | `UI_DRIFT_REQUIRED_CONTROL`, count=2 |
| `duplicate-fuel` | Nhân bản Fuel | `UI_DRIFT_REQUIRED_CONTROL`, count=2 |
| `duplicate-yaxis` | Nhân bản Y-Axis | `UI_DRIFT_REQUIRED_CONTROL`, count=2 |
| `duplicate-xaxis` | Nhân bản X-Axis | `UI_DRIFT_REQUIRED_CONTROL`, count=2 |
| `wrong-category-type` | Bỏ `multiple` của Category | `UI_DRIFT_CONTROL_TYPE` |
| `wrong-fuel-type` | Bỏ `multiple` của Fuel | `UI_DRIFT_CONTROL_TYPE` |

```js
VahanOfficialDevTools.run("duplicate-category", { confirm: true })
VahanOfficialDevTools.run("duplicate-fuel", { confirm: true })
VahanOfficialDevTools.run("duplicate-yaxis", { confirm: true })
VahanOfficialDevTools.run("duplicate-xaxis", { confirm: true })
VahanOfficialDevTools.run("wrong-category-type", { confirm: true })
VahanOfficialDevTools.run("wrong-fuel-type", { confirm: true })
```

### 3.3. Option và dữ liệu bắt buộc

| Case | Mutation | Kỳ vọng |
| --- | --- | --- |
| `missing-category-option` | Xóa option `Two Wheeler` | `UI_DRIFT_REQUIRED_OPTION` |
| `missing-yaxis-option` | Xóa option `Fuel` | `UI_DRIFT_REQUIRED_OPTION` |
| `empty-fuel-options` | Xóa toàn bộ option Fuel | `UI_DRIFT_EMPTY_OPTIONS` |
| `data-changed-category` | Đổi dataset Category sau baseline | `DATA_CHANGED`, change Category |
| `data-changed-fuel` | Đổi dataset Fuel sau baseline | `DATA_CHANGED`, change Fuel |
| `data-changed-yaxis` | Đổi dataset Y-Axis sau baseline | `DATA_CHANGED`, change Y-Axis |
| `data-changed-xaxis` | Đổi dataset X-Axis sau baseline | `DATA_CHANGED`, change X-Axis |
| `data-changed-category-and-fuel` | Đổi hai dataset cùng lúc | Một kết quả `DATA_CHANGED`, `changes[]` có 2 control |

```js
VahanOfficialDevTools.run("missing-category-option", { confirm: true })
VahanOfficialDevTools.run("missing-yaxis-option", { confirm: true })
VahanOfficialDevTools.run("empty-fuel-options", { confirm: true })
```

Các case `data-changed-*` phải có baseline riêng:

```text
reload → baseline → Kiểm tra ngay (PASS)
reload → data-changed-* → Kiểm tra ngay (DATA_CHANGED)
```

### 3.4. Multiselect, wrapper, ô tìm kiếm và All

| Case | Mutation | Kỳ vọng |
| --- | --- | --- |
| `missing-category-wrapper` | Xóa wrapper Category | `UI_DRIFT_MULTISELECT_WRAPPER` |
| `duplicate-category-wrapper` | Nhân bản wrapper Category | `UI_DRIFT_MULTISELECT_WRAPPER` |
| `moved-category-wrapper` | Đưa wrapper ra sai vị trí | `UI_DRIFT_MULTISELECT_WRAPPER` |
| `missing-fuel-wrapper` | Xóa wrapper Fuel | `UI_DRIFT_MULTISELECT_WRAPPER` |
| `duplicate-fuel-wrapper` | Nhân bản wrapper Fuel | `UI_DRIFT_MULTISELECT_WRAPPER` |
| `moved-fuel-wrapper` | Đưa wrapper ra sai vị trí | `UI_DRIFT_MULTISELECT_WRAPPER` |
| `missing-fuel-search` | Xóa ô search Fuel | `UI_DRIFT_SEARCH_INPUT` |
| `duplicate-fuel-search` | Nhân bản ô search Fuel | `UI_DRIFT_SEARCH_INPUT` |
| `missing-fuel-all` | Xóa checkbox All Fuel | `UI_DRIFT_ALL_OPTION_NOT_FOUND` |
| `duplicate-fuel-all` | Nhân bản checkbox All Fuel | `UI_DRIFT_ALL_OPTION_NOT_FOUND` |

```js
VahanOfficialDevTools.run("missing-category-wrapper", { confirm: true })
VahanOfficialDevTools.run("duplicate-category-wrapper", { confirm: true })
VahanOfficialDevTools.run("moved-category-wrapper", { confirm: true })
VahanOfficialDevTools.run("missing-fuel-wrapper", { confirm: true })
VahanOfficialDevTools.run("duplicate-fuel-wrapper", { confirm: true })
VahanOfficialDevTools.run("moved-fuel-wrapper", { confirm: true })
VahanOfficialDevTools.run("missing-fuel-search", { confirm: true })
VahanOfficialDevTools.run("duplicate-fuel-search", { confirm: true })
VahanOfficialDevTools.run("missing-fuel-all", { confirm: true })
VahanOfficialDevTools.run("duplicate-fuel-all", { confirm: true })
```

### 3.5. Nhiều lỗi trong một lượt

| Case | Số lỗi kỳ vọng | Mục tiêu |
| --- | ---: | --- |
| `two-drift` | 2 | Category và Fuel cùng mất |
| `multi-drift` | 6 | Kiểm tra danh sách nhiều lỗi và thứ tự diagnostic |
| `missing-form` | Tùy DOM, thường >1 | Kiểm tra một mutation làm mất cả cây control |
| `visual-only` | 0 | Đổi style/data attribute không được báo false positive |

```js
VahanOfficialDevTools.run("two-drift", { confirm: true })
// Expected: status=UI_DRIFT, errorCount=2, reports.length=2

VahanOfficialDevTools.run("multi-drift", { confirm: true })
// Expected: status=UI_DRIFT, errorCount=6, reports.length=6

VahanOfficialDevTools.run("visual-only", { confirm: true })
// Expected: PASS nếu chỉ thay đổi visual không thuộc contract
```

`multi-drift` là case trực tiếp nhiều lỗi lớn nhất hiện có trong file DevTools.
Bộ kiểm tra controller tự động còn kiểm tra payload có 10 report; xem mục 11.
Không được dùng một bản ghi giả 10 lỗi để kết luận DOM thật đã phát hiện 10 lỗi.

## 4. Test bằng Elements/Snippets, không cần gõ lệnh Console

### 4.1. Elements panel

1. Mở **DevTools → Elements** trên tab VAHAN.
2. Dùng `Ctrl/Cmd+F` tìm selector.
3. Chuột phải **Delete element**, **Edit as HTML** hoặc đổi attribute.
4. Bấm **Kiểm tra ngay** trên Web UI trước khi reload.
5. Reload trang sau khi lưu diagnostic.

| Case manual | Thao tác Elements | Kỳ vọng |
| --- | --- | --- |
| `E-01` | Xóa `#vehicleFuel` | Thiếu Fuel |
| `E-02` | Đổi `id` Category thành tên khác | Selector cũ count=0 |
| `E-03` | Xóa `multiple` của Category/Fuel | Sai `controlType` |
| `E-04` | Xóa option `Two Wheeler` | Thiếu required option |
| `E-05` | Xóa option `Fuel` của Y-Axis | Thiếu required option |
| `E-06` | Xóa toàn bộ option Fuel | Danh sách rỗng |
| `E-07` | Xóa wrapper multiselect | Wrapper thiếu |
| `E-08` | Nhân bản wrapper multiselect | Wrapper trùng |
| `E-09` | Xóa ô search trong Fuel | Search input thiếu |
| `E-10` | Xóa checkbox All trong Fuel | All option thiếu |
| `E-11` | Đổi đồng thời Category và Fuel | Một lượt có 2 lỗi |
| `E-12` | Đổi ba vùng DOM khác nhau trước một lần check | Tất cả report phải xuất hiện |
| `E-13` | Đặt control vào một wrapper sai vị trí | Sai cấu trúc wrapper |
| `E-14` | Tạo hai `select` cùng ID | Duplicate selector |
| `E-15` | Đưa control vào modal/portal ngoài form | Xác nhận scope contract |
| `E-16` | Đưa control vào iframe | Phải báo thiếu nếu contract không quét iframe |
| `E-17` | Ẩn control bằng `display:none` nhưng không xóa | Ghi nhận đúng theo contract hiện tại |
| `E-18` | Xóa rồi tạo lại control sau vài giây | Kiểm tra timing/dynamic DOM |

Các case `E-15` đến `E-18` là regression về phạm vi contract. Không tự kết luận
là lỗi nếu `guard.js` hiện chỉ kiểm tra selector trong document chính; phải ghi lại
quyết định mong muốn của product rồi mới cập nhật guard.

### 4.2. Sources → Snippets

Để chạy mà không dán vào Console:

1. DevTools → **Sources → Snippets → New snippet**.
2. Dán toàn bộ `official-devtools-test.js`.
3. Thêm một lệnh ở cuối snippet, ví dụ:

   ```js
   VahanOfficialDevTools.run("two-drift", { confirm: true });
   ```

4. Lưu và bấm **Run** hoặc `Ctrl/Cmd+Enter`.
5. Trên Web UI bấm **Kiểm tra ngay**, sau đó reload tab để chạy case khác.

Snippets vẫn chỉ chạy trong tab hiện tại; không thêm CAPTCHA, Apply, submit hoặc
API production.

## 5. Ma trận DOM/data dài hạn

Các case dưới đây không nhất thiết có `caseId` trong harness hiện tại. Dùng
Elements, một test page nội bộ hoặc fixture của controller; ghi rõ `manual-*`
trong `trigger` để không nhầm với case DevTools trực tiếp.

| ID | Tình huống thay đổi website | Kỳ vọng cần xác nhận |
| --- | --- | --- |
| `DOM-01` | Form bị đổi tag hoặc đổi `id` | Required control/selector báo đúng target |
| `DOM-02` | Control bị render hai lần | Duplicate count chính xác, không chỉ lấy phần tử đầu |
| `DOM-03` | Control đổi từ `select` sang `input` | `UI_DRIFT_CONTROL_TYPE` |
| `DOM-04` | Multiselect mất `multiple` | Sai kiểu control |
| `DOM-05` | Wrapper đổi class | Wrapper/search/All diagnostic chỉ đúng selector bị ảnh hưởng |
| `DOM-06` | Search input đổi type/name | `UI_DRIFT_SEARCH_INPUT` hoặc fixture contract tương ứng |
| `DOM-07` | Checkbox All đổi class | `UI_DRIFT_ALL_OPTION_NOT_FOUND` |
| `DOM-08` | Control tồn tại nhưng nằm ngoài form | Kết quả đúng với scope đã thống nhất |
| `DOM-09` | Control nằm trong iframe/shadow root | Không false PASS; ghi rõ giới hạn quét |
| `DOM-10` | Control bị ẩn nhưng vẫn có trong DOM | Kết quả nhất quán giữa hidden và removed |
| `DOM-11` | ID có ký tự đặc biệt hoặc khoảng trắng | Selector không làm health-check throw exception |
| `DOM-12` | ID phân biệt hoa thường | Không nhận nhầm selector gần giống |
| `DOM-13` | DOM có node text/comment lạ | Snapshot vẫn ổn định |
| `DOM-14` | Page render lại bằng React/Angular | Không mất report vì node cũ bị thay thế |
| `DOM-15` | DOM đổi đúng lúc health-check đang đọc | Một kết quả nhất quán, hoặc `CHECK_ERROR` rõ nguyên nhân |
| `DOM-16` | DOM chưa tải xong | Không ghi `PASS` sớm; retry/timeout có diagnostic |
| `DATA-01` | Option bị xóa | `UI_DRIFT_REQUIRED_OPTION` hoặc `DATA_CHANGED` tùy baseline |
| `DATA-02` | Toàn bộ option rỗng | `UI_DRIFT_EMPTY_OPTIONS` |
| `DATA-03` | Đổi text option nhưng giữ value | Digest data phải phát hiện nếu text thuộc contract |
| `DATA-04` | Đổi value nhưng giữ text | Digest data phải phát hiện |
| `DATA-05` | Đổi thứ tự option | Quyết định rõ có coi là thay đổi; không thay đổi ngẫu nhiên |
| `DATA-06` | Trùng value option | Diagnostic chỉ ra duplicate nếu contract yêu cầu |
| `DATA-07` | Trùng label option | Diagnostic chỉ ra duplicate nếu contract yêu cầu |
| `DATA-08` | Option bị disabled | Kết quả phân biệt disabled với missing |
| `DATA-09` | Option bị hidden bằng CSS | Không bị coi là dữ liệu hợp lệ nếu flow không chọn được |
| `DATA-10` | API dữ liệu trả 500/401/empty | `CHECK_ERROR` hoặc empty-options, không `PASS` giả |
| `DATA-11` | Dataset tải chậm hơn timeout | Timeout có `duration`/target rõ ràng |
| `DATA-12` | Dataset đổi trong hai lần kiểm tra | `DATA_CHANGED` chỉ ra control và before/after |
| `DATA-13` | Hai dataset đổi cùng lượt | `changes.length=2`, không gộp mất một change |
| `DATA-14` | Dataset lớn hơn bình thường | Không cắt digest/report; không làm treo extension |
| `DATA-15` | Ký tự Unicode/HTML trong label | Không làm hỏng JSON, CSV hoặc giao diện diagnostic |
| `DATA-16` | Option có thứ tự ổn định nhưng DOM node mới | Không báo false `DATA_CHANGED` nếu nội dung thực sự giống nhau |

## 6. Kiểm tra đúng tab, URL và vòng đời extension

Các case này kiểm tra lỗi “đang mở trang đúng nhưng extension lại trỏ sang tab
khác”. Trong scheduled check, extension chỉ đọc tab VAHAN chính thức đã mở; nó
không tự mở tab và không dùng Web UI làm tab kiểm tra.

| ID | Cách tái hiện | Kỳ vọng |
| --- | --- | --- |
| `TAB-01` | Chỉ mở đúng tab official | Check chạy trên official tab |
| `TAB-02` | Mở Web UI active, official tab background | Vẫn kiểm tra official tab; `pageUrl` là VAHAN |
| `TAB-03` | Mở nhiều tab, một tab official đúng URL | Chọn đúng tab theo URL |
| `TAB-04` | Mở hai tab official đúng URL | Chọn một tab hợp lệ và ghi runner/tab rõ ràng |
| `TAB-05` | Đóng tab official | `CHECK_ERROR`, không tự mở tab |
| `TAB-06` | Đổi official tab sang `/analytics/index.html` | `CHECK_ERROR`, không `PASS` |
| `TAB-07` | Đổi host sang domain giả | `CHECK_ERROR` |
| `TAB-08` | Đổi `https` thành `http` | `CHECK_ERROR` |
| `TAB-09` | Thêm port khác | `CHECK_ERROR` |
| `TAB-10` | Mở URL đúng nhưng loading chưa xong | Chờ/retry hoặc timeout rõ ràng |
| `TAB-11` | Reload giữa lúc request đang pending | Không tạo bản ghi PASS giả hoặc duplicate |
| `TAB-12` | Đổi URL sau khi preflight nhưng trước DOM check | `CHECK_ERROR`/wrong-page rõ nguyên nhân |
| `TAB-13` | Web UI reload khi check đang chạy | Poll/realtime vẫn nhận đúng `checkId` |
| `TAB-14` | Extension reload từ `chrome://extensions` | Content script được khôi phục ở lần check mới |
| `TAB-15` | Content script mất kết nối | Inject/retry theo thiết kế hoặc `CHECK_ERROR` rõ ràng |
| `TAB-16` | Chrome restart, official tab mở lại | Alarm/schedule được khôi phục |
| `TAB-17` | Backend restart khi extension đang chạy | Extension đọc lại schedule và gửi log sau reconnect |
| `TAB-18` | Chrome không có tab official trong kỳ alarm | Ghi `CHECK_ERROR`, không tự mở trang |
| `TAB-19` | Web UI là tab duy nhất | Nút check không tạo `PASS` giả |
| `TAB-20` | Có tab official nhưng extension chưa được cấp quyền | Lỗi quyền/content script được báo rõ |

`UI_DRIFT_WRONG_PAGE` là mã guard-level khi content check được gọi với
`requireOfficial=true` trên tab sai. Luồng Web UI thường có thể ghi
`CHECK_ERROR` vì runner không chọn được tab; không ép hai luồng phải trả cùng một
mã.

## 7. Các mã flow/runtime không tạo ra từ scheduled DOM check

Không dùng `official-devtools-test.js` để giả lập các mã dưới đây rồi kỳ vọng
scheduled health-check tự sinh ra chúng. Chúng thuộc adapter/flow thao tác:

| Mã | Case flow cần kiểm tra |
| --- | --- |
| `UI_DRIFT_WRONG_PAGE` | Gọi guard trên URL không phải official |
| `UI_DRIFT_CHANGED_DURING_RUN` | Lấy preflight signature, sửa control giữa các bước flow |
| `UI_DRIFT_DYNAMIC_CONTROL_TIMEOUT` | Control/option không xuất hiện trong timeout |
| `UI_DRIFT_OPTION_NOT_UNIQUE` | Flow tìm thấy nhiều option cùng tiêu chí |
| `UI_DRIFT_OPTION_CONTROL` | Option không thuộc control adapter mong đợi |
| `UI_DRIFT_SELECTION_NOT_SYNCED` | Chọn option nhưng state/UI không đồng bộ |
| `UI_DRIFT_AXIS_NOT_SYNCED` | X/Y axis hiển thị khác state đã chọn |
| `UI_DRIFT_STALE_FLOW_STATE` | Flow dùng snapshot cũ sau khi page render lại |

Các flow case phải không nhập CAPTCHA thật, không bấm Apply và không tải báo cáo.
Nếu muốn test flow hoàn chỉnh, dùng fixture/staging được cấp quyền.

## 8. Kiểm tra nhiều lỗi và không bị cắt danh sách

### 8.1. Case trực tiếp trên trang thật

```text
reload official
→ run("baseline")
→ Web UI: Kiểm tra ngay
→ PASS, errorCount=0

reload official
→ run("two-drift", { confirm: true })
→ Web UI: Kiểm tra ngay
→ UI_DRIFT, errorCount=2, reports.length=2
```

Với `multi-drift`, kỳ vọng là 6 report. Kiểm tra từng target, code và
`diagnostics.selector`; không chấp nhận hai dòng có cùng selector nếu mutation
chỉ tạo một lỗi.

### 8.2. Case pipeline 10 report

Chạy từ thư mục extension:

```bash
cd /Users/mac/Desktop/vahan/vahan-rpa/vahan-chrome-extension
npm run test:ui-drift
```

Bộ test này tạo payload tổng hợp có 10 `reports[]` và kiểm tra xuyên suốt state,
queue offline và backend payload. Đây là test năng lực truyền/lưu nhiều lỗi, không
thay thế việc kiểm tra DOM thật bằng `multi-drift`.

### 8.3. Tiêu chí chống lỗi “chỉ ghi một lỗi”

| Vị trí | Phải kiểm tra |
| --- | --- |
| Content script | `collectUiDriftReports()` trả đủ mảng |
| Message response | `errorCount` bằng `reports.length` |
| Service worker | Không chỉ lấy `report` đầu tiên khi normalize |
| Offline queue | Queue giữ nguyên toàn bộ `reports[]` |
| POST logs | JSON gửi đủ reports |
| CSV backend | `error_count` bằng tổng lỗi của check |
| Web UI | Dòng chính hiển thị `N lỗi`, diagnostic mở đủ N mục |
| Summary | `UI drift` là số lượt; `lỗi UI` là tổng số lỗi |
| Refresh/retry | Không nhân đôi cùng `checkId` |

### 8.4. Fixture nhiều lỗi tối thiểu

Khi test bằng Swagger/API, dùng cấu trúc này. Các phần tử trong `reports[]` phải
có `code`, `target`, `expected`, `actual`, `diagnostics`; không chỉ lặp lại
`report` đầu tiên:

```json
{
  "status": "UI_DRIFT",
  "errorCount": 2,
  "report": {
    "code": "UI_DRIFT_REQUIRED_CONTROL",
    "target": "Category (#vehicleCategoryGroup)",
    "expected": "DOM phải có đúng 1 control",
    "actual": "DOM đang có 0 control"
  },
  "reports": [
    {
      "code": "UI_DRIFT_REQUIRED_CONTROL",
      "target": "Category (#vehicleCategoryGroup)",
      "diagnostics": { "selector": "#vehicleCategoryGroup", "count": 0 }
    },
    {
      "code": "UI_DRIFT_REQUIRED_CONTROL",
      "target": "Fuel (#vehicleFuel)",
      "diagnostics": { "selector": "#vehicleFuel", "count": 0 }
    }
  ]
}
```

## 9. Test backend, CORS, Socket.IO và lưu CSV

Backend local có các endpoint:

```text
GET    /api/ui-health/schedule
PUT    /api/ui-health/schedule
POST   /api/ui-health/run-now
POST   /api/ui-health/logs
GET    /api/ui-health/reports?date=YYYY-MM-DD
GET    /api/ui-health/reports/{fileName}/download
```

### 9.1. Gửi fixture nhiều lỗi bằng Swagger

Cách này kiểm tra riêng backend và Web UI; nó không thay thế việc sửa DOM thật
trên tab VAHAN.

1. Mở `http://127.0.0.1:8000/docs`.
2. Mở `POST /api/ui-health/logs` → **Try it out**.
3. Dán body dưới đây và bấm **Execute**.
4. Mở Web UI, chọn ngày `2026-01-12`, xác nhận một row `2 lỗi`, mở đủ hai
   diagnostic và tải CSV.

```json
{
  "pageUrl": "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en",
  "runnerId": "manual-md-runner",
  "healthCheck": {
    "checkId": "manual-md-two-drift-001",
    "status": "UI_DRIFT",
    "trigger": "manual-md",
    "startedAt": "2026-01-12T03:00:00.000Z",
    "checkedAt": "2026-01-12T03:00:01.000Z",
    "errorCount": 2,
    "report": {
      "code": "UI_DRIFT_REQUIRED_CONTROL",
      "step": "scheduled-health-check",
      "title": "Control bắt buộc bị thiếu hoặc bị trùng",
      "target": "Category Group (#vehicleCategoryGroup)",
      "expected": "DOM phải có đúng 1 control",
      "actual": "DOM đang có 0 control",
      "action": "Dev kiểm tra selector Category.",
      "message": "Phát hiện thay đổi tại Category.",
      "diagnostics": {
        "selector": "#vehicleCategoryGroup",
        "count": 0
      }
    },
    "reports": [
      {
        "code": "UI_DRIFT_REQUIRED_CONTROL",
        "step": "scheduled-health-check",
        "title": "Control bắt buộc bị thiếu hoặc bị trùng",
        "target": "Category Group (#vehicleCategoryGroup)",
        "expected": "DOM phải có đúng 1 control",
        "actual": "DOM đang có 0 control",
        "action": "Dev kiểm tra selector Category.",
        "message": "Phát hiện thay đổi tại Category.",
        "diagnostics": {
          "selector": "#vehicleCategoryGroup",
          "count": 0
        }
      },
      {
        "code": "UI_DRIFT_REQUIRED_CONTROL",
        "step": "scheduled-health-check",
        "title": "Control bắt buộc bị thiếu hoặc bị trùng",
        "target": "Fuel (#vehicleFuel)",
        "expected": "DOM phải có đúng 1 control",
        "actual": "DOM đang có 0 control",
        "action": "Dev kiểm tra selector Fuel.",
        "message": "Phát hiện thay đổi tại Fuel.",
        "diagnostics": {
          "selector": "#vehicleFuel",
          "count": 0
        }
      }
    ]
  }
}
```

Kết quả phải là HTTP `201`. Khi xem history, `error_count` phải bằng `2`, JSON
diagnostic phải có hai selector khác nhau và dòng Web UI phải hiển thị `2 lỗi`.
Đổi `checkId` và timestamp khi chạy lại; không gửi lặp cùng fixture rồi coi đó là
hai lượt kiểm tra độc lập.

### 9.2. Ma trận API/runner

| ID | Thao tác | Kỳ vọng |
| --- | --- | --- |
| `API-01` | GET schedule khi mới chạy | `200`, mặc định `intervalDays=3` |
| `API-02` | PUT `intervalDays=1` | `200`, `nextCheckAt` hợp lệ |
| `API-03` | PUT `intervalDays=365` | `200` |
| `API-04` | PUT `0`, `366`, số thập phân, chuỗi | `422`, không đổi schedule hợp lệ |
| `API-05` | `run-now` không có runner | `409`, không tạo PASS giả |
| `API-06` | `run-now` có runner nhưng không có official tab | request được nhận, extension ghi `CHECK_ERROR` |
| `API-07` | `run-now` khi runner đang bận | Không chạy chồng; lỗi/trạng thái rõ |
| `API-08` | POST một `PASS` | Lưu một row với `error_count=0` |
| `API-09` | POST một `UI_DRIFT` | Lưu code/target/diagnostic |
| `API-10` | POST `UI_DRIFT` có 2 reports | `error_count=2`, CSV giữ đủ JSON |
| `API-11` | POST có 6 hoặc 10 reports | Không cắt report, không lỗi kích thước ngoài dự kiến |
| `API-12` | POST `DATA_CHANGED` có nhiều `changes[]` | Giữ đủ before/after/change list |
| `API-13` | POST `CHECK_ERROR` | Giữ error/runtime diagnostic |
| `API-14` | POST thiếu `healthCheck` hoặc timestamp hỏng | `4xx`, không ghi row nửa vời |
| `API-15` | POST URL không phải official | Từ chối hoặc ghi lỗi theo policy, không coi là PASS official |
| `API-16` | POST lại cùng `checkId` | Không nhân đôi nếu policy yêu cầu idempotency |
| `API-17` | GET reports theo ngày có dữ liệu | Summary và rows đúng ngày |
| `API-18` | GET ngày không có dữ liệu | Kết quả rỗng, không 500 |
| `API-19` | Download CSV | `200`, UTF-8 BOM, đủ cột và đủ diagnostic |
| `API-20` | Filename download không hợp lệ | `404`, không đọc file ngoài thư mục |
| `API-21` | File vượt 512 KiB | Backend tạo file mới đúng policy |
| `API-22` | Qua hơn 10 ngày | Backend rollover đúng cửa sổ ngày |

### 9.3. CORS và extension origin

Trong DevTools của extension kiểm tra cả request lẫn preflight:

```text
Origin: chrome-extension://ooplajjjjphdcaolokpaenmkjlbcmlhk
GET /api/ui-health/schedule          → 200
POST /api/ui-health/logs             → 201
Access-Control-Allow-Origin          → đúng extension origin
```

Nếu extension ID khác, cấu hình `VAHAN_API_EXTENSION_IDS` bằng đúng ID đó rồi
restart backend. Không dùng `Access-Control-Allow-Origin: *` như cách sửa tắt
CORS cho credentialed request.

Case CORS:

| ID | Cách kiểm tra | Kỳ vọng |
| --- | --- | --- |
| `CORS-01` | GET từ extension origin đã allow | Không có lỗi CORS |
| `CORS-02` | POST log từ extension origin | Backend nhận đủ body |
| `CORS-03` | OPTIONS preflight | Header allow method/header đúng |
| `CORS-04` | Extension ID chưa allow | Lỗi bị chặn rõ; không ghi PASS giả |
| `CORS-05` | Backend restart rồi retry | Request mới hoạt động, queue cũ không mất |
| `CORS-06` | API trả 500/timeout | `CHECK_ERROR` hoặc pending queue, không mất log |

### 9.4. Socket.IO realtime

| ID | Sự kiện | Kỳ vọng |
| --- | --- | --- |
| `SOCKET-01` | Backend phát `ui-health:schedule-updated` | Extension đặt lại alarm |
| `SOCKET-02` | Backend phát `ui-health:run-now` | Đúng một runner nhận request |
| `SOCKET-03` | Runner trả log | `/ui` nhận `ui-health:log-received` |
| `SOCKET-04` | Web UI reload khi event đến | Poll/refresh vẫn lấy được row |
| `SOCKET-05` | Socket disconnect/reconnect | Không tạo duplicate check |
| `SOCKET-06` | Hai runner cùng online | Chỉ một runner xử lý manual request |

## 10. Test Web UI: nút Kiểm tra ngay và lịch sử

### 10.1. Luồng thủ công

1. Mở `http://127.0.0.1:5173/#configure`.
2. Đảm bảo extension và backend đang online.
3. Bấm **Kiểm tra ngay** một lần.
4. Chờ trạng thái pending kết thúc hoặc realtime log xuất hiện.
5. Chọn ngày hiện tại trong **Báo cáo kiểm tra theo ngày**.
6. Kiểm tra summary, dòng lịch sử, diagnostic và CSV.

| ID | Cách tái hiện | Kỳ vọng |
| --- | --- | --- |
| `UI-01` | Check baseline | Một row PASS, `0 lỗi UI` |
| `UI-02` | Check một drift | Một row UI drift, `1 lỗi` |
| `UI-03` | Check `two-drift` | Một row `2 lỗi`, mở đủ 2 diagnostic |
| `UI-04` | Check `multi-drift` | Một row `6 lỗi`, không tách thành lỗi đầu tiên |
| `UI-05` | Gửi 10 reports | Summary tăng tổng 10 lỗi, không chỉ tăng 1 |
| `UI-06` | Click nút liên tiếp nhiều lần | Nút bị disable/debounce; không tạo check trùng |
| `UI-07` | Reload Web UI trong pending | Kết quả mới vẫn gắn đúng check/request |
| `UI-08` | Backend không có runner | Hiển thị lỗi kết nối, không thêm PASS |
| `UI-09` | Runner không có official tab | Row CHECK_ERROR có diagnostic |
| `UI-10` | Mở/đóng diagnostic | Hiển thị đủ report và JSON tương ứng |
| `UI-11` | Bấm **Xem thêm** | Hiển thị thêm rows, không mất rows cũ |
| `UI-12` | Chuyển ngày | Summary/rows/CSV đổi đúng ngày |
| `UI-13` | Ngày không có log | Empty state, không crash |
| `UI-14` | Tải CSV | File đúng ngày, đủ row và error count |
| `UI-15` | Timestamp `Z` | Hiển thị đúng giờ local kèm `GMT+7` |
| `UI-16` | Row cũ `manual-md` | Hiển thị theo timestamp trong payload; không coi là giờ hiện tại |
| `UI-17` | Diagnostic chứa Unicode/HTML | Render an toàn, không phá layout/XSS |
| `UI-18` | Diagnostic rất dài | Có wrap/scroll, không cắt mất JSON |
| `UI-19` | 50+ rows trong ngày | Pagination/load-more ổn định |
| `UI-20` | Nhiều file CSV rollover | Chọn/tải đúng file chứa ngày đã chọn |

### 10.2. Summary phải phân biệt lượt và số lỗi

Ví dụ 23 lượt UI drift, trong đó tổng các `error_count` là 52, phải hiển thị
theo logic tương đương:

```text
23 lượt UI drift · 52 lỗi UI
```

Không dùng số dòng history làm số lỗi. Một row `UI_DRIFT` có 6 reports vẫn là
một lượt kiểm tra nhưng sáu lỗi UI.

### 10.3. Lịch kiểm tra

| ID | Input/thao tác | Kỳ vọng |
| --- | --- | --- |
| `SCHEDULE-01` | Nhập `1` | Lưu được |
| `SCHEDULE-02` | Nhập `365` | Lưu được |
| `SCHEDULE-03` | Nhập `0` | Validation, không gọi PUT hợp lệ |
| `SCHEDULE-04` | Nhập `366` | Validation |
| `SCHEDULE-05` | Nhập số thập phân/chữ | Validation |
| `SCHEDULE-06` | Bấm lưu hai lần | Không tạo schedule duplicate |
| `SCHEDULE-07` | Lưu khi backend offline | Báo lỗi, giữ giá trị cũ |
| `SCHEDULE-08` | Backend reconnect | Schedule được đọc lại, alarm được cập nhật |

## 11. Queue offline, retry và độ bền lâu dài

| ID | Tình huống | Kỳ vọng |
| --- | --- | --- |
| `QUEUE-01` | Tắt backend trước khi gửi PASS | Health-check vào `vahanUiHealthPendingLogs` |
| `QUEUE-02` | Tắt backend khi có 2 reports | Queue giữ nguyên cả 2 reports |
| `QUEUE-03` | Tắt backend khi có 10 reports | Không serialize thành report đầu tiên |
| `QUEUE-04` | Bật backend lại | Gửi bù và xóa đúng item đã gửi |
| `QUEUE-05` | Retry trả 500 | Giữ item, không xóa nhầm |
| `QUEUE-06` | Retry thành công sau lỗi | Không gửi duplicate ngoài policy |
| `QUEUE-07` | Extension reload khi queue còn item | Queue local còn nguyên |
| `QUEUE-08` | Chrome restart khi queue còn item | Queue phục hồi hoặc có diagnostic mất queue |
| `QUEUE-09` | Payload có Unicode/JSON dài | Queue không hỏng parse |
| `QUEUE-10` | Hai check pending liên tiếp | Giữ đúng thứ tự hoặc có sequence rõ |
| `QUEUE-11` | Backend response timeout sau khi đã ghi | Idempotency/checkId không tạo duplicate |
| `QUEUE-12` | Storage gần đầy | Có lỗi rõ ràng; không làm mất các log cũ âm thầm |

## 12. Flow/runtime và tính ổn định khi website đổi liên tục

Đây là các tình huống website thật có thể xảy ra sau release. Chạy trên fixture
hoặc staging nếu flow có thao tác; chỉ dùng trang production cho các mutation DOM
đã được cho phép.

| ID | Tình huống | Kỳ vọng |
| --- | --- | --- |
| `FLOW-01` | Preflight sạch, DOM đổi trước bước chọn | `UI_DRIFT_CHANGED_DURING_RUN` |
| `FLOW-02` | Control xuất hiện sau timeout | `UI_DRIFT_DYNAMIC_CONTROL_TIMEOUT` |
| `FLOW-03` | Có hai option cùng label | `UI_DRIFT_OPTION_NOT_UNIQUE` |
| `FLOW-04` | Adapter nhận sai loại control | `UI_DRIFT_OPTION_CONTROL` |
| `FLOW-05` | Chọn xong nhưng UI không sync | `UI_DRIFT_SELECTION_NOT_SYNCED` |
| `FLOW-06` | X/Y axis lệch nhau | `UI_DRIFT_AXIS_NOT_SYNCED` |
| `FLOW-07` | Page re-render làm snapshot cũ | `UI_DRIFT_STALE_FLOW_STATE` |
| `FLOW-08` | Flow bị timeout | CHECK_ERROR có duration/step |
| `FLOW-09` | Flow bị cancel | Không ghi PASS hoàn tất |
| `FLOW-10` | Flow retry | Không nhân bản diagnostic của lần trước |
| `FLOW-11` | API response chậm | Timeout có target, không treo worker |
| `FLOW-12` | API response malformed | CHECK_ERROR, giữ raw reason an toàn |
| `FLOW-13` | Tab đổi page giữa flow | Wrong page/changed during run |
| `FLOW-14` | Extension mất content script giữa flow | Reconnect/retry hoặc lỗi rõ |

## 13. Test tự động trước mỗi release

Chạy các lệnh sau từ workspace. Các lệnh terminal không thay đổi trang VAHAN
thật và phù hợp với CI:

```bash
cd /Users/mac/Desktop/vahan/vahan-rpa/vahan-chrome-extension
node --check ui-drift/official-devtools-test.js
node --check ui-drift/guard.js
node --check ui-drift/health-check-content.js
node --check ui-drift/health-check.mjs
npm run check
npm run test:ui-drift
npm run build

cd /Users/mac/Desktop/vahan/vahan-rpa/apps/api-server
PYTHONPATH=. .venv/bin/pytest -q

cd /Users/mac/Desktop/vahan/vahan-rpa/apps/web-ui
npm run check
npm run build

cd /Users/mac/Desktop/vahan/vahan-rpa
python3 test_ui_diagnostics.py
python3 test_verify_file.py
```

Tối thiểu phải có các kết quả:

```text
official harness: syntax pass
controller: multi_error_reports=True
controller: offline_queue=True
controller: exact_url_guard=True
backend: multiple reports preserved
web-ui: check/build pass
git diff --check: pass
```

## 14. Bảng kết quả chuẩn để đối chiếu

| Tình huống | Status | Điều kiện đạt |
| --- | --- | --- |
| DOM sạch | `PASS` | `errorCount=0`, `reports=[]` |
| Một lỗi | `UI_DRIFT` | `errorCount=1`, `reports.length=1` |
| Hai lỗi cùng lượt | `UI_DRIFT` | `errorCount=2`, `reports.length=2`, Web UI hiện `2 lỗi` |
| Sáu lỗi cùng lượt | `UI_DRIFT` | `errorCount=6`, `reports.length=6` |
| Mười report pipeline | `UI_DRIFT` | state/queue/backend giữ đủ 10 report |
| Dataset đổi | `DATA_CHANGED` | đủ `diagnostics.changes[]` |
| Không có tab official | `CHECK_ERROR` | URL/runner/reason rõ, không PASS |
| URL sai | `CHECK_ERROR` hoặc guard wrong-page | Không đọc localhost/host khác |
| Backend offline | `CHECK_ERROR` hoặc pending queue | Không mất payload |
| CORS sai | request bị chặn có lý do | Không sửa bằng wildcard tùy tiện |

## 15. Khi phát hiện lỗi: bằng chứng và cách sửa

Health-check chỉ phát hiện và báo cáo. Nó không tự sửa website VAHAN, không tự
đổi selector, không tự bấm Apply và không tự vượt CAPTCHA.

Mỗi lỗi cần lưu tối thiểu:

```text
caseId, checkId, logId, trigger, status, errorCount
pageUrl, startedAt, checkedAt, code, step, target
expected, actual, diagnostics, reports[]
```

Quy trình sửa:

1. Đối chiếu selector/contract với DOM thật.
2. Xác định đây là thay đổi thật của website hay mutation test.
3. Nếu website đã thay đổi, sửa adapter/selector/guard trong source extension.
4. Chạy lại syntax, controller, backend và Web UI test.
5. Reload extension từ `chrome://extensions`.
6. Reload trang official sạch, chạy baseline rồi chạy lại case lỗi.
7. Kiểm tra history và CSV, đặc biệt `errorCount` và toàn bộ `reports[]`.

`VahanOfficialDevTools.restore()` chỉ xóa mutation tạm thời bằng cách khôi phục/
reload tab; đó không phải cơ chế sửa website chính thức.

## 16. Checklist release dài hạn

- [ ] Exact official URL và lựa chọn tab đã được kiểm tra.
- [ ] Baseline PASS sau reload sạch.
- [ ] Đã chạy tất cả 37 case có sẵn trong `official-devtools-test.js` (gồm baseline).
- [ ] Đã chạy ít nhất các case Elements `E-01`, `E-04`, `E-06`, `E-11`, `E-18`.
- [ ] Đã kiểm tra `two-drift`, `multi-drift` và pipeline 10 reports.
- [ ] `errorCount === reports.length` ở content, worker, queue, API, CSV và UI.
- [ ] Summary phân biệt số lượt UI drift với tổng số lỗi UI.
- [ ] Đã kiểm tra tab sai, không có tab, loading, reload và extension reconnect.
- [ ] Đã kiểm tra CORS đúng extension ID.
- [ ] Đã kiểm tra schedule 1–365 và input không hợp lệ.
- [ ] Đã kiểm tra backend offline, retry, queue và duplicate checkId.
- [ ] Đã kiểm tra `DATA_CHANGED` sau baseline.
- [ ] Đã kiểm tra timestamp UTC/GMT+7 và ngày chọn trong lịch sử.
- [ ] Đã tải CSV và xác nhận không mất diagnostic.
- [ ] `npm run check`, `npm run test:ui-drift`, backend pytest và Web UI build đều pass.
