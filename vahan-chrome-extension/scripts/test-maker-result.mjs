import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../content.js", import.meta.url), "utf8");
const start = source.indexOf("const NO_RECORD_TEXT =");
const end = source.indexOf("const findVisiblePageMessages =", start);
assert.ok(start >= 0 && end > start, "Maker result detector must be present");
const detector = source.slice(start, end);

function element(textContent = "") {
  return {
    textContent,
    getClientRects: () => [1],
    getAttribute: () => null,
    closest: () => null,
  };
}

function classify(headings, rows) {
  const table = Object.assign(element(), {
    textContent: [...headings, ...rows.flat()].join(" "),
    querySelectorAll(selector) {
      if (selector.includes("thead")) return headings.map(element);
      if (selector === "tbody tr") return rows.map((values) => Object.assign(element(values.join(" ")), {
        querySelectorAll: () => values.map(element),
      }));
      return [];
    },
  });
  const excelButton = element("Download All Records Excel");
  const region = { querySelectorAll: (selector) => selector === "table" ? [table] : [excelButton] };
  const context = {
    document: {
      querySelector: () => region,
      querySelectorAll: () => [excelButton],
    },
    window: { getComputedStyle: () => ({ display: "block", visibility: "visible", opacity: "1" }) },
  };
  return runInNewContext(`${detector}\nreadMakerReportResult().type`, context);
}

assert.equal(classify(["Maker", "2026-Jan", "Total"], [
  ["ATHER ENERGY LTD", "38", "487"],
  ["Page Total", "170", "1854"],
]), "DATA");
assert.equal(classify(["Maker", "2026-Jan"], [
  ["BAJAJ AUTO LTD", "—"],
]), "DATA", "a real Maker row must not depend on strict numeric formatting");
assert.equal(classify(["Maker"], [["No record found"]]), "NO_RECORD");
assert.equal(classify(["Maker", "2026-Jan"], [["Page Total", "0"]]), null);
console.log("Maker report result fixtures passed.");

// Exercise the asynchronous watcher against a changed table belonging to
// another RTO, an active Apply, and a no-record response replaced by data.
const watcherStart = source.indexOf("function waitForVahanResult(");
const watcherEnd = source.indexOf("async function resumeServerJobAfterApply(", watcherStart);
const watcher = source.slice(watcherStart, watcherEnd);
function watcherHarness(type = "DATA") {
  let report = { type, table: {}, fingerprint: "new table" };
  let regionText = "RTO (Amalapuram RTA - AP205)";
  let pending = false;
  let observer;
  const callbacks = new Set();
  const context = {
    window: { setTimeout, clearTimeout }, queueMicrotask,
    MutationObserver: class {
      constructor(callback) { observer = callback; }
      observe() {} disconnect() {}
    },
    document: { documentElement: {} },
    chrome: { storage: { onChanged: {
      addListener: (callback) => callbacks.add(callback),
      removeListener: (callback) => callbacks.delete(callback),
    } } },
    compactText: (value) => String(value).replace(/\s+/g, " ").trim(),
    INVALID_CAPTCHA_TEXT: /invalid captcha/i, NO_RECORD_CONFIRMATION_MS: 30,
    isVisible: () => true, findVisiblePageMessages: () => [],
    readMakerReportResult: () => report,
    getResultRegion: () => ({ textContent: regionText }),
    isApplyPending: () => pending, isResultLoading: () => pending,
    findExcelDownloadButton: () => ({}), isUsableExcelButton: () => true,
    mutationCanChangeResult: () => true, getActiveVahanAuthHold: async () => null,
  };
  const wait = runInNewContext(`${watcher}\nwaitForVahanResult`, context);
  return {
    wait: () => wait(200, { invalidCaptchaNodes: new Set(), resultTable: {}, resultFingerprint: "old table", regionFingerprint: "old region" }, "Adoni RTO - AP221"),
    update(rto, isPending, nextType = "DATA") {
      regionText = `RTO (${rto})`; pending = isPending;
      report = { type: nextType, table: {}, fingerprint: "changed" };
      observer([{ target: {} }]);
    }, callbacks,
  };
}
const harness = watcherHarness();
let resolved = false;
const detected = harness.wait().then((result) => { resolved = true; return result; });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(!resolved, "changed data for the previous RTO must not complete the current case");
harness.update("Adoni RTO - AP221", true);
await new Promise((resolve) => setTimeout(resolve, 0));
assert.ok(!resolved, "active Apply must finish before data is exported");
harness.update("Adoni RTO - AP221", false);
assert.equal((await detected).type, "DOWNLOAD_READY");
assert.equal(harness.callbacks.size, 0);

const noRecordHarness = watcherHarness("NO_RECORD");
const replaced = noRecordHarness.wait();
noRecordHarness.update("Adoni RTO - AP221", false, "NO_RECORD");
await new Promise((resolve) => setTimeout(resolve, 5));
noRecordHarness.update("Adoni RTO - AP221", false, "DATA");
assert.equal((await replaced).type, "DOWNLOAD_READY", "data arriving during confirmation must win over no-record");
console.log("Maker watcher rejects stale RTO/active Apply and prioritizes fresh data.");
