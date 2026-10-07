import { CaptchaPanel } from './CaptchaPanel';
import type { CaptchaChallenge } from '../contracts';

export interface CaptchaInboxItem {
  runnerId: string;
  workerLabel: string;
  office: string;
  challenge: CaptchaChallenge;
}

interface Props {
  items: CaptchaInboxItem[];
  selectedJobId: string | null;
  taskRunning: boolean;
  onSelect: (jobId: string) => void;
  submitting: boolean;
  refreshing: boolean;
  onSubmit: (value: string, challenge: CaptchaChallenge) => Promise<void>;
  onRefresh: (challenge: CaptchaChallenge) => Promise<void>;
}

export function CaptchaInbox({items, selectedJobId, taskRunning, onSelect, submitting, refreshing, onSubmit, onRefresh}: Props) {
  const selected = items.find((item) => item.challenge.jobId === selectedJobId) || items[0];
  return <section className="captcha-inbox" id="captcha-assistance" aria-labelledby="captcha-inbox-title">
    <div className="captcha-inbox-header">
      <div>
        <p className="worker-dashboard-eyebrow">{taskRunning ? 'LIVE ASSISTANCE' : 'TASK STATUS'}</p>
        <h2 id="captcha-inbox-title">CAPTCHA assistance</h2>
        <p>{items.length
          ? 'Choose a worker to inspect its current image. Enter the CAPTCHA manually on VAHAN when needed.'
          : taskRunning
            ? 'Task đang chạy. Hiện chưa có worker nào cần hỗ trợ CAPTCHA.'
            : 'Chưa có task nào đang chạy.'}</p>
      </div>
      <span className="captcha-inbox-count">{items.length
        ? `${items.length} ${items.length === 1 ? 'worker' : 'workers'} waiting`
        : taskRunning ? '0 workers waiting' : 'No active task'}</span>
    </div>
    {items.length > 0 && selected ? <div className="captcha-inbox-layout">
        <div className="captcha-inbox-workers" role="group" aria-label="Workers with CAPTCHA images">
          {items.map((item) => <button type="button" key={item.runnerId}
            id={'captcha-' + item.runnerId} aria-controls="captcha-inbox-preview"
            aria-pressed={item.challenge.jobId === selected.challenge.jobId}
            className="captcha-inbox-worker" onClick={() => onSelect(item.challenge.jobId)}>
            <span className="captcha-inbox-worker-dot" aria-hidden="true" />
            <span><strong>{item.workerLabel}</strong><small>{item.runnerId}</small></span>
            {item.challenge.invalid && <em>Retry</em>}
          </button>)}
        </div>
        <div className="captcha-inbox-preview" id="captcha-inbox-preview" role="region" aria-live="polite"
          aria-label={'CAPTCHA preview for ' + selected.workerLabel}>
          <div className="captcha-inbox-preview-heading">
            <div><strong>{selected.workerLabel}</strong><span>{selected.office}</span></div>
            <span>Current image</span>
          </div>
          <CaptchaPanel key={selected.challenge.jobId} challenge={selected.challenge}
            submitting={submitting} refreshing={refreshing}
            onSubmit={(value) => onSubmit(value, selected.challenge)}
            onRefresh={() => onRefresh(selected.challenge)} />
        </div>
      </div> : <div className="captcha-inbox-empty" role="status" aria-live="polite">
        <span className="captcha-inbox-empty-mark" data-running={taskRunning} aria-hidden="true" />
        <strong>{taskRunning ? 'Chưa có worker nào chờ CAPTCHA' : 'Chưa có task nào đang chạy'}</strong>
        <p>{taskRunning
          ? 'Khung hỗ trợ sẽ hiển thị yêu cầu tại đây khi worker cần nhập CAPTCHA.'
          : 'Khu vực hỗ trợ sẽ tiếp tục hiển thị tại đây khi bạn bắt đầu task.'}</p>
      </div>}
  </section>;
}
