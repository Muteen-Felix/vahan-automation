import { persistentState } from './services/persistent-state';
import type { Scenario } from "./contracts";

export const MATRIX_STORAGE_KEY = "vahanStateRtoMatrixV1";
export const MIN_REPORT_YEAR = 1900;

export function isReportYear(year: number): boolean {
  return Number.isInteger(year) && year >= MIN_REPORT_YEAR && year <= currentReportYear();
}

export interface MatrixPlan {
  year: number;
  states: string[];
  scenarios: Scenario[];
  profileId?: string;
  profileRevision?: number;
  profileName?: string;
  skippedBranches?: number;
}

export function currentReportYear(): number {
  return new Date().getFullYear();
}

export function reportName(state: string, rto: string, year: number): string {
  return `Maker Month Wise Data  of ${rto} , ${state} (${year})`;
}

export function updateMatrixYear(plan: MatrixPlan, year: number): MatrixPlan {
  if (plan.year === year) return plan;
  return {
    ...plan,
    year,
    scenarios: plan.scenarios.map((scenario) => {
      const {filters} = scenario;
      const state = filters.states[0];
      const rto = filters.rtos[0];
      const suffix=scenario.caseKey&&scenario.name.includes(' · ')?` · ${scenario.name.split(' · ').slice(1).join(' · ')}`:'';
      return {...scenario, name: reportName(state, rto, year)+suffix, filters: {...filters, fromYear: String(year), toYear: String(year)} };
    }),
  };
}

export function readMatrixPlan(): MatrixPlan | null {
  try {
    const raw = persistentState.getItem(MATRIX_STORAGE_KEY);
    if (!raw) return null;
    const plan = JSON.parse(raw) as MatrixPlan;
    if (!Number.isInteger(plan.year) || !Array.isArray(plan.states) || !Array.isArray(plan.scenarios)) return null;
    if (!plan.states.length || !plan.scenarios.length) return null;
    if (!plan.scenarios.every((item) => item && typeof item.name === "string"
      && item.filters?.states?.length === 1 && item.filters?.rtos?.length === 1)) return null;
    return plan;
  } catch {
    return null;
  }
}
