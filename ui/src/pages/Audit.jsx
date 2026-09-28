import { Fragment, useEffect, useState } from "react";
import { listAudit, verifyAudit } from "../api/client.js";

/**
 * S8 audit viewer.
 *
 * Rows expand to show the proposal, the edit diff, the decision and the hash
 * links, because the whole point of a hash chain is being able to look at it.
 * The Verify button calls GET /api/audit/verify, which walks every row and
 * recomputes the chain.
 */

const EVENT_LABELS = {
  chat_turn: "Question answered",
  action_proposed: "Action proposed",
  action_decided: "Decision recorded",
  action_executed: "Action executed",
  action_policy_denied: "Blocked by policy",
};

function EditDiff({ diff }) {
  const keys = Object.keys(diff || {});
  if (keys.length === 0) return null;
  return (
    <div className="audit-diff">
      <strong>Edit diff</strong>
      <ul>
        {keys.map((key) => (
          <li key={key} className="mono">
            {key}: <span className="diff-from">{String(diff[key].from)}</span> →{" "}
            <span className="diff-to">{String(diff[key].to)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Detail({ entry }) {
  const payload = entry.payload || {};
  return (
    <div className="audit-detail">
      {payload.question && (
        <p>
          <strong>Question</strong> {payload.question}
        </p>
      )}
      {payload.tool && (
        <p>
          <strong>Tool</strong> <span className="mono">{payload.tool}</span>
          {payload.tier && <span className="pill pill--teal">{payload.tier}</span>}
        </p>
      )}
      {payload.parameters && (
        <pre className="mono audit-json">{JSON.stringify(payload.parameters, null, 2)}</pre>
      )}
      {payload.rationale && (
        <p>
          <strong>Rationale</strong> {payload.rationale}
        </p>
      )}
      {payload.decision && (
        <p>
          <strong>Decision</strong>{" "}
          <span className={payload.decision === "approved" ? "pill pill--teal" : "pill"}>
            {payload.decision}
          </span>
          {payload.note ? ` — “${payload.note}”` : ""}
        </p>
      )}
      <EditDiff diff={payload.edit_diff} />
      {payload.policy && (
        <p>
          <strong>Policy</strong> {payload.policy.decision}
          {(payload.policy.reasons || []).length > 0 && ` — ${payload.policy.reasons.join("; ")}`}
        </p>
      )}
      {(payload.untrusted_fields || []).length > 0 && (
        <p>
          <strong>Untrusted values</strong>{" "}
          <span className="pill pill--warn">{payload.untrusted_fields.join(", ")}</span>
        </p>
      )}
      {payload.output && (
        <pre className="mono audit-json">{JSON.stringify(payload.output, null, 2)}</pre>
      )}
      {(payload.citations || []).length > 0 && (
        <p>
          <strong>Evidence</strong>{" "}
          {payload.citations.map((c, i) => (
            <span key={i} className="mono">
              {(c.path || "").split("/").pop()}
              {c.page != null ? `:${c.page}` : ""}{" "}
            </span>
          ))}
        </p>
      )}
      {(payload.evidence_document_hashes || []).length > 0 && (
        <p className="hint mono">
          hashes: {payload.evidence_document_hashes.map((h) => h.slice(0, 10)).join(", ")}
        </p>
      )}
      <p className="hint mono">
        prev {entry.prev_hash.slice(0, 16)}… → row {entry.row_hash.slice(0, 16)}…
      </p>
    </div>
  );
}

export default function Audit() {
  const [entries, setEntries] = useState([]);
  const [verification, setVerification] = useState(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());

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

  async function runVerify() {
    setVerifying(true);
    try {
      setVerification(await verifyAudit());
    } catch (err) {
      setError(err.message);
    } finally {
      setVerifying(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function toggle(id) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section>
      <h2>Audit Log</h2>
      <p className="hint">
        Append-only and hash-chained: every row&rsquo;s hash includes the
        previous row&rsquo;s, so altering any past entry breaks the chain and
        Verify will say so.
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

      <div className="row">
        <button onClick={runVerify} disabled={verifying}>
          {verifying ? "Verifying…" : "Verify chain"}
        </button>
        <button onClick={refresh} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {loading ? (
        <p>Loading…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Event</th>
              <th>Timestamp</th>
              <th>Row hash</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={5}>
                  No audit events yet. Ask a question on the Chat page.
                </td>
              </tr>
            )}
            {entries.map((entry) => (
              <Fragment key={entry.id}>
                <tr>
                  <td>{entry.id}</td>
                  <td>{EVENT_LABELS[entry.event] ?? entry.event}</td>
                  <td>{entry.ts.slice(0, 19).replace("T", " ")}</td>
                  <td className="mono">{entry.row_hash.slice(0, 12)}…</td>
                  <td>
                    <button className="link-button" onClick={() => toggle(entry.id)}>
                      {expanded.has(entry.id) ? "Hide" : "Details"}
                    </button>
                  </td>
                </tr>
                {expanded.has(entry.id) && (
                  <tr>
                    <td colSpan={5}>
                      <Detail entry={entry} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
