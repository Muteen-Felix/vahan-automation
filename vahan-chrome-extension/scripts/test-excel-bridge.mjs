import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../interceptor-main.js", import.meta.url), "utf8");
const listeners = new Map();
const captures = [];
const revoked = [];
let nativeDownloads = 0;
let nextUrl = 0;
const window = {
  setTimeout: (callback, ms) => { const timer = setTimeout(callback, ms); if (ms >= 120000) timer.unref(); return timer; },
  addEventListener(name, callback) { listeners.set(name, callback); },
  dispatchEvent(event) { listeners.get(event.type)?.(event); },
};
class Anchor {
  constructor(href) { this.href = href; }
  hasAttribute(name) { return name === "download"; }
  getAttribute(name) { return name === "href" ? this.href : "report.xlsx"; }
  click() { nativeDownloads += 1; }
}
class FileReader {
  readAsDataURL(blob) {
    // Delayed delivery reproduces the page revoking the URL immediately.
    blob.arrayBuffer().then((bytes) => {
      this.result = `data:application/octet-stream;base64,${Buffer.from(bytes).toString("base64")}`;
      this.onload();
    });
  }
}
class CustomEvent {
  constructor(type, options) { this.type = type; this.detail = options.detail; }
}
const pageUrlApi = {
  createObjectURL: () => `blob:https://analytics.parivahan.gov.in/${++nextUrl}`,
  revokeObjectURL: (url) => revoked.push(url),
};
runInNewContext(source, {
  window, document: { addEventListener() {} }, HTMLAnchorElement: Anchor,
  URL: pageUrlApi, Blob, FileReader, CustomEvent,
  fetch: () => { throw new Error("Captured blob must not be fetched again"); },
  setTimeout: (callback, ms) => { const timer = setTimeout(callback, ms); timer.unref(); return timer; },
});
window.addEventListener("__VAHAN_EXCEL_EXPORT__", (event) => captures.push(event.detail));

const unmanagedUrl = pageUrlApi.createObjectURL(new Blob(["manual workbook"]));
new Anchor(unmanagedUrl).click();
assert.equal(nativeDownloads, 1, "manual downloads must keep their native path");

window.dispatchEvent(new CustomEvent("__VAHAN_EXCEL_CAPTURE_REQUEST__", { detail: { captureId: "job-a-capture" } }));
const href = pageUrlApi.createObjectURL(new Blob(["exact workbook bytes"]));
new Anchor(href).click();
pageUrlApi.revokeObjectURL(href);
assert.ok(!revoked.includes(href), "revoke must wait until the workbook bytes are copied");
window.dispatchEvent(new CustomEvent("__VAHAN_EXCEL_CAPTURE_REQUEST__", { detail: { captureId: "job-b-capture" } }));
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(nativeDownloads, 1, "server reports must suppress the duplicate native download");
assert.equal(captures.length, 1);
assert.equal(captures[0].captureId, "job-a-capture", "a late old export must retain its old capture identity");
assert.equal(Buffer.from(captures[0].dataUrl.split(",")[1], "base64").toString(), "exact workbook bytes");
assert.ok(revoked.includes(href));

window.dispatchEvent(new CustomEvent("__VAHAN_EXCEL_CAPTURE_REQUEST__", { detail: { captureId: null } }));
new Anchor(unmanagedUrl).click();
assert.equal(nativeDownloads, 2);
console.log("Excel bridge preserves exact bytes across immediate revocation and late delivery.");
