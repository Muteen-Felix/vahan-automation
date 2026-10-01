// Retry the same captured workbook, without asking VAHAN to export it again.
// The API treats repeat uploads to one job as the same saved report.
export async function uploadCapturedReport({
  serverUrl, jobId, runnerId, token, blob, fileName, signal,
  fetchImpl = fetch, attempts = 3, timeoutMs = 15_000,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
}) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    signal?.throwIfAborted();
    const controller = new AbortController();
    const cancel = () => controller.abort(signal.reason);
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(() => controller.abort(new Error("Upload timed out.")), timeoutMs);
    let retryable = true;
    try {
      const body = new FormData();
      body.append("file", blob, fileName);
      const response = await fetchImpl(`${serverUrl.replace(/\/$/, "")}/api/jobs/${jobId}/upload-excel`, {
        method: "POST",
        headers: { "X-VAHAN-RUNNER-TOKEN": token, "X-VAHAN-RUNNER-ID": runnerId },
        body,
        signal: controller.signal,
      });
      retryable = response.status >= 500 || response.status === 408 || response.status === 429;
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${result.detail || "Backend could not save Excel."}`);
      retryable = true; // A lost/truncated success body can be safely requested again.
      if (!result.ok || !result.fileName || result.sizeBytes !== blob.size) {
        throw new Error("Backend did not confirm the captured workbook's filename and byte size.");
      }
      signal?.throwIfAborted();
      return result;
    } catch (error) {
      signal?.throwIfAborted();
      lastError = error;
      if (!retryable) break;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
    if (attempt < attempts - 1) await sleep(300 * (attempt + 1));
  }
  throw new Error(`EXCEL_UPLOAD_FAILED: ${lastError?.message || "Upload failed."} (${serverUrl})`);
}

export function matchesReportCapture(message, sender, pending) {
  return Boolean(pending && sender.tab?.id === pending.tabId
    && message.captureId === pending.captureId);
}

export function matchesJobPageResult(message, sender, job) {
  return Boolean(job && message.jobId === job.jobId && sender.tab?.id === job.tabId);
}
