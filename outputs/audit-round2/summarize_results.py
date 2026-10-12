"""Build the final per-file result table from retained run evidence."""
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
raw = json.loads((HERE / 'results.json').read_text(encoding='utf-8'))
rows = {item['file']: dict(item) for item in raw if not item['file'].endswith('-migrate')}

def log_text(name):
    data = (HERE / name).read_bytes()
    return data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')

def junit(name):
    tree = ET.parse(HERE / name)
    suites = list(tree.iter('testsuite'))
    result = {key: sum(int(s.get(key, 0)) for s in suites)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    assert result['tests'] and not any(result[k] for k in ('failures', 'errors', 'skipped')), (name, result)
    return tree, result

core, _ = junit('api-core-verified.xml')
groups = defaultdict(list)
for case in core.iter('testcase'):
    groups[case.get('classname')].append(case)
for classname, cases in groups.items():
    file = 'apps/api-server/' + classname.replace('.', '/') + '.py'
    rows[file] = dict(file=file, status='PASS', exit_code=0, tests=len(cases),
                      failures=0, errors=0, skipped=0, log='api-core-verified.log',
                      evidence='api-core-verified.xml')

for file, xml, log in [
    ('apps/api-server/verification/test_queue_retry_checkpoints.py', 'retry-checkpoints-final.xml', 'retry-checkpoints-final.log'),
    ('apps/api-server/verification/test_worker_pool.py', 'worker-pool-final.xml', 'worker-pool-final.log'),
]:
    _, counts = junit(xml)
    rows[file].update(counts, status='PASS', exit_code=0, log=log, evidence=xml)

for file, log, marker in [
    ('apps/api-server/verification/test_main_migration.py', 'legacy-main-migration.log', '"originalDatesAndSourcesPreserved": true'),
    ('apps/api-server/verification/test_main_live_workbook.py', 'legacy-workbook-replay.log', '"duplicateRowsAdded": 0'),
    ('apps/api-server/verification/test_shared_migration.py', 'legacy-shared-migration-final.log', '"allOriginalMonthValuesAccountedFor": 30'),
]:
    assert marker in log_text(log)
    rows[file].update(status='PASS', exit_code=0, log=log,
                      fixture='synthetic nonempty data: 3 manufacturers / 30 month cells / 1 historical item')

platform = ROOT / 'apps/web-ui/scripts/test-platform.mjs'
files = re.findall(r"'((?:scripts/)test[^']+\.mjs)'", platform.read_text(encoding='utf-8'))
assert len(files) == 12
assert 'Web UI platform tests passed.' in log_text('ui-platform-final.log')
for file in files + ['scripts/test-platform.mjs', 'scripts/test-artifact-path.mjs']:
    path = 'apps/web-ui/' + file
    rows[path] = dict(file=path, status='PASS', exit_code=0,
                     log='ui-artifact-path.log' if file.endswith('test-artifact-path.mjs') else 'ui-platform-final.log')

inventory = set()
for folder, glob in [
    ('apps/api-server/tests', 'test*.py'), ('apps/api-server/verification', 'test*.py'),
    ('apps/api-server/scripts', 'test*.py'), ('apps/browser-runner', 'test*.mjs'),
    ('apps/web-ui/scripts', 'test*.mjs'), ('scripts', 'test*.py'), ('tools/ui-drift-guard', 'test*.py'),
]:
    inventory.update(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).glob(glob))
assert inventory == set(rows), {'not_run': sorted(inventory-set(rows)), 'unexpected': sorted(set(rows)-inventory)}
assert len(rows) == 66, len(rows)
for row in rows.values():
    assert row['status'] == 'PASS' and row['exit_code'] == 0, row
    assert not any(row.get(k, 0) for k in ('failures', 'errors', 'skipped')), row
    assert (HERE / row['log']).is_file(), row
    row['source_sha256'] = hashlib.sha256((ROOT / row['file']).read_bytes()).hexdigest()
    xml = row.get('evidence') or row['log'].removesuffix('.log') + '.xml'
    if row.get('tests') and (HERE / xml).exists():
        junit(xml)
        row['evidence'] = xml

summary = dict(files=len(rows), passed=len(rows), failed=0, skipped=0,
               python_test_cases=sum(x.get('tests', 0) for x in rows.values()))
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
changed = subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT, text=True).splitlines()
untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
source_paths = set(changed) | {name for name in untracked if name.startswith('apps/')} | {p.relative_to(ROOT).as_posix() for p in (ROOT / 'apps/api-server').rglob('test*.py') if '.venv' not in p.parts}
source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                 for name in sorted(source_paths) if (ROOT / name).is_file() and name.startswith('apps/')}
assert 'Maker update smoke passed:' in log_text('maker-smoke-final.log')
assert 'built in' in log_text('web-build-final.log')
output = dict(generated_at=datetime.now(timezone.utc).isoformat(), branch='ocr',
              base_commit='64c9fc9703cff8871f397c9e8d430766a66b22fb', head=head,
              tested_working_tree=True, summary=summary, results=sorted(rows.values(), key=lambda x:x['file']),
              changed_source_sha256=source_hashes,
              supplementary=[dict(file='apps/api-server/verification/maker_update_smoke.py', status='PASS', log='maker-smoke-final.log'),
                             dict(file='apps/web-ui/scripts/smoke-ui.mjs', status='PASS', log='apps__api-server__verification__test_worker_lifecycle.py.log')])
(HERE / 'final-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

report = f'''# Đợt 2 — Luồng lịch tự động, phục hồi queue và test

Đã hoàn thành phạm vi sửa code và kiểm tra cục bộ. **{summary['files']}/{summary['files']} file test PASS**, **{summary['python_test_cases']} test case Python PASS**, **0 FAIL, 0 SKIP**; hai smoke script bổ sung PASS và build UI PASS. Bảng theo từng file và log nằm cuối báo cáo; số test case chỉ đếm các bộ có JUnit, không cộng số assertion JavaScript hoặc các script kiểm tra trực tiếp.

Đầu đợt ở commit `64c9fc9` (audit Đợt 1 đã commit/push). Trong lúc làm xuất hiện hai commit UI `8a69713` và `f30b704`; HEAD cuối là `{head}` trên nhánh `ocr`. Đã chạy lại toàn bộ platform UI và build trên HEAD cuối cộng các thay đổi Đợt 2 trong working tree. Các thay đổi Đợt 2 hiện chưa commit/push. `final-results.json` lưu SHA256 nguồn test và nguồn thay đổi để nhận diện chính xác bản được kiểm tra. Các file và thư mục cá nhân ngoài phạm vi được giữ nguyên.

## Hành vi sản phẩm đã sửa

| Runner kết nối và còn heartbeat | Hành vi lịch kiểm chứng | Case đồng thời lớn nhất | Kết quả |
| --- | --- | ---: | --- |
| 0 | Chờ runner; không compile plan, không preflight, không áp pool và không giao job | 0 | PASS |
| 1 | Dù lịch cũ có `workerCount=9999`, dùng đúng 1 runner | 1 | 9 case duy nhất hoàn tất, PASS |
| 3 | Dù lịch cũ có `workerCount=9999`, dùng đúng 3 runner | 3 | 9 case duy nhất hoàn tất, PASS |

- `connected_workers()`, `sync_worker_capacity()`, `prepare_run()` và `dispatch_run()` trong [run_scheduler.py](../../apps/api-server/app/run_scheduler.py) lấy năng lực từ runner còn heartbeat. Preflight kiểm những runner thực tế được chọn, queue tự điều chỉnh khi kết nối thay đổi. Assignment cũ được drain/recover; không viết lại case hay ranh giới checkpoint khi giảm năng lực.
- `live_worker()` trong [worker_pool.py](../../apps/api-server/app/worker_pool.py) loại runner reconnecting và heartbeat quá hạn. `BatchQueueRepository.claim()` cùng `set_worker_limit()` trong [batch_queue.py](../../apps/api-server/app/repositories/batch_queue.py) giới hạn queue lịch bằng số runner còn hoạt động; không tin cờ SQL `connected=True` khi heartbeat đã hết hạn.
- [AutomaticRunSettings.tsx](../../apps/web-ui/src/components/AutomaticRunSettings.tsx), [api-client.ts](../../apps/web-ui/src/services/api-client.ts) và [run-schedules.ts](../../apps/web-ui/src/run-schedules.ts) bỏ điều khiển số worker khỏi cả create/resume. Test khẳng định form và card lịch không còn ô nhập số worker ở mọi trạng thái. Model [run_schedule.py](../../apps/api-server/app/models/run_schedule.py) nhận tương thích request cũ nhưng loại bỏ giá trị; repository không lưu count mới, không trả count cũ cho UI và bỏ count khi resume. Queue cũ được chuyển về năng lực tự động.
- `_settle()` trong [batch_queue.py](../../apps/api-server/app/repositories/batch_queue.py) khóa job trước khi quyết định lease hết hạn; kết quả đã commit thắng tình huống expiry cạnh tranh. `claim()` thống nhất thứ tự khóa job trước runner và đánh giá expiry trước trả assignment recovered.
- `_change()` trong [postgres.py](../../apps/api-server/app/repositories/postgres.py) chỉ release runner khi lần đầu chuyển sang terminal; ACK terminal gửi muộn không giữ khóa runner của case mới. `_expire_disconnected_runner()` trong [runner_events.py](../../apps/api-server/app/realtime/runner_events.py) không emit payload rỗng khi trạng thái đã được giao dịch kết quả chốt.

Code hiện tại dùng PostgreSQL task claims sau migration 0014. Ghi nhớ Redis của các đợt trước đã được đối chiếu lại và không dùng làm bằng chứng kiến trúc hiện tại.

## Kiểm chứng phục hồi và tính duy nhất

| Tình huống | Bằng chứng và kết quả |
| --- | --- |
| Worker cùng lấy việc | `test_queue_recovery.py`: 12 poll cạnh tranh từ 3 worker qua 27 case; 27 job và 27 lịch sử SQL, ACK trùng không tăng số dòng. PASS |
| Lease hết hạn, socket mất hoặc cờ connected còn true | Tạo attempt mới cho đúng case, filters và retryOf; kết quả NO_DATA muộn qua HTTP bị 409, workbook muộn bị từ chối; chỉ kết quả attempt mới vào lịch sử. PASS |
| Commit kết quả cạnh tranh expiry | Expiry chờ khóa job, đọc lại terminal đã commit, không tạo retry hoặc deadlock. PASS |
| ACK terminal cũ trong lúc runner bị khóa | ACK hoàn thành và runner vẫn giữ jobId case mới. PASS |
| API restart | Subprocess Uvicorn thật, readiness có DB migration head: 3 client Socket.IO/HTTP, kill process rồi restart, reconnect nhận đúng jobId cũ, duplicate result, pause/drain/resume, 9/9 case duy nhất và attempts=1. PASS |
| Pause/resume, đổi số runner thực tế | Bộ lịch 39/39; giữ sessionId/case/progress; tăng/giảm số runner không lấy lại count lưu cũ. PASS |
| Mất mạng | Queue không giao việc khi offline; case bị ngắt trở về pending không tăng failure; tự resume sau phục hồi; pause thủ công không bị auto resume. Network monitor yêu cầu hai probe khỏe. PASS |
| Tải và checkpoint | 1.600 case duy nhất, 10 worker, mỗi worker 160 claim; complete SQL và thứ tự checkpoint PASS trong 135,5 giây. Bộ retry/checkpoint 5/5 PASS. |
| UI smoke hiện hành | Browser đăng nhập, socket dùng token, runner source new/Playwright, nhận jobId và hiển thị tiến trình; hủy đúng job fixture sau kiểm tra. PASS trong lifecycle test. |

## Migration DB 0012 → 0014 lên và xuống

`verification/test_queue_migrations.py`: **2/2 PASS** trên PostgreSQL thật, gồm DB trống và DB có dữ liệu. Chạy `0012 → 0013 → 0014 → 0013 → 0012 → 0014` qua subprocess Alembic.

- 0013 tạo outbox cho đúng task PENDING/PROCESSING của session RUNNING; không enqueue session PAUSED hoặc task terminal. 0014 bỏ outbox; downgrade 0014 khôi phục đúng outbox.
- Giữ nguyên user, auth session, report session, filters/task state, attempts/failures, jobId/payload và settings cũ ở mỗi chiều.
- Khi hạ xuống 0012, cap 27 được clamp về 10 và constraint/default 10 được phục hồi đúng thiết kế cũ. Đây là thay đổi cap dự kiến, không mất case/job.
- Kiểm migration báo cáo cũ trên fixture **tổng hợp có dữ liệu**, 3 manufacturer/30 ô tháng/1 lịch sử: main migration giữ giá trị, ngày và nguồn; shared migration chuẩn hóa scope và filters, giữ dữ liệu; replay workbook không thêm dòng trùng hoặc bản sao SQL file. Không phải workbook sản xuất lịch sử. Log replay vẫn có nhãn `realCase` cũ của script; fixture được tạo tổng hợp.

## Phân biệt test lỗi thời, lỗi sản phẩm và môi trường

| Nhóm | Nguyên nhân và cách xử lý |
| --- | --- |
| Lỗi sản phẩm | Lịch áp `workerCount` cũ; lease bị giữ vô hạn bởi connected=true; race expiry/kết quả và thứ tự khóa job/runner; ACK terminal chạm runner case mới. Sửa code và thêm kiểm tra cạnh tranh, HTTP, restart và dữ liệu SQL. |
| Test lỗi thời | Filter `maxCases` không còn là giới hạn; UI year lấy từ profile; quyền member redirect khi load trang và deny khi hash navigation; schedule create/resume dùng runner tự động; smoke cần auth và runner engine hiện hành. Cập nhật assertion theo hành vi mới, vẫn kiểm SQL/UI/authorization. |
| Fixture thiếu hoặc sai | Mock preflight dùng mã PASS hết hạn sau 5 phút: tạo gate fresh mỗi lần check. Case dài thiếu heartbeat: fixture worker gửi heartbeat như runner thật. Test upload thiếu user khi chạy riêng: khai báo fixture admin trực tiếp, đã pass 8/8 trên DB hoàn toàn mới. Migration/workbook cũ thiếu fixture: tạo dữ liệu tổng hợp không rỗng và kiểm dữ liệu trước/sau. |
| Gián đoạn môi trường | Container test đầu tiên không còn tồn tại ở cuối lượt rộng; 3 worker-pool case báo ConnectionRefused, maker smoke chưa khởi chạy. Dựng container riêng mới; worker pool 7/7 và maker smoke PASS. Giữ log thất bại ban đầu trong `results.json`; kết quả chạy lại xác minh trong `final-results.json`. |

Không thêm skip/xfail hoặc giảm điều kiện kiểm để lấy bảng xanh. JUnit các lượt cuối có 0 failures/errors/skipped. Log cũ được giữ để đối chiếu, không dùng log một lượt FAIL làm kết quả cuối.

## Phạm vi môi trường và cách chạy lại

Windows/Python 3.12/Node 24, PostgreSQL 17 riêng trên localhost:55433, DB có hậu tố `_test`; migration phá schema chỉ cho DB guard `vahan_migration_*_test`. API lifecycle là process/HTTP/Socket.IO thật với worker protocol fixture. Platform UI dùng Chromium với fixture backend; network outage/probe được mô phỏng có kiểm SQL. Hai test live DOM tools kiểm VAHAN nhưng dừng trước CAPTCHA/Apply. Chưa thực hiện acceptance đầy đủ OCR/Apply với 1/3 browser VAHAN thật, và không coi build hoặc fixture là bằng chứng đó. Stack ứng dụng đang chạy không được restart/deploy trong đợt này. Sau khi các lượt cuối hoàn tất, đã dọn container test riêng `codex-round2-db-20261012`; API/web/3 runner/PostgreSQL của stack ứng dụng vẫn báo healthy khi kiểm tra cuối.

Đặt `DATABASE_URL` và cấu hình auth/runner cho PostgreSQL disposable, `VAHAN_ENVIRONMENT=test`, `VAHAN_ALLOW_DATABASE_CLEAR=test-only`; `VAHAN_RESULT_TEST_DATABASE` là tên DB tương ứng. Các verification có guard riêng đọc biến môi trường trong đầu file. Không chạy bằng URL DB sản xuất.

```powershell
# Từ apps/api-server, trên DB test đã migrate
.venv/Scripts/python.exe -m app.migrate
.venv/Scripts/python.exe -m pytest tests --tb=short
.venv/Scripts/python.exe -m pytest verification/test_run_schedules.py --tb=short
.venv/Scripts/python.exe -m pytest verification/test_queue_retry_checkpoints.py --tb=short
.venv/Scripts/python.exe -m pytest verification/test_worker_lifecycle.py --tb=short
# Migration dùng DB vahan_migration_*_test và VAHAN_QUEUE_MIGRATION_TEST_DATABASE
.venv/Scripts/python.exe -m pytest verification/test_queue_migrations.py --tb=short
# Các verification khác chạy từng file với DB fixture riêng như log command đã lưu

# Từ apps/web-ui
npm.cmd run test:platform
node scripts/test-artifact-path.mjs
npm.cmd run build
```

Để kiểm historical migration có dữ liệu, dùng `verification/prepare_report_test_fixtures.py` với PostgreSQL disposable và `VAHAN_FIXTURE_POSTGRES_CONTAINER` của container riêng. Script từ chối tên DB không phải test và DB fixture đã tồn tại. Các biến nguồn/đích cụ thể nằm ở guard đầu từng test và log setup.

## Kết quả cuối theo từng file

| File | Trạng thái | Test case Python | Log |
| --- | --- | ---: | --- |
'''
for row in output['results']:
    report += f"| `{row['file']}` | PASS | {row.get('tests', '—')} | [{row['log']}]({row['log']}) |\n"
report += '\nHai smoke bổ sung: [maker-smoke-final.log](maker-smoke-final.log), [worker lifecycle/UI smoke](apps__api-server__verification__test_worker_lifecycle.py.log). Build: [web-build-final.log](web-build-final.log). Kiểm tra độc lập upload: [cold-upload.log](cold-upload.log). Dữ liệu tổng hợp kết quả: [final-results.json](final-results.json); lịch sử lần chạy đầu: [results.json](results.json).\n'
(HERE / 'REPORT.md').write_text(report, encoding='utf-8')
print(json.dumps(summary))
