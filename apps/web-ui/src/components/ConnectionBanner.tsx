import type { ConnectionState } from "../contracts";

interface Props {
  backend: ConnectionState;
  runners: number;
}

export function ConnectionBanner({ backend, runners }: Props) {
  const text = {
    connecting: "Connecting to backend...",
    connected: runners > 0 ? `${runners} extension runner${runners === 1 ? "" : "s"} online` : "Backend connected · No extension runner online",
    disconnected: "Backend disconnected",
    error: "Could not connect to backend",
  }[backend];

  return (
    <div className="connection-banner" data-state={backend}>
      <span className="connection-dot" />
      <span>{text}</span>
    </div>
  );
}
