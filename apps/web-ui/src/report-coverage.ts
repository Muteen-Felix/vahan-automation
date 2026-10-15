import type { MatrixPlan } from './matrix-plan';
import { updateMatrixYear } from './matrix-plan';
import { request } from './services/api-client';

export type CoverageContext = {year: number; dataset: string; state: string; rto: string};
type CoverageOffice = {index: number; state: string; rto: string; name: string};
export type ReportCoverageData = {
  year: number; datasetId: string; total: number; covered: number; missing: number;
  withData: number; noData: number; coveredThrough: number; missingIndices: number[];
  firstMissing: CoverageOffice | null; lastSaved: (CoverageOffice & {savedAt: string}) | null;
  canContinue: boolean; blockedReason: string; matrixLoaded: boolean;
};
export function loadReportCoverage(context: CoverageContext, plan: MatrixPlan | null, signal?: AbortSignal) {
  return request<ReportCoverageData>('/api/annual-reports/coverage', {method: 'POST', signal,
    body: JSON.stringify({...context, scenarios: plan ? updateMatrixYear(plan, context.year).scenarios : []})});
}
