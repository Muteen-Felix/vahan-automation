import { useEffect, useRef, useState } from 'react';
import { formatRunErrors, groupRunErrors, type RunErrorEntry } from '../run-error-log';

export function CopyRunErrors({entries}: {entries: RunErrorEntry[]}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const groups = groupRunErrors(entries);
  useEffect(() => () => clearTimeout(timer.current), []);
  async function copy() {
    setCopied(false); setError(''); clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(formatRunErrors(entries));
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 2500);
    } catch {
      setError('Could not copy errors. Allow clipboard access and try again.');
    }
  }
  return <div className="run-error-copy">
    <button type="button" className="secondary-button" disabled={!groups.length} onClick={() => void copy()}
      aria-label={copied ? 'Errors copied' : `Copy ${groups.length} unique run errors`}>
      {copied ? 'Copied' : `Copy errors (${groups.length})`}
    </button>
    <span className="sr-only" role="status">{copied ? 'Errors copied to clipboard.' : ''}</span>
    {error && <p role="alert">{error}</p>}
  </div>;
}
