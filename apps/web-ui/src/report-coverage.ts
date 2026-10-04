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
export type CoverageControls = {
  plan: MatrixPlan | null; busy: boolean; running: boolean; loadingMatrix: boolean;
  status: string; current: string;
  onContinue: (context: CoverageContext) => Promise<void>;
  onStop: () => void;
};
export function loadReportCoverage(context: CoverageContext, plan: MatrixPlan | null, signal?: AbortSignal) {
  return request<ReportCoverageData>('/api/annual-reports/coverage', {method: 'POST', signal,
    body: JSON.stringify({...context, scenarios: plan ? updateMatrixYear(plan, context.year).scenarios : []})});
}

export function uncoveredScenarios(plan: MatrixPlan, coverage: ReportCoverageData) {
  if (!coverage.canContinue) throw new Error(coverage.blockedReason || 'This report cannot be continued.');
  const indices = coverage.missingIndices;
  if (new Set(indices).size !== indices.length || indices.some(index => !Number.isInteger(index) || !plan.scenarios[index])) {
    throw new Error('The office list changed. Refresh coverage before continuing.');
  }
  return {indices, scenarios: indices.map(index => plan.scenarios[index])};
}
