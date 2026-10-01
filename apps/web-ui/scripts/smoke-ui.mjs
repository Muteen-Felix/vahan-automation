import { io } from "socket.io-client";

const apiUrl = process.env.VITE_API_URL || "http://127.0.0.1:8000";
const runnerId = `web-ui-smoke-${Date.now()}`;
const runner = io(`${apiUrl}/runner`, {
  transports: ["websocket"],
  auth: {
    runnerId,
    runnerName: "Web UI Smoke Runner",
    token: process.env.VAHAN_API_RUNNER_TOKEN || "change-me",
    version: "0.1.0",
  },
  reconnection: false,
});
const ui = io(`${apiUrl}/ui`, { transports: ["websocket"], reconnection: false });

const event = (socket, name) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${name}`)), 5_000);
  socket.once(name, (payload) => {
    clearTimeout(timer);
    resolve(payload);
  });
});

try {
  await Promise.all([event(runner, "connect"), event(ui, "connect")]);
  const assignedPromise = event(runner, "job:assigned");
  const response = await fetch(`${apiUrl}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      runnerId,
      filters: {
        states: ["Delhi"],
        categoryGroups: ["Two Wheeler"],
        fuels: ["ELECTRIC(BOV)"],
        yAxis: "Vehicle Class",
        xAxis: "Month Wise",
        autoApply: true,
        autoExport: true,
      },
    }),
  });
  if (!response.ok) throw new Error(`Create job failed (${response.status})`);
  const job = await response.json();
  const assigned = await assignedPromise;
  if (assigned.jobId !== job.id) throw new Error("Runner received the wrong job.");

  const subscription = await ui.timeout(3_000).emitWithAck("ui:subscribe-job", { jobId: job.id });
  if (!subscription?.ok) throw new Error(subscription?.error || "Job subscription failed.");

  for (const nextStatus of ["OPENING_VAHAN", "CAPTURING_CAPTCHA"]) {
    const statusPromise = event(ui, "job:status");
    const acknowledgement = await runner.timeout(3_000).emitWithAck("job:status", {
      jobId: job.id,
      status: nextStatus,
    });
    if (!acknowledgement?.ok) throw new Error(acknowledgement?.error || "Status update failed.");
    const status = await statusPromise;
    if (status.status !== nextStatus) throw new Error("Web UI received the wrong status.");
  }

  console.log(`Web UI flow verified for job: ${job.id}`);
} finally {
  ui.disconnect();
  runner.disconnect();
}
