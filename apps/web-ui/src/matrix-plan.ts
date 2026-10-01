import type { Scenario, VahanFilters } from "./contracts";

export const MATRIX_STORAGE_KEY = "vahanStateRtoMatrixV1";

export interface MatrixPlan {
  year: number;
  states: string[];
  scenarios: Scenario[];
}

export function currentReportYear(): number {
  return new Date().getFullYear();
}

export function reportName(state: string, rto: string, year: number): string {
  return `Maker Month Wise Data  of ${rto} , ${state} (${year})`;
}

export function fixedFilters(state: string, rto: string, year: number): VahanFilters {
  return {
    states: [state],
    rtos: [rto],
    archivedFlags: ["ACTIVE_COMPLIANT", "ACTIVE_NON_COMPLIANT", "PERMANENT_ARCHIVE", "TEMPORARY_ARCHIVE"],
    period: "CALENDAR YEAR",
    financialYears: [],
    fromYear: String(year),
    toYear: String(year),
    fromDate: "",
    toDate: "",
    delhiNcr: "ALL STATES",
    emissions: [],
    makers: [],
    categoryGroups: ["Two Wheeler"],
    subCategories: ["TWO WHEELER (Invalid Carriage)", "TWO WHEELER(NT)", "TWO WHEELER(T)"],
    classes: [],
    fuels: ["ELECTRIC(BOV)", "PURE EV"],
    yAxis: "Maker",
    xAxis: "Month Wise",
    autoApply: true,
    autoExport: true,
  };
}

export function buildMatrix(states: string[], rtosByState: Record<string, string[]>, year: number): MatrixPlan {
  const scenarios = states.flatMap((state) => (rtosByState[state] || []).map((rto) => ({
    name: reportName(state, rto, year),
    filters: fixedFilters(state, rto, year),
  })));
  return { year, states, scenarios };
}

export function updateMatrixYear(plan: MatrixPlan, year: number): MatrixPlan {
  if (plan.year === year) return plan;
  return {
    ...plan,
    year,
    scenarios: plan.scenarios.map(({ filters }) => {
      const state = filters.states[0];
      const rto = filters.rtos[0];
      return { name: reportName(state, rto, year), filters: fixedFilters(state, rto, year) };
    }),
  };
}

export function readMatrixPlan(): MatrixPlan | null {
  try {
    const raw = localStorage.getItem(MATRIX_STORAGE_KEY);
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
