import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import type { Acknowledgement, Runner, VahanFilters } from "../contracts";
import { uiSocket } from "../services/socket-client";

interface Props {
  runners: Runner[];
  busy: boolean;
  onSubmit: (runnerId: string, filters: VahanFilters) => Promise<void>;
}

type OptionMap = Record<string, string[]>;
type FormState = Record<string, string | string[] | boolean>;

const initial: FormState = {
  archivedFlags: ["ACTIVE_COMPLIANT", "ACTIVE_NON_COMPLIANT", "PERMANENT_ARCHIVE", "TEMPORARY_ARCHIVE"],
  period: "CALENDAR YEAR", financialYears: [], reportYear: "", reportMonth: "",
  fromYear: "2025", toYear: "2025", fromDate: "", toDate: "", delhiNcr: "ALL STATES",
  states: ["Delhi"], rtos: ["DWARKA - DL9"], emissions: ["Not Applicable"], makers: [],
  categoryGroups: ["Two Wheeler"], subCategories: ["TWO WHEELER(NT)"],
  classes: ["M-Cycle/Scooter"], fuels: ["ELECTRIC(BOV)"], evTypes: ["ELECTRIC(BOV)"],
  statuses: ["ACTIVE"], ownerTypes: ["INDIVIDUAL"], vehicleType: "Non-Transport",
  fitness: "NO", yAxis: "Vehicle Class", xAxis: "Month Wise",
  autoApply: true, autoExport: true,
};

const matching = (options: string[], wanted: string) =>
  options.find((option) => option.trim().toLocaleLowerCase() === wanted.trim().toLocaleLowerCase()) || "";
const matchingMany = (options: string[], wanted: string[]) =>
  wanted.map((item) => matching(options, item)).filter(Boolean);

function optionErrorMessage(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : String(reason || "");
  if (/VAHAN_SESSION_EXPIRED|session timeout/i.test(message)) {
    return "The VAHAN session has expired. Reload the VAHAN tab in your browser to load the options.";
  }
  if (/VAHAN_UNREACHABLE|chrome-error|lỗi kết nối/i.test(message)) {
    return "Cannot reach VAHAN. Check your internet connection or try again later.";
  }
  if (/VAHAN_SERVER_ERROR|HTTP 5/i.test(message)) {
    return "VAHAN is experiencing an internal error. Wait a few minutes and try again.";
  }
  if (/operation has timed out|timed out|timeout/i.test(message)) {
    return "VAHAN is responding slowly. The system will retry loading options when the extension is ready.";
  }
  if (/Receiving end does not exist/i.test(message)) {
    return "Could not find the VAHAN page content. Make sure the tab is on the Public Report page.";
  }
  return message || "Could not load options from VAHAN.";
}

function DynamicSelect({ label, name, options, value, multiple = false, disabled = false, onChange }: {
  label: string; name: string; options: string[]; value: string | string[]; multiple?: boolean;
  disabled?: boolean; onChange: (name: string, value: string | string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const fieldRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!fieldRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  if (multiple) {
    const selected = value as string[];
    const visible = options.filter((option) => option.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
    const toggle = (option: string, checked: boolean) => onChange(name, checked
      ? [...new Set([...selected, option])]
      : selected.filter((item) => item !== option));
    return <div className="dynamic-multi-field" ref={fieldRef}>
      <span className="dynamic-field-label">{label}</span>
      <button className="multi-trigger" type="button" disabled={disabled} aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        <span>{selected.length ? `${selected.length} selected` : "--- Select ---"}</span><i>⌄</i>
      </button>
      {open && <div className="dynamic-multi-popover"><div className="dynamic-multi">
          <input type="search" autoFocus placeholder="Search..." value={search} disabled={disabled} onChange={(event) => setSearch(event.target.value)} />
          <label className="multi-select-all"><input type="checkbox" disabled={disabled || !visible.length}
            checked={Boolean(visible.length) && visible.every((item) => selected.includes(item))}
            onChange={(event) => onChange(name, event.target.checked
              ? [...new Set([...selected, ...visible])]
              : selected.filter((item) => !visible.includes(item)))} /> Select all</label>
          <div className="dynamic-option-list">{visible.map((option) =>
            <label key={option}><input type="checkbox" disabled={disabled} checked={selected.includes(option)}
              onChange={(event) => toggle(option, event.target.checked)} /> <span>{option}</span></label>)}</div>
        </div></div>}
    </div>;
  }
  return <label>{label}
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(name, event.currentTarget.value)}
    >
      <option value="">--- Select ---</option>
      {options.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>
  </label>;
}

export function FilterForm({ runners, busy, onSubmit }: Props) {
  const available = runners.filter((runner) => runner.status === "ONLINE" && !runner.currentJobId);
  const [runnerId, setRunnerId] = useState("");
  const [form, setForm] = useState<FormState>(initial);
  const [options, setOptions] = useState<OptionMap>({});
  const [makerOptions, setMakerOptions] = useState<string[]>([]);
  const [makerSearch, setMakerSearch] = useState("");
  const [makersLoading, setMakersLoading] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [optionError, setOptionError] = useState("");

  const selectedRunner = available.some((runner) => runner.id === runnerId)
    ? runnerId : available[0]?.id || "";

  async function runnerRequest(request: Record<string, unknown>) {
    if (!selectedRunner) throw new Error("No extension runner is available.");
    const response = await uiSocket.timeout(22_000).emitWithAck("ui:runner-options", {
      runnerId: selectedRunner, request,
    }) as Acknowledgement & { options?: OptionMap | string[] };
    if (!response.ok) throw new Error(response.error || "Could not load options from VAHAN.");
    return response;
  }

  useEffect(() => {
    if (!selectedRunner) return;
    let cancelled = false;
    setLoadingOptions(true);
    setOptionError("");
    runnerRequest({ type: "GET_ALL_OPTIONS" })
      .then(async (response) => {
        if (cancelled) return;
        const loaded = response.options as OptionMap;
        setOptions(loaded);
        setForm((current) => ({
          ...current,
          archivedFlags: matchingMany(loaded.archivedFlags || [], current.archivedFlags as string[]),
          period: matching(loaded.period || [], String(current.period)),
          financialYears: matchingMany(loaded.financialYears || [], current.financialYears as string[]),
          emissions: matchingMany(loaded.emissions || [], current.emissions as string[]),
          categoryGroups: matchingMany(loaded.categoryGroups || [], current.categoryGroups as string[]),
          subCategories: matchingMany(loaded.subCategories || [], current.subCategories as string[]),
          classes: matchingMany(loaded.classes || [], current.classes as string[]),
          fuels: matchingMany(loaded.fuels || [], current.fuels as string[]),
          evTypes: matchingMany(loaded.evTypes || [], current.evTypes as string[]),
          statuses: matchingMany(loaded.statuses || [], current.statuses as string[]),
          ownerTypes: matchingMany(loaded.ownerTypes || [], current.ownerTypes as string[]),
          delhiNcr: matching(loaded.delhiNcr || [], String(current.delhiNcr)),
          vehicleType: matching(loaded.vehicleType || [], String(current.vehicleType)),
          fitness: matching(loaded.fitness || [], String(current.fitness)),
          yAxis: matching(loaded.yAxis || [], String(current.yAxis)),
        }));
      })
      .catch((error) => !cancelled && setOptionError(error.message))
      .finally(() => !cancelled && setLoadingOptions(false));
    return () => { cancelled = true; };
  }, [selectedRunner]);

  useEffect(() => {
    if (!selectedRunner || !form.delhiNcr) return;
    runnerRequest({ type: "GET_STATE_OPTIONS", delhiNcr: form.delhiNcr })
      .then((response) => {
        const values = response.options as string[];
        setOptions((current) => ({ ...current, states: values, rtos: [] }));
        setForm((current) => ({ ...current, states: matchingMany(values, current.states as string[]) }));
      })
      .catch((error) => setOptionError(optionErrorMessage(error)));
  }, [selectedRunner, form.delhiNcr]);

  useEffect(() => {
    const states = form.states as string[];
    if (!selectedRunner || states.length !== 1) {
      setOptions((current) => ({ ...current, rtos: [] }));
      return;
    }
    runnerRequest({ type: "GET_RTO_OPTIONS", stateLabels: states.join(",") })
      .then((response) => {
        const values = response.options as string[];
        setOptions((current) => ({ ...current, rtos: values }));
        setForm((current) => ({ ...current, rtos: matchingMany(values, current.rtos as string[]) }));
      })
      .catch((error) => setOptionError(optionErrorMessage(error)));
  }, [selectedRunner, form.states]);

  useEffect(() => {
    if (!selectedRunner || !form.yAxis) return;
    runnerRequest({ type: "GET_X_AXIS_OPTIONS", yAxis: form.yAxis })
      .then((response) => {
        const values = response.options as string[];
        setOptions((current) => ({ ...current, xAxis: values }));
        setForm((current) => ({ ...current, xAxis: matching(values, String(current.xAxis)) }));
      })
      .catch((error) => setOptionError(optionErrorMessage(error)));
  }, [selectedRunner, form.yAxis]);

  useEffect(() => {
    const search = makerSearch.trim();
    if (!selectedRunner || search.length < 2) { setMakerOptions([]); setMakersLoading(false); return; }
    setMakersLoading(true);
    const timer = window.setTimeout(() => runnerRequest({ type: "SEARCH_MAKERS", search })
      .then((response) => setMakerOptions(response.options as string[]))
      .catch((error) => setOptionError(optionErrorMessage(error)))
      .finally(() => setMakersLoading(false)), 300);
    return () => window.clearTimeout(timer);
  }, [selectedRunner, makerSearch]);

  const change = (name: string, value: string | string[]) => {
    setForm((current) => ({ ...current, [name]: value }));
    if (name === "delhiNcr") setForm((current) => ({ ...current, states: [], rtos: [] }));
    if (name === "states") setForm((current) => ({ ...current, rtos: [] }));
    if (name === "yAxis") setForm((current) => ({ ...current, xAxis: "" }));
  };

  const select = useMemo(() => (name: string, label: string, multiple = false) =>
    <DynamicSelect label={label} name={name} options={options[name] || []} value={form[name] as string | string[]}
      multiple={multiple} disabled={loadingOptions || busy} onChange={change} />, [options, form, loadingOptions, busy]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedRunner) return;
    try {
      await onSubmit(selectedRunner, form as unknown as VahanFilters);
    } catch {
      // lỗi đã được hiển thị qua banner lỗi cấp App
    }
  }

  return <form className="panel filter-form" onSubmit={submit}>
    <div className="panel-heading"><span className="step-number">1</span><div>
      <h2>Report configuration</h2><p>Options are loaded directly from the VAHAN tab.</p>
    </div></div>

    <label>Extension runner<select value={selectedRunner} onChange={(event) => setRunnerId(event.target.value)} disabled={busy}>
      {!available.length && <option value="">No extension available</option>}
      {available.map((runner) => <option key={runner.id} value={runner.id}>{runner.name} · {runner.id}</option>)}
    </select></label>
    {loadingOptions && <p className="option-note">Loading options from VAHAN...</p>}
    {optionError && <p className="error-message">{optionError}</p>}

    <details className="filter-group" open><summary>Time &amp; region</summary><div className="form-grid">
      {select("archivedFlags", "Archive status", true)}
      {select("period", "Year type")}
      {select("financialYears", "Financial year", true)}
      {select("reportYear", "Report year")}
      {select("reportMonth", "Report month")}
      <label>From year<input value={String(form.fromYear)} onChange={(e) => change("fromYear", e.target.value)} /></label>
      <label>To year<input value={String(form.toYear)} onChange={(e) => change("toYear", e.target.value)} /></label>
      <label>From date<input value={String(form.fromDate)} onChange={(e) => change("fromDate", e.target.value)} /></label>
      <label>To date<input value={String(form.toDate)} onChange={(e) => change("toDate", e.target.value)} /></label>
      {select("delhiNcr", "Delhi NCR")}
      {select("states", "State / UT", true)}
      {select("rtos", "RTO", true)}
    </div></details>

    <details className="filter-group"><summary>Vehicle filters</summary><div className="form-grid">
      {select("emissions", "Emission standards", true)}
      <div className="maker-field"><span className="dynamic-field-label">Manufacturer</span><div className="maker-autocomplete">
        <div className="maker-chips">{(form.makers as string[]).map((maker) => <span className="maker-chip" key={maker}>{maker}
          <button type="button" title={`Remove ${maker}`} onClick={() => change("makers", (form.makers as string[]).filter((item) => item !== maker))}>×</button>
        </span>)}</div>
        <input type="search" value={makerSearch} placeholder="Enter at least 2 characters to search..." onChange={(e) => setMakerSearch(e.target.value)} />
        {(makersLoading || makerSearch.trim().length >= 2) && <div className="maker-results">
          {makersLoading && <p>Searching...</p>}
          {!makersLoading && !makerOptions.filter((item) => !(form.makers as string[]).includes(item)).length && <p>No results.</p>}
          {!makersLoading && makerOptions.filter((item) => !(form.makers as string[]).includes(item)).map((maker) =>
            <button type="button" key={maker} onClick={() => {
              change("makers", [...(form.makers as string[]), maker]); setMakerSearch(""); setMakerOptions([]);
            }}>{maker}</button>)}
        </div>}
      </div></div>
      {select("categoryGroups", "Vehicle categories", true)}
      {select("subCategories", "Subcategory", true)}
      {select("classes", "Vehicle class", true)}
      {select("fuels", "Fuel type", true)}
      {select("evTypes", "EV type", true)}
      {select("statuses", "Status", true)}
      {select("ownerTypes", "Owner type", true)}
      {select("vehicleType", "Transport type")}
      {select("fitness", "Valid fitness")}
    </div></details>

    <details className="filter-group" open><summary>Report axes</summary><div className="form-grid">
      {select("yAxis", "Y-axis")}{select("xAxis", "X-axis")}
    </div></details>

    <div className="checks">
      <label><input type="checkbox" checked={Boolean(form.autoApply)} onChange={(e) => setForm((c) => ({ ...c, autoApply: e.target.checked }))} /> Automatically click Apply after entering the CAPTCHA</label>
      <label><input type="checkbox" checked={Boolean(form.autoExport)} onChange={(e) => setForm((c) => ({ ...c, autoExport: e.target.checked }))} /> Automatically download Excel</label>
    </div>
    <button className="primary-button" disabled={busy || loadingOptions || !selectedRunner}>{busy ? "Creating job..." : "▶ Fill Filter"}</button>
  </form>;
}
