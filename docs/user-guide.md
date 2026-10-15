# Hướng dẫn sử dụng VAHAN Automation

Tài liệu dành cho người mới sử dụng website. Tên nút và tên màn hình được giữ bằng tiếng Anh để bạn dễ tìm trên giao diện.

VAHAN Automation giúp thu thập, xem và tải báo cáo số lượng xe đăng ký theo hãng, khu vực và tháng từ VAHAN.

## 1. Bắt đầu sử dụng

Bạn cần có:

- Đường dẫn website do đơn vị cung cấp dịch vụ gửi.
- Tên đăng nhập và mật khẩu do quản trị viên cấp.
- Máy tính có trình duyệt và kết nối Internet.

Bạn chỉ cần mở website để sử dụng, không cần cài project trên máy.

### Đăng nhập

1. Mở đường dẫn website được cung cấp.
2. Nhập tên đăng nhập vào **Username**.
3. Nhập mật khẩu vào **Password**.
4. Bấm **Sign in**.

Sau khi đăng nhập, bạn sẽ thấy trang **Exported Reports**.

Nếu quên mật khẩu hoặc chưa có tài khoản, hãy liên hệ quản trị viên để được cấp lại.

### Bạn có thể sử dụng những chức năng nào?

| Loại tài khoản | Chức năng |
| --- | --- |
| Người xem báo cáo — Workspace member | Xem, tìm kiếm và tải báo cáo Excel; đổi mật khẩu cá nhân. |
| Quản trị viên — Administrator | Các chức năng trên, cùng với tạo bộ lọc, đặt lịch thu thập báo cáo, xem lịch sử chạy và quản lý tài khoản. |

Nếu bạn chỉ thấy **Exported Reports**, hãy bắt đầu với phần 2 và 3. Đây là giao diện bình thường của tài khoản người xem báo cáo.

## 2. Xem và tìm báo cáo

### Xem dữ liệu

1. Bấm **Exported Reports** trên thanh menu.
2. Chọn năm cần xem ở **Year**.
3. Nếu có ô **Report filters**, chọn bộ báo cáo phù hợp. Ô này chỉ xuất hiện khi có nhiều bộ báo cáo.
4. Xem các dòng trong bảng. Kéo thanh cuộn ngang để xem đủ 12 tháng.
5. Bấm **Next** để sang trang tiếp theo hoặc **Previous** để quay lại.

Bảng hiển thị tối đa 100 dòng mỗi trang.

| Cột trong bảng | Ý nghĩa |
| --- | --- |
| STATE | Bang/khu vực tại Ấn Độ. |
| RTO | Cơ quan đăng ký xe. |
| RTOCode | Mã cơ quan đăng ký xe. |
| Maker | Hãng sản xuất xe. |
| JAN đến DEC | Số lượng đăng ký từ tháng 1 đến tháng 12. |

**Cách đọc số liệu:** `0` nghĩa là không có lượt đăng ký. Dấu `—` trong cột tháng nghĩa là chưa có dữ liệu cho ô đó; không được xem dấu này là số 0.

Khung **Last updated** cho biết thời điểm cập nhật dữ liệu gần nhất. **Months with data** cho biết các tháng đã có dữ liệu trong bộ báo cáo đang xem, không có nghĩa mọi khu vực đều đã thu thập đủ.

### Tìm theo khu vực

1. Nhập tên bang vào **Search State**.
2. Nếu cần tìm cụ thể hơn, nhập tên hoặc mã cơ quan đăng ký xe vào **Search RTO / code**.
3. Chờ bảng cập nhật kết quả.
4. Bấm **Clear** để bỏ điều kiện tìm kiếm và xem lại toàn bộ bộ báo cáo đã chọn.

Ví dụ: để xem dữ liệu của một RTO, chọn năm, nhập bang ở **Search State**, sau đó nhập mã RTO được cung cấp ở **Search RTO / code**.

Nếu bảng trống, thử bấm **Clear**, kiểm tra lại năm và **Report filters**, rồi bấm **Refresh**. Bộ cài mới chưa có dữ liệu cho đến khi quản trị viên thu thập báo cáo.

## 3. Tải báo cáo Excel

### Tải kết quả đang tìm kiếm

1. Chọn năm và bộ báo cáo cần tải.
2. Nhập điều kiện **Search State** hoặc **Search RTO / code**.
3. Bấm **Export filtered to Excel**.
4. Đọc số dòng trong hộp xác nhận. Bấm **OK** để tải hoặc **Cancel** để quay lại.
5. Chờ tải xong và mở file trong thư mục tải xuống của trình duyệt.

File Excel chứa **tất cả các dòng khớp điều kiện**, kể cả các dòng ở trang tiếp theo.

### Tải toàn bộ bộ báo cáo

1. Bấm **Clear** nếu đang tìm kiếm theo State/RTO.
2. Kiểm tra **Year** và **Report filters** nếu có.
3. Bấm **Export all to Excel**.
4. Kiểm tra số dòng và bấm **OK** để xác nhận.

“Toàn bộ” là toàn bộ bộ báo cáo và năm đang chọn. Khi nút hiển thị **Exporting…**, hãy chờ tải xong trước khi bấm lại.

## 4. Đổi mật khẩu và đăng xuất

### Mở phần tài khoản

- Người xem báo cáo: bấm **Account** ở phía trên trang.
- Quản trị viên: vào **Settings**, rồi bấm **Account**.

### Đổi mật khẩu

1. Trong **Account settings**, mở **Change password** nếu có các tab.
2. Nhập mật khẩu hiện tại vào **Current password**.
3. Nhập mật khẩu mới vào **New password**; dùng ít nhất 12 ký tự.
4. Nhập lại mật khẩu mới vào **Confirm new password**.
5. Bấm **Update password** và chờ thông báo thành công.

Sau khi đổi mật khẩu, tài khoản sẽ được đăng xuất trên các thiết bị khác.

### Chọn múi giờ

Trong **Account**, chọn **Display time zone**:

- **Vietnam time (UTC+07:00)**: giờ Việt Nam.
- **India time (UTC+05:30)**: giờ Ấn Độ.

Với quản trị viên, thao tác đổi múi giờ còn cập nhật múi giờ của lịch đã lưu. Sau khi đổi, hãy kiểm tra lại giờ chạy trong **Settings**.

### Đăng xuất

Mở **Account** và bấm **Log out**. Nếu website yêu cầu đăng nhập lại sau một thời gian không sử dụng, nhập lại tài khoản để tiếp tục.

## 5. Tạo bộ lọc thu thập báo cáo — dành cho quản trị viên

Bộ lọc là các lựa chọn cho biết bạn muốn thu thập báo cáo nào, chẳng hạn năm, bang, RTO, loại xe và nhiên liệu.

### Tạo bộ lọc mới

1. Vào **Filters**.
2. Bấm **New filters**.
3. Nhập tên dễ nhớ ở **Filter name**, ví dụ: “Xe điện hai bánh — 2026”.
4. Chọn năm báo cáo ở **From** hoặc **To**. Hiện hai ô cùng chọn một năm, không phải khoảng nhiều năm.
5. Chờ các lựa chọn từ VAHAN tải xong.
6. Mở từng mục cần thay đổi, tìm và chọn các giá trị phù hợp.
7. Bấm **Save filters** để lưu, hoặc **Save & preview** để lưu và xem trước các báo cáo sẽ thu thập.

**Hãy kiểm tra các lựa chọn mặc định trước khi lưu:** bộ lọc mới đã có một số lựa chọn về xe hai bánh và nhiên liệu điện. Đổi chúng nếu nhu cầu của bạn khác.

| Mục thường dùng | Dùng để chọn |
| --- | --- |
| State / RTO | Bang và cơ quan đăng ký xe. Chọn State trước rồi kiểm tra lại RTO. |
| Maker | Hãng sản xuất xe. |
| Category Group / Sub-Category / Class | Nhóm, phân nhóm và loại xe. Chọn từ nhóm lớn đến nhóm nhỏ. |
| EV Type / Fuel | Loại xe điện và nhiên liệu. Sau khi đổi EV Type, kiểm tra lại Fuel. |
| Active / Archive Type | Nhóm hồ sơ đang hoạt động hoặc lưu trữ. |

Các lựa chọn phụ thuộc nhau có thể thay đổi khi bạn chọn một mục khác. Hãy rà soát lại trước khi lưu.

### Hiểu cách chọn nhiều giá trị

Trong các mục có **Collect reports using**:

- **Selected choices together**: sử dụng các giá trị đã chọn cùng nhau trong một điều kiện lọc.
- **Each choice separately**: thu thập riêng cho từng giá trị. Ví dụ, chọn hai bang thì hệ thống xử lý riêng từng bang.

Ở chế độ **Each choice separately**, để trống danh sách lựa chọn nghĩa là dùng tất cả lựa chọn khả dụng. Lần đầu nên chọn phạm vi nhỏ và xem trước để biết khối lượng công việc.

**Save & preview** chỉ xem trước kế hoạch, chưa bắt đầu thu thập báo cáo. Sau khi lưu, tiếp tục đặt lịch ở phần 6.

Để sửa bộ lọc, chọn tên trong **Saved filters**, thay đổi nội dung rồi lưu lại. Để xóa, bấm **Delete** và đọc hộp xác nhận; báo cáo đã thu thập được giữ lại.

## 6. Đặt lịch thu thập — dành cho quản trị viên

### Tạo lịch

1. Vào **Settings**.
2. Trong **Automatic report schedule**, bấm **Show form**.
3. Chọn bộ lọc ở **Saved filters**.
4. Chọn ngày ở **Start date** và giờ ở **Start time**. Lần đầu, chọn một thời điểm sắp tới để có thời gian kiểm tra.
5. Kiểm tra múi giờ hiển thị ở cuối biểu mẫu.
6. Chọn **Repeat**:
   - **Once**: chạy một lần vào ngày giờ đã chọn.
   - **Every month**: chạy hằng tháng vào cùng ngày và giờ.
7. Bấm **Add schedule**.
8. Kiểm tra lịch vừa tạo trong **Saved schedules**, đặc biệt là **Next start**.

Năm báo cáo lấy từ bộ lọc đã lưu. Ngày chạy có thể khác năm dữ liệu cần thu thập.

Với lịch tháng, nếu tháng không có ngày đã chọn, hệ thống chạy vào ngày cuối tháng. Ví dụ, lịch ngày 31 sẽ chạy vào ngày cuối tháng 2. Khi hoàn tất năm báo cáo và lịch vẫn bật, hệ thống tự tạo bộ lọc và lịch riêng cho năm tiếp theo. Muốn ngừng tiếp tục hằng năm, tắt các lần chạy tương lai.

### Tạm dừng, tiếp tục và ngừng lịch

| Nút | Kết quả |
| --- | --- |
| Pause run | Tạm dừng lượt đang chạy. Hệ thống xử lý xong công việc đã nhận trước khi dừng, nên có thể hiện Pausing một lúc. |
| Continue run | Tiếp tục phần chưa hoàn thành của lượt đang tạm dừng. |
| Disable future runs | Tắt các lần chạy tương lai. Lượt hiện đang chạy vẫn tiếp tục. |
| Enable schedule | Bật lại các lần chạy tương lai. |
| Delete schedule | Xóa lịch và công việc chưa hoàn thành; dữ liệu đã thu thập được giữ lại. Nút chỉ dùng được khi trạng thái cho phép. |

Muốn tạm dừng lượt hiện tại và ngăn các lần chạy sau: bấm **Pause run**, sau đó **Disable future runs**.

Bạn có thể đóng tab sau khi lưu lịch; việc thu thập diễn ra trên hệ thống. Máy chủ phải tiếp tục hoạt động. Khi không có trình duyệt thu thập khả dụng, lịch sẽ chờ.

## 7. Theo dõi kết quả — dành cho quản trị viên

Vào **Run History** để xem lịch sử, lượt mới nhất nằm trên cùng. Bấm **Refresh history** nếu cần cập nhật ngay.

Một “case” là một công việc thu thập theo tổ hợp bộ lọc. **Progress** cho biết số công việc đã xử lý trên tổng số; số đã xử lý có thể bao gồm cả công việc lỗi.

| Trạng thái | Ý nghĩa và cách xử lý |
| --- | --- |
| Preparing / Resuming | Đang chuẩn bị hoặc tiếp tục. Chờ hệ thống xử lý. |
| Running | Đang thu thập báo cáo. |
| Pausing / Paused | Đang tạm dừng / đã tạm dừng. Tiếp tục tại Settings bằng Continue run. |
| Completed | Lượt chạy đã hoàn tất. |
| Completed with errors | Đã kết thúc nhưng còn công việc lỗi. Kiểm tra Failed và thông báo trong Settings. |
| Error | Có lỗi cần kiểm tra. Gửi thông báo lỗi cho bộ phận hỗ trợ. |
| Stopped | Lượt chạy đã dừng. |

Trong **Results**:

- **With data**: công việc có dữ liệu.
- **No data**: nguồn báo cáo không có bản ghi cho điều kiện đó; đây không phải lỗi tải báo cáo.
- **Failed**: công việc gặp lỗi.

Dữ liệu đã lưu xuất hiện ở **Exported Reports**. Có một phần dữ liệu không đồng nghĩa toàn bộ lượt chạy đã hoàn tất. Hệ thống có thể tự thử lại công việc chưa hoàn thành; hãy theo dõi trước khi tạo lịch trùng.

## 8. Cấp tài khoản — dành cho quản trị viên

1. Vào **Settings → Account → Manage user accounts**.
2. Nhập **Username** và **Password**; mật khẩu ít nhất 12 ký tự.
3. Bấm **Create account**.
4. Kiểm tra vai trò trong danh sách và gửi thông tin đăng nhập riêng cho người dùng.

Các nút quản lý:

- **Reset password**: đặt lại mật khẩu khi người dùng quên. Nhập và xác nhận mật khẩu mới, rồi bấm **Save new password**.
- **Disable / Enable**: khóa hoặc mở lại quyền đăng nhập.
- **Make administrator**: cấp quyền quản trị.
- **Make report viewer**: chuyển về quyền xem và tải báo cáo.

Chỉ cấp quyền quản trị cho người phụ trách bộ lọc, lịch chạy hoặc tài khoản.

## 9. Khi gặp vấn đề

| Vấn đề | Bạn nên làm gì? |
| --- | --- |
| Không đăng nhập được | Kiểm tra tên đăng nhập, mật khẩu và Caps Lock. Nếu vẫn lỗi, nhờ quản trị viên kiểm tra tài khoản hoặc đặt lại mật khẩu. |
| Could not connect hoặc thông báo mất kết nối | Kiểm tra Internet, chờ kết nối trở lại rồi tải lại trang. Nếu vẫn lỗi, liên hệ hỗ trợ. |
| Không thấy Filters, Settings hoặc Run History | Tài khoản có quyền xem báo cáo. Nhờ quản trị viên cấp quyền nếu công việc yêu cầu. |
| Không thấy dữ liệu | Bấm Clear, kiểm tra Year và Report filters, rồi Refresh. Nếu chưa có báo cáo được thu thập, nhờ quản trị viên đặt lịch. |
| Nút xuất Excel bị mờ | Chờ bảng tải xong và kiểm tra có dòng dữ liệu khớp điều kiện không. |
| Bấm tải nhưng chưa thấy file | Chờ Exporting… kết thúc và kiểm tra danh sách tải xuống của trình duyệt. Nếu có thông báo lỗi, gửi cho hỗ trợ. |
| Bộ lọc đang chờ hoặc không sửa được | Chờ lượt thu thập hiện tại kết thúc hoặc trình duyệt thu thập sẵn sàng. Nếu chờ lâu, liên hệ hỗ trợ. |
| Lịch chưa chạy dù đã đến giờ | Kiểm tra múi giờ, lịch có bật không và thông báo tại Settings. Hệ thống có thể đang chờ trình duyệt thu thập. |
| Website check / Cannot start yet | Trong Settings, mở Website check nếu có cảnh báo. Bấm Copy all issues hoặc Copy for support và gửi cho hỗ trợ. Chờ xử lý trước khi tiếp tục. |

Khi nhờ hỗ trợ, gửi tên màn hình, thời điểm xảy ra, thao tác vừa thực hiện, tên bộ lọc/lịch hoặc số lượt chạy nếu có, cùng nội dung thông báo lỗi. Có thể gửi ảnh chụp màn hình nếu cần. **Không gửi mật khẩu.**

## 10. Quy trình sử dụng hằng ngày

**Người xem báo cáo:** đăng nhập → chọn năm và bộ báo cáo → tìm State/RTO → kiểm tra dữ liệu → tải Excel → đăng xuất.

**Quản trị viên:** tạo và kiểm tra bộ lọc → đặt lịch → theo dõi Run History → kiểm tra dữ liệu tại Exported Reports → cấp tài khoản cho người cần xem báo cáo.
