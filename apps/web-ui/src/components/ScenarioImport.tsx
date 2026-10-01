import { useEffect, useRef, useState } from "react";

import type { Scenario, VahanFilters } from "../contracts";
import { AuthenticatedDownload } from "./AuthenticatedDownload";

interface BatchLogEntry {
  index: number;
  name: string;
  status: "ok" | "empty" | "error";
  detail: string;
  jobId?: string;
  excelFileName?: string | null;
}

interface Props {
  scenarios: Scenario[];
  fileName: string;
  onImport: (scenarios: Scenario[], fileName: string) => void;
  onRunAll: (scenarios: Scenario[]) => void;
  onRunFrom: (index: number) => void;
  onRunOne: (index: number) => void;
  onRetryFailed: () => void;
  onStop: () => void;
  running: boolean;
  progress: { done: number; total: number; current: string };
  batchStatus: "idle" | "running" | "completed" | "completed_with_errors" | "stopped" | "error";
  log: BatchLogEntry[];
  failedAtIndex: number | null;
  disabled: boolean;
}

const REQUIRED_ARRAY_FIELDS: (keyof VahanFilters)[] = ["categoryGroups", "fuels"];
const REQUIRED_STRING_FIELDS: (keyof VahanFilters)[] = ["yAxis", "xAxis"];
const FILTER_LABELS: [keyof VahanFilters, string][] = [
  ["states", "State / region"],
  ["rtos", "RTO"],
  ["categoryGroups", "Vehicle categories"],
  ["fuels", "Fuel types"],
  ["archivedFlags", "Archive status"],
  ["period", "Report period"],
  ["financialYears", "Financial years"],
  ["reportYear", "Report year"],
  ["reportMonth", "Report month"],
  ["fromYear", "From year"],
  ["toYear", "To year"],
  ["fromDate", "From date"],
  ["toDate", "To date"],
  ["delhiNcr", "Delhi NCR"],
  ["emissions", "Emission standards"],
  ["makers", "Manufacturers"],
  ["subCategories", "Subcategories"],
  ["classes", "Vehicle classes"],
  ["evTypes", "EV types"],
  ["statuses", "Vehicle status"],
  ["ownerTypes", "Owner types"],
  ["vehicleType", "Vehicle type"],
  ["fitness", "Fitness"],
  ["yAxis", "Y-axis"],
  ["xAxis", "X-axis"],
  ["autoApply", "Auto-apply"],
  ["autoExport", "Standalone auto-download"],
];

function formatFilterValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "None selected";
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (value === "" || value === null || value === undefined) return "Not set";
  return String(value);
}

function scenarioDisplayName(name: string, index: number): string {
  return name.replace(new RegExp(`^0*${index + 1}\\s*\\|\\s*`), "");
}

function parseScenarioFile(raw: string): Scenario[] {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error("The file is not valid JSON.");
  }
  if (!Array.isArray(data)) {
    throw new Error("The file must be a JSON array of scenarios: [{ \"name\": ..., \"filters\": {...} }, ...].");
  }

  return data.map((item, index) => {
    const label = `scenario #${index + 1}`;
    if (typeof item !== "object" || item === null) {
      throw new Error(`${label}: must be a JSON object.`);
    }
    const { name, filters } = item as Record<string, unknown>;
    if (typeof name !== "string" || !name.trim()) {
      throw new Error(`${label}: is missing the "name" field (string).`);
    }
    if (typeof filters !== "object" || filters === null) {
      throw new Error(`${label} ("${name}"): is missing the "filters" field (object).`);
    }
    const filterRecord = filters as Record<string, unknown>;
    for (const field of REQUIRED_ARRAY_FIELDS) {
      if (!Array.isArray(filterRecord[field])) {
        throw new Error(`${label} ("${name}"): filters.${field} must be an array (it may be empty).`);
      }
    }
    for (const field of REQUIRED_STRING_FIELDS) {
      if (typeof filterRecord[field] !== "string" || !(filterRecord[field] as string).trim()) {
        throw new Error(`${label} ("${name}"): filters.${field} must be a non-empty string.`);
      }
    }
    return { name, filters: filterRecord as unknown as VahanFilters };
  });
}

export function ScenarioImport({
  scenarios, fileName, onImport, onRunAll, onRunFrom, onRunOne, onRetryFailed, onStop, running, progress,
  batchStatus, log, failedAtIndex, disabled,
}: Props) {
  const [selectedStartIndex, setSelectedStartIndex] = useState(0);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (running && scenarios.length) {
      setSelectedStartIndex(Math.min(Math.max(progress.done, 0), scenarios.length - 1));
      return;
    }
    if (failedAtIndex === null || !scenarios.length) {
      setSelectedStartIndex(0);
      return;
    }
    setSelectedStartIndex(failedAtIndex + 1 < scenarios.length ? failedAtIndex + 1 : failedAtIndex);
  }, [failedAtIndex, progress.done, running, scenarios.length]);

  const errorCount = log.filter((entry) => entry.status === "error").length;
  const completedCount = log.filter((entry) => entry.status === "ok").length;
  const emptyCount = log.filter((entry) => entry.status === "empty").length;
  const progressPercent = progress.total ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0;

  async function handleFile(file: File) {
    setError("");
    try {
      const text = await file.text();
      const parsed = parseScenarioFile(text);
      onImport(parsed, file.name);
    } catch (reason) {
      onImport([], "");
      setError(reason instanceof Error ? reason.message : "Could not read the scenario file.");
    }
  }

  function clearScenarioFile() {
    setError("");
    onImport([], "");
  }

  return (
    <section className="panel scenario-import">
      <div className="scenario-heading">
        <div>
          <h2>JSON Scenarios</h2>
          <p>Import a file, review its filters, and run cases in sequence.</p>
        </div>
        {scenarios.length > 0 && !error && <span className="scenario-count">{scenarios.length} {scenarios.length === 1 ? "case" : "cases"}</span>}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="application/json,.json"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) handleFile(file);
          event.target.value = "";
        }}
        hidden
      />
      <div className="scenario-file-row">
        <button className="secondary-button scenario-file-button" type="button" disabled={running} onClick={() => inputRef.current?.click()}>
          {fileName ? "Replace JSON file" : "Choose JSON file"}
        </button>
        <div className="scenario-file-label">
          <strong>{fileName || "No file selected"}</strong>
          <span>{fileName && !error ? `${scenarios.length} ${scenarios.length === 1 ? "case" : "cases"} imported` : "JSON file must include name and filters"}</span>
        </div>
        {fileName && !running && !error && (
          <button className="scenario-clear-button" type="button" onClick={clearScenarioFile}>
            Remove file
          </button>
        )}
      </div>

      {error && <p className="error-message">{error}</p>}
      {!fileName && !error && <p className="scenario-empty-hint">Choose a JSON file to view its cases and run options.</p>}

      {scenarios.length > 0 && !error && (
        <>
          <div className="scenario-run-info" role="status">
            <div><strong>Using configuration from JSON</strong><span>Manual report settings are ignored.</span></div>
            <p>Sequential run <i /> Failed cases retry once in original order <i /> Every report is saved on the server</p>
          </div>

          <div className="scenario-list-heading">
            <h3>Cases</h3>
            <span>{scenarios.length} total</span>
          </div>
          <ol className="scenario-list">
            {scenarios.map((scenario, index) => {
              const result = log.find((entry) => entry.index === index);
              const filters = scenario.filters;
              return (
                <li key={`${scenario.name}-${index}`} data-status={result?.status || "pending"}>
                  <div className="scenario-case-heading">
                    <span className="scenario-index">{String(index + 1).padStart(2, "0")}</span>
                    <strong title={scenarioDisplayName(scenario.name, index)}>{scenarioDisplayName(scenario.name, index)}</strong>
                    {result && <span className={`scenario-result ${result.status}`}>{result.status === "ok" ? "Saved" : result.status === "empty" ? "No data" : "Failed"}</span>}
                  </div>
                  <details className="scenario-filter-details">
                    <summary>View filters</summary>
                    <dl>
                      {FILTER_LABELS.map(([key, label]) => (
                        <div key={key}><dt>{label}</dt><dd>{formatFilterValue(filters[key])}</dd></div>
                      ))}
                    </dl>
                  </details>
                </li>
              );
            })}
          </ol>

          <div className="scenario-actions">
            {running ? (
              <button className="secondary-button scenario-stop-button" type="button" onClick={onStop}>
                Stop after the current job
              </button>
            ) : (
              <button className="primary-button scenario-run-all" type="button" disabled={disabled} onClick={() => onRunAll(scenarios)}>
                Run all · {scenarios.length} {scenarios.length === 1 ? "case" : "cases"}
              </button>
            )}
            {!running && (
              <div className="scenario-start-row">
                <label>
                  Select case
                  <select value={selectedStartIndex} disabled={disabled} onChange={(event) => setSelectedStartIndex(Number(event.target.value))}>
                    {scenarios.map((scenario, index) => (
                      <option key={scenario.name + "-" + index} value={index}>
                        {String(index + 1).padStart(2, "0")} · {scenarioDisplayName(scenario.name, index)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="scenario-run-buttons">
                  <button className="secondary-button scenario-run-from" type="button" disabled={disabled} onClick={() => onRunFrom(selectedStartIndex)}>
                    Run from here
                  </button>
                  <button className="primary-button scenario-run-one" type="button" disabled={disabled} onClick={() => onRunOne(selectedStartIndex)}>
                    Run one case
                  </button>
                </div>
              </div>
            )}
            {!running && errorCount > 0 && failedAtIndex !== null && scenarios[failedAtIndex] && (
              <button className="retry-button scenario-retry" type="button" disabled={disabled} onClick={onRetryFailed}>
                Retry all {errorCount} failed {errorCount === 1 ? "case" : "cases"} in original order
              </button>
            )}
          </div>

          {(running || progress.total > 0) && (
            <div className="scenario-progress" role="status">
              <div className="scenario-progress-heading">
                <strong>
                  {running ? `Running ${Math.min(progress.done + 1, progress.total)}/${progress.total}`
                    : batchStatus === "completed" ? "Completed"
                      : batchStatus === "completed_with_errors" ? "Completed with errors"
                        : batchStatus === "stopped" ? "Stopped"
                          : batchStatus === "error" ? "Stopped due to an error" : "Ready to run"}
                </strong>
                <span>{Math.min(progress.done, progress.total)}/{progress.total}</span>
              </div>
              <div className="scenario-progress-track"><span style={{ width: `${progressPercent}%` }} /></div>
              <p>{running ? progress.current : batchStatus === "completed_with_errors"
                ? `${errorCount} failed case(s) were skipped.`
                : batchStatus === "stopped" ? `Processed through case ${Math.min(progress.done, progress.total)}/${progress.total}.`
                  : batchStatus === "error" ? `Processed through case ${Math.min(progress.done, progress.total)}/${progress.total}.`
                    : batchStatus === "completed" ? `Processed through case ${Math.min(progress.done, progress.total)}/${progress.total}.`
                      : `Ready to run ${progress.total} ${progress.total === 1 ? "case" : "cases"}.`}</p>
            </div>
          )}

          {log.length > 0 && (
            <details className="scenario-history">
              <summary><strong>Run results</strong><span>{completedCount} saved files · {emptyCount} no data · {errorCount} failed</span></summary>
              <ol className="scenario-list batch-log">
                {log.map((entry, index) => {
                  const icon = entry.status === "ok" ? "✓" : entry.status === "empty" ? "○" : "×";
                  return (
                    <li key={entry.index + "-" + index} data-status={entry.status}>
                      <strong>{icon} #{entry.index + 1} · {entry.name}</strong>
                      <span>{entry.detail}</span>
                      {entry.status === "ok" && entry.excelFileName && (
                        <div>
                          <AuthenticatedDownload
                            path={`/api/jobs/reports/file/${encodeURIComponent(entry.excelFileName)}`}
                            fileName={entry.excelFileName}
                            className="batch-excel-link"
                          >
                            Download Excel
                          </AuthenticatedDownload>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </details>
          )}
        </>
      )}
    </section>
  );
}
