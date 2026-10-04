export type ConnectionState = "connecting" | "connected" | "disconnected" | "error";

export type RunnerStatus = "ONLINE" | "BUSY" | "RECONNECTING";

export interface Runner {
  id: string;
  name: string;
  source: "new" | "old";
  version?: string | null;
  status: RunnerStatus;
  currentJobId?: string | null;
  lastSeenAt: string;
}

export interface UiHealthSchedule {
  intervalDays: number;
  updatedAt: string;
  nextCheckAt: string;
}

export interface UiHealthCheckNowResponse {
  ok: boolean;
  requestId: string;
  runnerId: string;
  runnerName: string;
  requestedAt: string;
  status: "REQUESTED";
}

export interface PendingUiHealthCheck {
  requestId: string;
  requestedAt: string;
}

export interface UiHealthDaySummary {
  date: string;
  total: number;
  pass: number;
  dataChanged: number;
  dataChangedErrors: number;
  uiDrift: number;
  uiDriftErrors: number;
  checkError: number;
  latestCheckedAt: string;
}

export interface UiHealthReportFile {
  fileName: string;
  fromDate: string;
  toDate: string;
  part: number;
  rowCount: number;
  sizeBytes: number;
  updatedAt: string;
  containsSelectedDate: boolean;
  downloadUrl: string;
}

export interface UiHealthReportsResponse {
  selectedDate: string | null;
  availableDates: UiHealthDaySummary[];
  reports: UiHealthReportFile[];
  rows: Array<Record<string, string>>;
}

export type JobStatus =
  | "QUEUED"
  | "ASSIGNED"
  | "OPENING_VAHAN"
  | "CAPTURING_CAPTCHA"
  | "FILLING_FILTERS"
  | "WAITING_CAPTCHA"
  | "SUBMITTING"
  | "WAITING_RESULT"
  | "COMPLETED"
  | "NO_DATA"
  | "FAILED"
  | "CANCELLED";

export interface VahanFilters {
  states: string[];
  rtos: string[];
  categoryGroups: string[];
  fuels: string[];
  archivedFlags?: string[];
  period?: string;
  financialYears?: string[];
  reportYear?: string;
  reportMonth?: string;
  fromYear?: string;
  toYear?: string;
  fromDate?: string;
  toDate?: string;
  delhiNcr?: string;
  emissions?: string[];
  makers?: string[];
  subCategories?: string[];
  classes?: string[];
  evTypes?: string[];
  statuses?: string[];
  ownerTypes?: string[];
  vehicleType?: string;
  fitness?: string;
  yAxis: string;
  xAxis: string;
  autoApply: boolean;
  autoExport: boolean;
}

export interface Scenario {
  name: string;
  filters: VahanFilters;
}

export type ReportSource = "new" | "old";

export interface Job {
  id: string;
  runnerId: string;
  sessionId: string;
  retryOfJobId?: string | null;
  caseId?: string | null;
  status: JobStatus;
  filters: VahanFilters & Record<string, unknown>;
  scenarioName?: string | null;
  source?: ReportSource;
  captchaId?: string | null;
  error?: string | null;
  excelFileName?: string | null;
  noDataFileName?: string | null;
  excelFileSize?: number | null;
  mainReportSavedAt?: string | null;
  mainReportSummary?: {parsedRows: number; newRows: number; newCells: number; duplicates: number; conflicts: number} | null;
  resultMessage?: string | null;
  resultObservedAt?: string | null;
  reportTableCount?: number | null;
  reportRowCount?: number | null;
  successfulApplyCount?: number;
  createdAt: string;
  updatedAt: string;
}

export interface ExportedReportItem {
  jobId: string;
  scenarioName: string;
  fileName: string;
  fileSize: number;
  createdAt: string;
  sessionFolder?: string;
  downloadUrl: string;
  source?: ReportSource;
}

export interface ExportedReportJob {
  jobId: string;
  scenarioName: string;
  state: string;
  rto: string;
  source: ReportSource;
  status: JobStatus;
  error?: string | null;
  filters: Record<string, unknown>;
  fileName?: string | null;
  fileType?: "excel" | "text" | null;
  fileSize: number;
  filePath?: string | null;
  createdAt: string;
  updatedAt: string;
  downloadUrl?: string | null;
}

export interface ExportedReportSession {
  sessionId: string;
  deletedAt?: string | null;
  sessionFolder?: string | null;
  startedAt: string;
  updatedAt: string;
  jobCount: number;
  completedCount: number;
  noDataCount: number;
  failedCount: number;
  cancelledCount: number;
  activeCount: number;
  fileCount: number;
  totalFileSize: number;
  sources: ReportSource[];
  jobs: ExportedReportJob[];
}

export interface CaptchaChallenge {
  jobId: string;
  captchaId: string;
  imageDataUrl: string;
  invalid?: boolean;
  refreshed?: boolean;
}

export interface Acknowledgement {
  ok: boolean;
  error?: string;
  job?: Job;
  captcha?: CaptchaChallenge;
}
