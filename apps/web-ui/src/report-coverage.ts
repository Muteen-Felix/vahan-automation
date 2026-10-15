import type { MatrixPlan } from './matrix-plan';
import { updateMatrixYear } from './matrix-plan';
import { request } from './services/api-client';

export type CoverageContext = {year: number; dataset: string; state: string; rto: string};
export type ReportCoverageData = {
  year: number; datasetId: string; hasRun: boolean; matrixLoaded: boolean;
  total: number; processed: number; withData: number; noData: number; failed: number;
  pending: number; running: number; status: string; startedAt: string | null; lastActivityAt: string | null;
};
export function loadReportCoverage(context: CoverageContext, plan: MatrixPlan | null, signal?: AbortSignal) {
  return request<ReportCoverageData>('/api/annual-reports/coverage', {method: 'POST', signal,
    body: JSON.stringify({...context, scenarios: plan ? updateMatrixYear(plan, context.year).scenarios : []})});
}
