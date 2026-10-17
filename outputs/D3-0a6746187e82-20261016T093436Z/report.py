import harness as h
import json,collections
def write():
    d=json.loads((h.ROOT/'checklist.json').read_text(encoding='utf-8'))
    counts=collections.Counter(r['status'] for r in d['items'])
    current=json.loads((h.ROOT/'r8-current.json').read_text(encoding='utf-8')) if (h.ROOT/'r8-current.json').exists() else None
    text=['# D3 release F — evidence mới','',f'- Cập nhật UTC: {h.now()}',f'- SHA: `{h.SHA}`',f'- Staging: {h.ENV["baseUrl"]}; project `{h.ENV["project"]}`',f'- Images TAR SHA-256: `{h.ENV["imageArchiveDigest"]}`',f'- Manifest SHA-256: `{h.ENV["manifestDigest"]}`','- Người dùng đã chốt gói và lệnh bắt đầu D3; xem [approval.json](approval.json).','- Gate đầu D3 PASS; xem [identity-gate.json](identity-gate.json).','- Source/artifact giữ nguyên trong D3. Helper kiểm thử và evidence nằm ngoài source/gói release.','',f'Tổng hiện tại: {dict(counts)}. NOT_RUN trong lúc D3 đang chạy là mục chưa hoàn tất; không suy PASS từ lần chạy trước.','']
    if current:
        s=current['schedule'];text.extend([f'R8 quan sát gần nhất `{current["at"]}`: **{s["status"]}**, {s["done"]}/{s["total"]}; có dữ liệu {s["withData"]}, NO_DATA {s["noData"]}, failed {s["failed"]}. VAHAN online: {current["network"].get("online")}.',''])
    text+=['| Mục | Kết quả | Bắt đầu UTC | Kết thúc UTC | Evidence / lý do |','| --- | --- | --- | --- | --- |']
    for r in d['items']:
        links=', '.join(f'[{p}]({p})' for p in r['evidence'])
        text.append(f'| {r["item"]} | {r["status"]} | {r["startedAt"] or "—"} | {r["finishedAt"] or "—"} | {r["reason"].replace("|","/")} {links} |')
    text+=['','Mỗi dòng JSON chứa full SHA và cả hai digest: [checklist.json](checklist.json).','', 'Ghi chú harness: lần đầu kiểm preflight sau restart được gọi trước khi runner reconnect (danh sách rỗng →422); đã chờ đủ 3 runner và thực hiện preflight thật PASS. Browser harness ban đầu tìm nút “Sign out”, trong UI nút nằm trong Account và có tên “Log out”; selector đã sửa, 5 trang và logout PASS, 0 page errors. Kiểm lịch sử ban đầu giả định có file NO_DATA cũ; source hiện lưu kết quả vào bảng chính, vì vậy kiểm trạng thái/kết quả thay vì yêu cầu file không thuộc hợp đồng release. Các điều chỉnh này chỉ ở harness; không đổi source, image, dữ liệu kết quả hoặc gate.','']
    (h.ROOT/'REPORT.md').write_text('\n'.join(text),encoding='utf-8')
if __name__=='__main__':write();print('D3 REPORT updated')
