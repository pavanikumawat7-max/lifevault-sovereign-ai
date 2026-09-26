import { useEffect, useState } from "react";
import { listAudit, verifyAudit } from "../api/client.js";

export default function Audit() {
  const [entries, setEntries] = useState([]);
  const [verification, setVerification] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [auditResp, verifyResp] = await Promise.all([listAudit(), verifyAudit()]);
      setEntries(auditResp.entries);
      setVerification(verifyResp);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <section>
      <h2>Audit Log</h2>
      <p className="hint">
        The one part of S1 that's real end to end: an append-only,
        hash-chained log (see api/audit.py). Every row's hash depends on
        the previous row's hash, so tampering with any past row is
        detectable.
      </p>

      {error && <p className="error">Error: {error}</p>}

      {verification && (
        <div className={verification.valid ? "card ok" : "card error"}>
          <strong>Chain verification: {verification.valid ? "VALID" : "TAMPERED"}</strong>
          {!verification.valid && (
            <p>
              First bad row: #{verification.row_id} ({verification.reason})
            </p>
          )}
          <p>{verification.rows_checked} row(s) checked.</p>
        </div>
      )}

      <button onClick={refresh}>Refresh</button>

      {loading ? (
        <p>Loading...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Event</th>
              <th>Timestamp</th>
              <th>Row hash</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={4}>No audit events yet.</td>
              </tr>
            )}
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>{entry.id}</td>
                <td>{entry.event}</td>
                <td>{entry.ts}</td>
                <td className="mono">{entry.row_hash.slice(0, 12)}...</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
