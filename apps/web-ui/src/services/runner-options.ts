import type { Socket } from 'socket.io-client';

// Runner deadline: 110 s; API acknowledgement: 115 s; allow transport overhead.
export const RUNNER_OPTIONS_ACK_TIMEOUT_MS = 125_000;

export async function requestRunnerOptions(
  socket: Socket, runnerId: string, request: Record<string, unknown>,
  message: string, onProgress: (message: string) => void,
): Promise<unknown> {
  let lastError = 'VAHAN did not return options.';
  let busySince: number | null = null;
  let attempt = 1;
  while (attempt <= 3) {
    // Never buffer preparation commands to replay after a disconnected session.
    if (!socket.connected) throw new Error('Connection lost while loading VAHAN options. Reconnect and try again.');
    const started = Date.now();
    const updateProgress = () => onProgress(busySince !== null
      ? `Waiting for the browser worker… · ${Math.floor((Date.now() - busySince) / 1000)}s / 125s`
      : `${message} · attempt ${attempt}/3 · ${Math.floor((Date.now() - started) / 1000)}s / 125s`);
    updateProgress();
    const timer = setInterval(updateProgress, 1000);
    try {
      const response = await socket.volatile.timeout(RUNNER_OPTIONS_ACK_TIMEOUT_MS).emitWithAck('ui:runner-options', {
        runnerId, request,
      }) as { ok: boolean; error?: string; options?: unknown; code?: string; retryAfterMs?: number };
      if (response.ok && response.options != null) return response.options;
      lastError = response.error || lastError;
      if (response.code === 'RUNNER_BUSY' || /^(?:Browser )?Worker is busy\.?$/i.test(lastError)) {
        busySince ??= Date.now();
        const busyMs = Date.now() - busySince;
        if (busyMs >= RUNNER_OPTIONS_ACK_TIMEOUT_MS) {
          throw new Error('RUNNER_BUSY_TIMEOUT: the browser worker remained busy for 125 seconds. Wait for its current task to finish and try again.');
        }
        onProgress(`Waiting for the browser worker… · ${Math.floor(busyMs / 1000)}s / 125s`);
        // Busy means no options operation started. Keep the same attempt, rather
        // than exhaust all three attempts while the previous request cleans up.
        await new Promise(resolve => setTimeout(resolve, Math.min(5000, Math.max(1000, response.retryAfterMs || 1000))));
        continue;
      }
      busySince = null;
      if (/authentication|VAHAN_AUTH_REQUIRED|unsupported/i.test(lastError)) throw new Error(lastError);
    } catch (reason) {
      lastError = reason instanceof Error ? reason.message : String(reason);
      if (/authentication|VAHAN_AUTH_REQUIRED|unsupported|RUNNER_BUSY_TIMEOUT/i.test(lastError)) throw reason;
    } finally {
      clearInterval(timer);
    }
    if (attempt < 3) await new Promise(resolve => setTimeout(resolve, attempt * 1000));
    attempt += 1;
  }
  throw new Error(lastError);
}
