import { io } from "socket.io-client";

const serverUrl = process.env.VAHAN_API_URL || "http://127.0.0.1:8000";
const runnerId = `runner-smoke-${Date.now()}`;
const socket = io(`${serverUrl}/runner`, {
  transports: ["websocket"],
  auth: {
    runnerId,
    runnerName: "Socket.IO Smoke Test",
    token: process.env.VAHAN_API_RUNNER_TOKEN || "change-me",
    version: "0.1.0",
  },
  timeout: 5_000,
  reconnection: false,
});

const timeout = setTimeout(() => {
  console.error("Timed out while connecting to the backend.");
  socket.disconnect();
  process.exitCode = 1;
}, 8_000);

socket.on("connect_error", (error) => {
  clearTimeout(timeout);
  console.error(`Connection failed: ${error.message}`);
  socket.disconnect();
  process.exitCode = 1;
});

socket.on("connect", async () => {
  try {
    const heartbeat = await socket.timeout(3_000).emitWithAck("runner:heartbeat", {
      timestamp: Date.now(),
    });
    if (!heartbeat?.ok) throw new Error(heartbeat?.error || "Heartbeat was rejected.");

    const response = await fetch(`${serverUrl}/api/runners`);
    const runners = await response.json();
    if (!runners.some((runner) => runner.id === runnerId && runner.status === "ONLINE")) {
      throw new Error("Connected runner was not present in /api/runners.");
    }
    console.log(`Socket.IO runner connected and registered: ${runnerId}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  } finally {
    clearTimeout(timeout);
    socket.disconnect();
  }
});
