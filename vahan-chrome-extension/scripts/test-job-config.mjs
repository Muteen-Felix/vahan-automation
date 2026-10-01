import assert from "node:assert/strict";
import { normalizeJobFilters } from "../src/job-config.mjs";

assert.deepEqual(normalizeJobFilters({
  states: [" Delhi ", ""],
  categoryGroups: ["Two Wheeler"],
  yAxis: "Vehicle Class",
  autoApply: true,
}), {
  states: "Delhi",
  categoryGroups: "Two Wheeler",
  yAxis: "Vehicle Class",
  autoApply: true,
});

console.log("Job filter normalization passed.");
