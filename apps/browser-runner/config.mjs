const LIST_FIELDS = new Set([
  "states", "rtos", "categoryGroups", "fuels", "archivedFlags",
  "financialYears", "emissions", "makers", "subCategories", "classes",
  "evTypes", "statuses", "ownerTypes",
]);

export function normalizeJobFilters(filters = {}) {
  return Object.fromEntries(Object.entries(filters).map(([key, value]) => {
    if (LIST_FIELDS.has(key) && Array.isArray(value)) {
      return [key, value.map((item) => String(item).trim()).filter(Boolean)];
    }
    return [key, value];
  }));
}

export const VAHAN_OPTION_SELECTORS = Object.freeze({
  archivedFlags: { selector: "#archivedFlags", multiple: true },
  period: { selector: "#reportType" },
  financialYears: { selector: "#financialYearSelect", multiple: true },
  reportYear: { selector: "#reportYear" },
  reportMonth: { selector: "#reportMonth" },
  states: { selector: "#stateName", multiple: true },
  rtos: { selector: "#rtoCode", multiple: true },
  emissions: { selector: "#vehicleEmission", multiple: true },
  categoryGroups: { selector: "#vehicleCategoryGroup", multiple: true },
  subCategories: { selector: "#vehicleSubCategory", multiple: true },
  classes: { selector: "#vehicleClass", multiple: true },
  fuels: { selector: "#vehicleFuel", multiple: true },
  evTypes: { selector: "#evType", multiple: true },
  statuses: { selector: "#vehicleStatus", multiple: true },
  ownerTypes: { selector: "#vehicleOwnerType", multiple: true },
  vehicleType: { selector: "#vehicleType" },
  fitness: { selector: "#fitnessCheck" },
  delhiNcr: { selector: "#delhiNcr" },
  yAxis: { selector: "#yAxis" },
  xAxis: { selector: "#xAxis" },
});
