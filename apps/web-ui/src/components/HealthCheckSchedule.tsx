import { useEffect, useState, type FormEvent } from "react";

import type { PendingUiHealthCheck, UiHealthCheckNowResponse, UiHealthSchedule } from "../contracts";
import { api } from "../services/api-client";

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

interface HealthCheckScheduleProps {
  pendingManualCheck?: PendingUiHealthCheck | null;
  onCheckRequested?: (request: UiHealthCheckNowResponse) => void;
}

export function HealthCheckSchedule({
  pendingManualCheck = null,
  onCheckRequested,
}: HealthCheckScheduleProps) {
  const [schedule, setSchedule] = useState<UiHealthSchedule | null>(null);
  const [days, setDays] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [checkingNow, setCheckingNow] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [admin, setAdmin] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void api.currentUser().then(user => { if (!cancelled) setAdmin(user.role === 'admin'); }).catch(() => {});
    api.uiHealthSchedule()
      .then((value) => {
        if (cancelled) return;
        setSchedule(value);
        setDays(String(value.intervalDays));
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the check schedule.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  async function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const intervalDays = Number(days.trim());
    if (!Number.isInteger(intervalDays) || intervalDays < 1 || intervalDays > 365) {
      setError("Enter a whole number of days from 1 to 365.");
      setNotice("");
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await api.updateUiHealthSchedule(intervalDays);
      setSchedule(updated);
      setDays(String(updated.intervalDays));
      setNotice(`Check schedule saved. It will run every ${updated.intervalDays} days.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the check schedule.");
    } finally {
      setSaving(false);
    }
  }

  async function runCheckNow() {
    setCheckingNow(true);
    setError("");
    setNotice("");
    try {
      const result = await api.runUiHealthCheckNow();
      onCheckRequested?.(result);
      setNotice(
        `A check was requested from ${result.runnerName}. Waiting for the result to update the statistics and history.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not request an immediate check.");
    } finally {
      setCheckingNow(false);
    }
  }

  return (
    <section className="panel health-schedule" id="health-check">
      <div className="panel-heading">
        <span className="step-number">0</span>
        <div>
          <h2>UI health check schedule</h2>
          <p>Check the official VAHAN page and save a log for review.</p>
        </div>
      </div>

      <form className="health-schedule-form" onSubmit={saveSchedule}>
        <label htmlFor="health-check-days">
          Check again after
          <span className="health-schedule-input-row">
            <input
              className="health-schedule-input"
              id="health-check-days"
              type="number"
              min="1"
              max="365"
              step="1"
              value={days}
              disabled={!admin || loading || saving || checkingNow || Boolean(pendingManualCheck)}
              onChange={(event) => setDays(event.currentTarget.value)}
              placeholder="3"
            />
            <span className="health-schedule-unit">days</span>
          </span>
        </label>
        <div className="health-schedule-actions">
          <button className="primary-button" type="submit" disabled={!admin || loading || saving || checkingNow}>
            {saving ? "Saving..." : "Save schedule"}
          </button>
          <button
            className="secondary-button health-check-now-button"
            type="button"
            onClick={runCheckNow}
            disabled={loading || saving || checkingNow || Boolean(pendingManualCheck)}
            title="Ask the browser worker to check the open official VAHAN tab"
          >
            {checkingNow ? "Requesting..." : "Check now"}
          </button>
        </div>
      </form>

      {notice && <p className="health-schedule-status success" role="status">{notice}</p>}
      {error && <p className="health-schedule-status error-message" role="alert">{error}</p>}
      {schedule && (
        <div className="health-schedule-meta">
          <span>Current interval: <strong>{schedule.intervalDays} days</strong></span>
          <span>Next scheduled check: <strong>{formatDate(schedule.nextCheckAt)}</strong></span>
        </div>
      )}
      <p className="security-note health-schedule-note">
        The browser worker will receive the updated schedule and reset its automatic check. Health checks
        open an isolated page at the official VAHAN URL. They only
        read the interface and never enter CAPTCHA or click Apply.
      </p>
    </section>
  );
}
