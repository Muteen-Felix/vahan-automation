import type { ConnectionState } from "../contracts";

interface Props {
  backend: ConnectionState;
  runners: number;
}

export function ConnectionBanner({ backend, runners }: Props) {
  const text = {
    connecting: "Connecting to the system…",
    connected: runners > 0 ? `${runners} report browser${runners === 1 ? "" : "s"} connected` : "System connected · No report browsers connected",
    disconnected: "Connection lost · Reconnecting…",
    error: "Could not connect to the system",
  }[backend];

  return (
    <div className="connection-banner" data-state={backend} title={text} aria-label={text}>
      <span className="connection-dot" />
      <span>{text}</span>
    </div>
  );
}
