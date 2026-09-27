import { useEffect, useRef, useState } from "react";
import { getIndexStatus, pauseIndex, resumeIndex } from "../api/client.js";

const POLL_MS = 4000;

const STATE_LABELS = {
  idle: "Idle",
  scanning: "Scanning folders",
  indexing: "Indexing documents",
  paused: "Paused",
  error: "Error",
};

export default function IndexStatus() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef(null);

  async function refresh() {
    try {
      const data = await getIndexStatus();
      setStatus(data.status);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    timerRef.current = setInterval(refresh, POLL_MS);
    return () => clearInterval(timerRef.current);
  }, []);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (status?.state === "paused") {
        await resumeIndex();
      } else {
        await pauseIndex();
      }
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const stateLabel = status ? STATE_LABELS[status.state] || status.state : "--";
  const cardClass = status?.state === "error" ? "card error" : status?.state === "paused" ? "card" : "card ok";

  return (
    <section>
      <h2>Indexing Status</h2>
      <p className="hint">
        Live status of the background worker that scans, parses and indexes
        your approved folders. Refreshes every {POLL_MS / 1000}s.
      </p>

      {error && <p className="error">Error: {error}</p>}

      {loading ? (
        <p>Loading...</p>
      ) : (
        <div className={cardClass}>
          <p>
            <strong>State:</strong> {stateLabel}
          </p>
          <p>
            <strong>Folders:</strong> {status.roots_total} total,{" "}
            {status.roots_paused} paused
          </p>
          <p>
            <strong>Documents indexed:</strong> {status.documents_indexed}
          </p>
          <p>
            <strong>Chunks indexed:</strong> {status.chunks_indexed}
          </p>
          <p>
            <strong>Last run:</strong> {status.last_run_at ?? "never"}
          </p>
          {status.message && (
            <p className="hint">
              <strong>Message:</strong> {status.message}
            </p>
          )}

          <div className="row">
            <button disabled={busy} onClick={toggle}>
              {status.state === "paused" ? "Resume indexing" : "Pause indexing"}
            </button>
            <button disabled={busy} onClick={refresh}>
              Refresh now
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
