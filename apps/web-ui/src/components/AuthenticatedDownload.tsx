import { useState, type CSSProperties, type ReactNode } from "react";

import { api } from "../services/api-client";

interface Props {
  path: string;
  fileName: string;
  className: string;
  children: ReactNode;
  style?: CSSProperties;
}

export function AuthenticatedDownload({ path, fileName, className, children, style }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function download() {
    setLoading(true);
    setError("");
    try {
      await api.downloadFile(path, fileName);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not download the file.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <span className="authenticated-download">
      <button
        className={className}
        style={style}
        type="button"
        onClick={() => void download()}
        disabled={loading}
      >
        {loading ? "Downloading…" : children}
      </button>
      {error && <small className="download-error" role="alert">{error}</small>}
    </span>
  );
}
