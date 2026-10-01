import assert from "node:assert/strict";
import { uploadCapturedReport, matchesReportCapture, matchesJobPageResult } from "../src/report-upload.mjs";

const blob = new Blob(["workbook bytes"], { type: "application/octet-stream" });
const options = {
  serverUrl: "http://127.0.0.1:8000", jobId: "job-1", runnerId: "runner-1",
  token: "test-token", blob, fileName: "Adoni.xlsx", sleep: async () => {},
};
const success = () => Response.json({ ok: true, fileName: "Adoni.xlsx", sizeBytes: blob.size });
let calls = 0;
const result = await uploadCapturedReport({ ...options, fetchImpl: async (url, init) => {
  calls += 1;
  assert.equal(url, "http://127.0.0.1:8000/api/jobs/job-1/upload-excel");
  assert.equal(await init.body.get("file").text(), "workbook bytes");
  if (calls === 1) throw new TypeError("Failed to fetch");
  if (calls === 2) return Response.json({ detail: "Temporary failure" }, { status: 503 });
  return success();
} });
assert.equal(result.fileName, "Adoni.xlsx");
assert.equal(calls, 3, "network/5xx retries must reuse the captured workbook");

calls = 0;
await assert.rejects(uploadCapturedReport({ ...options, fetchImpl: async () => {
  calls += 1;
  return Response.json({ detail: "Damaged workbook" }, { status: 400 });
} }), /EXCEL_UPLOAD_FAILED: HTTP 400: Damaged workbook/);
assert.equal(calls, 1, "invalid workbooks must not be retried");

calls = 0;
await assert.rejects(uploadCapturedReport({ ...options, fetchImpl: async () => {
  calls += 1;
  return Response.json({ ok: true, fileName: "Adoni.xlsx", sizeBytes: 1 });
} }), /byte size/);
assert.equal(calls, 3);

const cancelled = new AbortController();
calls = 0;
await assert.rejects(uploadCapturedReport({ ...options, signal: cancelled.signal, fetchImpl: async () => {
  calls += 1;
  cancelled.abort(new Error("Job cancelled"));
  throw new TypeError("Failed to fetch");
} }), /Job cancelled/);
assert.equal(calls, 1, "cancellation must stop upload retries immediately");

await assert.rejects(uploadCapturedReport({ ...options, timeoutMs: 5, attempts: 1,
  fetchImpl: (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(init.signal.reason));
  }),
}), /Upload timed out/);

const pending = { tabId: 7, captureId: "capture-current" };
assert.ok(matchesReportCapture({ captureId: "capture-current" }, { tab: { id: 7 } }, pending));
assert.ok(!matchesReportCapture({ captureId: "capture-previous" }, { tab: { id: 7 } }, pending));
assert.ok(!matchesReportCapture({ captureId: "capture-current" }, { tab: { id: 8 } }, pending));
assert.ok(!matchesReportCapture({ captureId: "capture-current" }, {}, pending));
assert.ok(matchesJobPageResult({ jobId: "job-current" }, { tab: { id: 7 } }, { tabId: 7, jobId: "job-current" }));
assert.ok(!matchesJobPageResult({ jobId: "job-old", result: "NO_RECORD" }, { tab: { id: 7 } }, { tabId: 7, jobId: "job-current" }),
  "a delayed no-data result must not be attached to the next filter in the same tab");
console.log("Excel upload retries, validation, cancellation and capture association passed.");
