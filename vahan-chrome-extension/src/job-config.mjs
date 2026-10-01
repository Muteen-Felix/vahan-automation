const LIST_FIELDS = new Set([
  "states", "rtos", "categoryGroups", "fuels", "archivedFlags",
  "financialYears", "emissions", "makers", "subCategories", "classes",
  "evTypes", "statuses", "ownerTypes",
]);

export function normalizeJobFilters(filters = {}) {
  return Object.fromEntries(Object.entries(filters).map(([key, value]) => {
    if (LIST_FIELDS.has(key) && Array.isArray(value)) {
      return [key, value.map((item) => String(item).trim()).filter(Boolean).join(",")];
    }
    return [key, value];
  }));
}
