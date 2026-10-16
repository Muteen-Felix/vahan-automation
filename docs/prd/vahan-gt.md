---
id: vahan
---
# VAHAN Automation — Ground-Truth PRD

Nguồn: VAHAN-PRD-001 v1.0 (docs/vahan-prd.md).

## US-1: Tài khoản và phiên đăng nhập

### Acceptance Criteria

- AC-1.1: Đăng nhập bằng username/password hợp lệ; tài khoản bị khóa hoặc thông tin sai không nhận phiên sử dụng hợp lệ. (FR-AUTH-01)
- AC-1.2: Áp quyền ở server cho mọi API nghiệp vụ; member truy cập trực tiếp chức năng admin nhận từ chối phù hợp, kể cả khi sửa URL/request. (FR-AUTH-02)
- AC-1.3: Phiên có giới hạn tuyệt đối 12 giờ và idle 1 giờ theo cấu hình code hiện tại; khi hết hạn, thao tác được bảo vệ yêu cầu đăng nhập lại. Polling không được coi mặc nhiên là hoạt động người dùng. (FR-AUTH-03)
- AC-1.4: Đăng xuất thu hồi phiên hiện tại; token phiên bị thu hồi không được tiếp tục gọi API được bảo vệ. (FR-AUTH-04)
- AC-1.5: Người dùng đổi mật khẩu bằng mật khẩu hiện tại và mật khẩu mới khác, dài tối thiểu 12 ký tự; phiên khác bị thu hồi, phiên hiện tại được giữ theo handler. (FR-AUTH-05)
- AC-1.6: Admin tạo tài khoản, reset mật khẩu, khóa/mở và đổi role; username trùng bị từ chối và mật khẩu reset tuân giới hạn đầu vào. (FR-AUTH-06)
- AC-1.7: Không cho khóa/hạ role làm mất admin đang hoạt động cuối cùng. Đổi role hoặc khóa tài khoản làm các phiên của tài khoản đó mất hiệu lực. (FR-AUTH-07)
- AC-1.8: Cho chọn múi giờ hiển thị Việt Nam/Ấn Độ. Với admin, luồng thay đổi có cập nhật múi giờ lịch đã lưu theo triển khai; phải kiểm lại thời điểm chạy và hiển thị, không coi chỉ là đổi nhãn. (FR-AUTH-08)
- AC-1.9: Ví dụ nghiệm thu: member đăng nhập, xem báo cáo thành công, sau đó gọi API tạo lịch và nhận 403. Việc menu bị ẩn riêng lẻ chưa đủ chứng minh phân quyền đúng. (Ví dụ nghiệm thu mục 5.2)

## US-2: Filter Profiles và lập kế hoạch

Lưu ý đầu vào: model hiện giới hạn mỗi danh sách values/include ở 100, exclude ở 500 và combination rules ở 30. Đây là validation của definition, không phải cam kết giới hạn tổng số case. Không suy từ sự tồn tại của khóa `maxCases` legacy rằng hệ thống còn áp trần đó.

### Acceptance Criteria

- AC-2.1: Admin tạo/sửa/xóa profile có tên và definition version; tên không trắng, tối đa 120 ký tự; update có kiểm revision theo hợp đồng lưu. (FR-FLT-01)
- AC-2.2: Profile gắn một năm Calendar Year, trục Y Maker và trục X Month Wise; từ chối định nghĩa ngoài schema, năm sai kiểu hoặc vượt giới hạn model. (FR-FLT-02)
- AC-2.3: Hỗ trợ State region, State, RTO, Category group, Sub-category, Class, EV type, Fuel, Active/Archive, Emission, Maker, Status, Owner type, Vehicle type và Fitness theo field hợp lệ. (FR-FLT-03)
- AC-2.4: Option preview/điền filter lấy từ nguồn VAHAN qua runner; không có option thật hoặc runner hợp lệ thì chờ/báo lỗi, không tự thay bằng danh sách mẫu. (FR-FLT-04)
- AC-2.5: Giữ thứ tự phụ thuộc: State region → State → RTO; Category group → Sub-category → Class; EV type → Fuel. Đổi cha phải rà lại lựa chọn con. (FR-FLT-05)
- AC-2.6: `fixed` dùng các giá trị chọn cùng một điều kiện; `iterate` tách từng giá trị thành nhánh. Iterate không chỉ định tập con dùng toàn bộ option hợp lệ của ngữ cảnh. (FR-FLT-06)
- AC-2.7: Áp include/exclude và combination rules require/exclude trước khi xác định tập case; trường không hỗ trợ và rule tự tham chiếu bị từ chối. (FR-FLT-07)
- AC-2.8: Save & preview cho biết kế hoạch/số case mà không bắt đầu thu thập; các nhánh cần thu thập không bị bỏ âm thầm. (FR-FLT-08)
- AC-2.9: Mỗi case có bộ filter xác định và khóa chuẩn hóa để hỗ trợ đối chiếu/lặp; không tạo hai case chỉ vì khác thứ tự cùng tập lựa chọn. (FR-FLT-09)
- AC-2.10: Xóa profile yêu cầu xác nhận và đúng revision; báo cáo đã lưu vẫn được giữ. Lịch giữ snapshot definition/profileRevision trong dữ liệu riêng; không giả định xóa profile sẽ cascade xóa lịch hoặc kết quả. (FR-FLT-10)
- AC-2.11: Ví dụ nghiệm thu: chọn 2 State ở iterate, mỗi State có tập RTO riêng. Preview phải dùng RTO đúng State, tính đúng tổng nhánh và không tạo tích chéo State/RTO không hợp lệ. (Ví dụ nghiệm thu mục 5.3)

## US-3: Lịch thu thập tự động

Không đặt độ trễ chạy lịch bằng 0 giây: scheduler còn phụ thuộc preflight và năng lực runner. Ngân sách trễ chấp nhận được phải đo trên môi trường mục tiêu.

### Acceptance Criteria

- AC-3.1: Admin tạo lịch từ profile đã lưu với thời điểm tương lai có timezone/offset; từ chối thời gian quá khứ hoặc thiếu timezone. (FR-SCH-01)
- AC-3.2: Hỗ trợ `once`/`monthly`; `daily` hoặc kiểu repeat khác bị từ chối. Múi giờ hỗ trợ là `Asia/Ho_Chi_Minh` và `Asia/Kolkata`. (FR-SCH-02)
- AC-3.3: Form lấy năm báo cáo từ profile, không yêu cầu worker count theo lịch. Các khóa `workerCount` legacy không được dùng để thay pool hoặc phục hồi concurrency cũ. (FR-SCH-03)
- AC-3.4: Lịch đến hạn được scheduler phía server xử lý dù tab đã đóng; nếu thiếu runner/mạng/preflight thì giữ trạng thái chờ đúng nguyên nhân. (FR-SCH-04)
- AC-3.5: Lịch Once hoàn tất không tự lập lại lần kế tiếp; thể hiện không còn future run. (FR-SCH-05)
- AC-3.6: Monthly giữ giờ địa phương theo zone; ngày không tồn tại trong tháng được clamp về cuối tháng. Kiểm riêng ngày 29/30/31 và qua năm. (FR-SCH-06)
- AC-3.7: Luồng chuyển năm tạo profile/lịch năm tiếp theo theo logic thực tế, giữ liên hệ và tránh bản sao trùng; chưa có full live evidence cho mọi biên lịch thì ghi rõ khi nghiệm thu. (FR-SCH-07)
- AC-3.8: Disable future runs ngừng các lần tương lai, không đồng nghĩa pause lượt hiện tại; bật lại cần có next start nhất quán. (FR-SCH-08)
- AC-3.9: Xóa lịch chỉ khi trạng thái và ràng buộc cho phép; giữ báo cáo đã commit, thông báo rõ tác động lên phần công việc chưa hoàn thành. (FR-SCH-09)

## US-4: Queue, thực thi browser và OCR

Luồng nghiệp vụ rút gọn: claim → mở/khôi phục VAHAN → kiểm giao diện → điền và xác minh filter → xử lý CAPTCHA khi có → Apply → đợi kết quả → tải/commit DATA hoặc ghi NO_DATA → trả case về trạng thái cuối. Đây là luồng nghiệp vụ, không yêu cầu thứ tự CAPTCHA cố định cho mọi trạng thái trang nguồn. WAITING_CAPTCHA là trạng thái thực thi báo cáo, không phải bằng chứng ứng dụng dùng CAPTCHA đăng nhập hoặc MFA. Baseline không cam kết tỷ lệ OCR thành công 100%.

### Acceptance Criteria

- AC-4.1: Lưu run/session/task/case trong SQL; runner claim bằng transaction, kiểm trạng thái/lease/giới hạn để tránh cùng case bị giao đồng thời không hợp lệ. (FR-RUN-01)
- AC-4.2: Mỗi runner xử lý tối đa một case thực thi cùng lúc; số đang chạy không vượt runner đủ điều kiện và giới hạn logic có hiệu lực. (FR-RUN-02)
- AC-4.3: Preflight kiểm control/DOM theo UI contract trước thao tác cần gate; không Apply để vượt khi gate chưa đạt. Lưu bằng chứng và version contract. (FR-RUN-03)
- AC-4.4: Điền filter theo phụ thuộc, đọc lại DOM để xác minh lựa chọn; sai hoặc thiếu điều kiện phải báo lỗi, không ghi kết quả như đúng phạm vi. (FR-RUN-04)
- AC-4.5: OCR dùng Tesseract trong runner với challenge hiện tại. API bắt đầu OCR kiểm credential runner, job đang thuộc runner, trạng thái và captchaId; challenge cũ bị từ chối. (FR-RUN-05)
- AC-4.6: Ứng dụng không áp quota số lần bắt đầu OCR; điều này không loại bỏ validation, timeout, retry policy hay giới hạn của VAHAN. Không log chuỗi OCR thô. (FR-RUN-06)
- AC-4.7: DATA yêu cầu workbook export đầy đủ từ nguồn, upload vào main-report và chờ API xác nhận lưu trước khi nhận case kế tiếp; export thiếu/commit lỗi không được báo thành công. (FR-RUN-07)
- AC-4.8: NO_DATA chỉ được ghi khi có bằng chứng nguồn hợp lệ; timeout, TLS, 404 hoặc lỗi download không được chuyển thành NO_DATA. (FR-RUN-08)
- AC-4.9: Kết quả gửi lại hoặc đến muộn phải qua kiểm identity/trạng thái phù hợp; không ghi đè attempt mới hoặc đếm hoàn tất hai lần. (FR-RUN-09)
- AC-4.10: Ghi nhận lỗi có stage/code/detail phù hợp để phân biệt mở trang, network, DOM, OCR, Apply, download và lưu báo cáo. (FR-RUN-10)

## US-5: Pause, resume, retry và phục hồi

Số lần retry, checkpoint và timeout cụ thể tuân policy trong source/bản release. PRD không dùng một con số lịch sử để thay toàn bộ policy của các loại lỗi khác nhau.

### Acceptance Criteria

- AC-5.1: Pause ngừng giao mới và drain attempt đang xử lý; giao diện phân biệt Pausing/Paused. (FR-REC-01)
- AC-5.2: Resume cùng queue/session, kiểm gate theo yêu cầu; không tạo một lượt mới để che trạng thái lượt cũ. (FR-REC-02)
- AC-5.3: Retry giữ case identity, bộ filter và session gốc; job retry liên kết attempt trước, không tăng tổng case nghiệp vụ. (FR-REC-03)
- AC-5.4: NO_DATA hợp lệ không bị đưa vào vòng retry lỗi. Case thất bại cuối giữ nguyên nguyên nhân và số lần thử. (FR-REC-04)
- AC-5.5: Runner disconnect được xử lý theo grace/lease; chỉ giao lại sau khi kiểm quyền sở hữu và tình trạng attempt, không coi mất socket là thành công. (FR-REC-05)
- AC-5.6: Restart API khôi phục từ SQL và không ghi đè dữ liệu đã lưu bằng state phía UI; kiểm cả trường hợp đang có attempt chưa ổn định. (FR-REC-06)
- AC-5.7: Mất mạng VAHAN có thể dẫn đến chờ/tạm ngừng cấp việc theo policy; mạng trở lại thì tiếp tục khi điều kiện hợp lệ, không thay đổi phạm vi run. (FR-REC-07)
- AC-5.8: Thay runner ID giữa lượt phải được kiểm lại binding/preflight. Đề xuất tự đưa runner thay thế đủ điều kiện vào lượt mà không cần pause/resume thủ công, sau khi xử lý gate an toàn. (FR-REC-08; ĐX — chưa triển khai)

## US-6: Báo cáo dùng chung, tìm kiếm và xuất Excel

API export hiện chấp nhận tối đa 1.048.573 dòng dữ liệu do workbook dành ba dòng đầu cho tiêu đề/summary/header. Đây là giới hạn kỹ thuật trong code; không phải bằng chứng export quy mô đó đã đạt ngân sách RAM/thời gian mong muốn.

### Acceptance Criteria

- AC-6.1: Admin/member xem cùng kho báo cáo được cấp quyền, chọn năm và dataset; nếu chưa có dữ liệu hiển thị empty state thật. (FR-RPT-01)
- AC-6.2: Hiển thị State, RTO, RTOCode, Maker và 12 tháng; không biến tháng NULL thành 0. `—` biểu diễn thiếu dữ liệu trên UI. (FR-RPT-02)
- AC-6.3: Search State và Search RTO/code lọc theo phạm vi đã chọn; Clear xóa điều kiện tìm kiếm, không chuyển âm thầm sang dataset khác. (FR-RPT-03)
- AC-6.4: Bảng phân trang tối đa 100 dòng/trang theo UI hiện tại; thay điều kiện không giữ offset khiến người dùng tưởng mất dữ liệu. (FR-RPT-04)
- AC-6.5: Hiển thị số dòng, thống kê và Last updated/Months with data theo dữ liệu phản hồi; tháng có dữ liệu ở một dòng không chứng minh mọi RTO đã đủ. (FR-RPT-05)
- AC-6.6: Export filtered lấy toàn bộ dòng khớp dataset/year/State/RTO, kể cả vượt 100 dòng; thứ tự và số liệu khớp điều kiện bảng. (FR-RPT-06)
- AC-6.7: Export all yêu cầu xác nhận trên UI và `confirmAll=true` ở API khi không có State/RTO search; thiếu xác nhận nhận 409. (FR-RPT-07)
- AC-6.8: Cả export filtered/all có hộp xác nhận trong trang nêu phạm vi, năm và số dòng; có hủy, Escape, focus phù hợp và trạng thái đang tải. (FR-RPT-08)
- AC-6.9: Không có dòng khớp thì không xuất file gây hiểu nhầm; API trả 404 phù hợp. Vượt ngưỡng worksheet thì trả 413 và hướng dẫn thu hẹp tìm kiếm. (FR-RPT-09)
- AC-6.10: Excel có tiêu đề, thông tin phạm vi/summary, header và dữ liệu; giữ đủ 12 tháng và ý nghĩa 0/thiếu, bảo toàn số lớn theo khả năng định dạng. (FR-RPT-10)
- AC-6.11: Lưu lịch sử cập nhật và nguồn/checksum phù hợp để kiểm ingest lặp và đối chiếu dữ liệu thay đổi; không coi Last updated là thời điểm nguồn hoàn thiện mọi tháng. (FR-RPT-11)
- AC-6.12: Ví dụ nghiệm thu: có 250 dòng khớp tìm kiếm, UI hiển thị 100 dòng trang đầu. Export filtered phải có đủ 250 dòng dữ liệu, không tính ba dòng đầu của workbook. Nếu dữ liệu đang cập nhật, kiểm trên snapshot/môi trường kiểm soát thay vì coi sai khác giữa hai thời điểm là lỗi cắt trang. (Ví dụ nghiệm thu mục 5.7)

## US-7: Run History, tiến độ và diagnostics

### Acceptance Criteria

- AC-7.1: Run History chỉ admin xem; một lượt/session có một dòng tổng hợp, retry không sinh thêm dòng như lượt độc lập. (FR-OBS-01)
- AC-7.2: Hiển thị tổng case, processed, with data, no data, failed và trạng thái cuối đúng định nghĩa; processed không được hiểu là tất cả thành công. (FR-OBS-02)
- AC-7.3: Có refresh và thời điểm trạng thái liên quan; nguồn dữ liệu từ API/DB, không có chế độ mẫu trong Run History sản phẩm. (FR-OBS-03)
- AC-7.4: ETA dựa trên throughput/active elapsed của lượt; thiếu mẫu, pause hoặc stall phải thể hiện chờ/không xác định phù hợp. Sai số cần được đo, không cam kết giờ hoàn thành tuyệt đối. (FR-OBS-04)
- AC-7.5: UI Health cung cấp diagnostics có thể copy/download, liên hệ với runner/check; trạng thái mất kết nối không được tự coi là đã sửa DOM. (FR-OBS-05)
- AC-7.6: Phân biệt chờ runner/bận planning với lỗi website khi có bằng chứng tương ứng; thông báo phải giúp người vận hành chọn bước xử lý. (FR-OBS-06)
- AC-7.7: API audit phục vụ admin truy vết thao tác theo actor/time/event trong phạm vi được ghi; không tuyên bố ghi đầy đủ mọi read request hay chống sửa. (FR-OBS-07)

## US-8: Công cụ vận hành sản phẩm

### Acceptance Criteria

- AC-8.1: Cung cấp hướng dẫn cài mới với secrets riêng, migration và thứ tự khởi động có kiểm readiness. (FR-OPS-01)
- AC-8.2: Guard trước thay dịch vụ phát hiện active job, planning lease, queue/lịch hoạt động và từ chối khi không an toàn; không dùng force restart thay điều khiển nghiệp vụ. (FR-OPS-02)
- AC-8.3: Backup có dump/config cần thiết và manifest/hash; lưu có kiểm soát quyền vì có thể chứa secrets. (FR-OPS-03)
- AC-8.4: Restore vào project tách biệt, giữ encryption key, đối chiếu dữ liệu và quyền runtime trước chuyển traffic. (FR-OPS-04)
- AC-8.5: Gói bàn giao nhận diện image/revision, bằng chứng; build thành công không được ghi thành deployed/runtime pass. (FR-OPS-05)
