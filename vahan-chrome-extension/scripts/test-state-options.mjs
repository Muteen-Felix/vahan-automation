import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../content.js", import.meta.url), "utf8");
const start = source.indexOf("async function waitForOptions(");
const end = source.indexOf("async function refreshXAxisOptions(", start);
assert.ok(start >= 0 && end > start, "State option wait functions must be present");

let available = ["Delhi", "Haryana", "Rajasthan", "Uttar Pradesh"];
const observers = new Set();
class MutationObserverStub {
  constructor(callback) { this.callback = callback; }
  observe() { observers.add(this); }
  disconnect() { observers.delete(this); }
}
const context = {
  window: { setTimeout, clearTimeout },
  document: {
    documentElement: {},
    querySelector: (selector) => selector === "#stateName"
      ? { options: available.map((label) => ({ label, value: label })) }
      : null,
  },
  MutationObserver: MutationObserverStub,
  normalize: (value) => String(value).trim().toLowerCase(),
  getOptionMap: (select) => select.options.map((option) => ({ label: option.label.toLowerCase() })),
};
const waitForOptions = runInNewContext(
  `${source.slice(start, end)}\nwaitForOptions`,
  context,
);

const pending = waitForOptions("#stateName", ["Assam"], 500);
setTimeout(() => {
  available = ["Assam", "Andaman & Nicobar Island", "Andhra Pradesh"];
  for (const observer of observers) observer.callback();
}, 20);
await pending;
assert.equal(observers.size, 0, "Observer should be released after options arrive");

await assert.rejects(
  waitForOptions("#stateName", ["Arunachal Pradesh"], 30),
  /#stateName: dynamic options did not load within 30 ms/,
);
assert.equal(observers.size, 0, "Observer should be released after timeout");
console.log("State option refresh wait passed.");
