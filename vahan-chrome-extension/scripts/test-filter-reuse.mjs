import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../content.js", import.meta.url), "utf8");
let changes = 0;
let waits = 0;
const select = {
  multiple: true,
  options: [
    { value: "AP221", label: "Adoni RTO - AP221", selected: true },
    { value: "AP205", label: "Amalapuram RTA - AP205", selected: false },
  ],
  get selectedOptions() { return this.options.filter((option) => option.selected); },
  dispatchEvent() { changes += 1; },
};
const start = source.indexOf("async function selectLabels(");
const end = source.indexOf("async function clearSelect(", start);
const selectLabels = runInNewContext(`${source.slice(start, end)}\nselectLabels`, {
  splitValues: (value) => value ? value.split(",").map((label) => label.trim()) : [],
  normalize: (value) => value.trim().toLowerCase(),
  getOptionMap: (element) => element.options.map((option) => ({ label: option.label.toLowerCase(), value: option.value })),
  document: { querySelector: () => select },
  Event: class {}, delay: async () => { waits += 1; },
});
assert.equal(await selectLabels("#rtoCode", "Adoni RTO - AP221"), false);
assert.equal(changes, 0);
assert.equal(waits, 0, "unchanged filters must not incur a widget delay");
assert.equal(await selectLabels("#rtoCode", "Amalapuram RTA - AP205"), true);
assert.equal(changes, 1);
assert.deepEqual(select.selectedOptions.map((option) => option.value), ["AP205"]);
await assert.rejects(selectLabels("#rtoCode", "Missing office - AP999"), /could not find/);
select.dispatchEvent = () => { select.options.forEach((option) => { option.selected = false; }); };
await assert.rejects(selectLabels("#rtoCode", "Adoni RTO - AP221"), /did not apply/);
console.log("Filter reuse avoids redundant changes and rejects missing/reset selections.");
