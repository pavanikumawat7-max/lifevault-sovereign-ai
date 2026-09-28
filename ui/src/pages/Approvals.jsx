import { useCallback, useEffect, useMemo, useState } from "react";
import { decideApproval, getMemory, listProposals } from "../api/client.js";

/**
 * S8 approval card.
 *
 * Kept deliberately plain: this is the screen judges look at longest, so it
 * shows the tool, every parameter as an editable field, the rationale, the
 * evidence it cites, a tier badge, and a precedent chip when memory has seen
 * this kind of action before.
 *
 * Two things here are load-bearing rather than decorative:
 *  - Parameters are editable, and "Edit & approve" sends only what actually
 *    changed. The API re-validates every edit through policy, so a bad value
 *    comes back as an error rather than being executed.
 *  - Values the API flagged as untrusted (they came out of document text and
 *    look like injected instructions) are highlighted. A person should never
 *    approve one of those without reading it.
 */

function fieldLabel(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function ParamField({ name, value, flagged, onChange }) {
  const isLong = typeof value === "string" && (value.length > 60 || name === "body");
  const asText = Array.isArray(value) ? value.join(", ") : (value ?? "");
  return (
    <label className={flagged ? "param param--flagged" : "param"}>
      <span className="param-name">
        {fieldLabel(name)}
        {flagged && (
          <span className="pill pill--warn" title="This value came from document text and looks like an instruction. Read it before approving.">
            untrusted
          </span>
        )}
      </span>
      {isLong ? (
        <textarea rows={4} value={asText} onChange={(e) => onChange(name, e.target.value)} />
      ) : (
        <input type="text" value={asText} onChange={(e) => onChange(name, e.target.value)} />
      )}
    </label>
  );
}

function ProposalCard({ proposal, precedent, onDecided }) {
  const [params, setParams] = useState(proposal.parameters || {});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState(null);

  const flagged = useMemo(
    () => new Set(proposal.untrusted_fields || []),
    [proposal.untrusted_fields],
  );

  const changed = useMemo(() => {
    const original = proposal.parameters || {};
    const diff = {};
    Object.keys(params).forEach((key) => {
      if (String(params[key] ?? "") !== String(original[key] ?? "")) {
        diff[key] = params[key];
      }
    });
    return diff;
  }, [params, proposal.parameters]);

  const hasEdits = Object.keys(changed).length > 0;

  function updateParam(name, value) {
    setParams((current) => ({ ...current, [name]: value }));
  }

  async function decide(decision) {
    setBusy(decision);
    setError(null);
    try {
      const response = await decideApproval(
        proposal.id,
        decision,
        note || null,
        decision === "edit" ? changed : null,
      );
      setOutcome(response);
      onDecided();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  if (outcome) {
    const wrote = outcome.result?.output?.vault_relative_path;
    return (
      <div className={outcome.executed ? "card ok" : "card"}>
        <p>
          <strong>{outcome.proposal.status === "executed" ? "Executed" : "Recorded"}</strong>{" "}
          &mdash; {proposal.tool}
        </p>
        {wrote && (
          <p className="hint">
            Wrote <code className="mono">{wrote}</code> inside your vault. Your
            original documents were not touched.
          </p>
        )}
        {outcome.edit_diff && Object.keys(outcome.edit_diff).length > 0 && (
          <p className="hint">
            Edited:{" "}
            {Object.entries(outcome.edit_diff).map(([key, change]) => (
              <span key={key} className="mono">
                {key}: {String(change.from)} → {String(change.to)}{" "}
              </span>
            ))}
          </p>
        )}
        {outcome.message && <p className="error">{outcome.message}</p>}
      </div>
    );
  }

  return (
    <div className="card approval-card">
      <div className="approval-head">
        <div>
          <span className="approval-tool mono">{proposal.tool}</span>
          {proposal.tier && <span className="pill pill--teal">{proposal.tier}</span>}
        </div>
        {precedent && (
          <span className="pill" title={`Last time: ${precedent}`}>
            Because you {precedent} this before
          </span>
        )}
      </div>

      {proposal.rationale && <p className="approval-rationale">{proposal.rationale}</p>}

      <div className="param-grid">
        {Object.keys(proposal.parameters || {}).map((name) => (
          <ParamField
            key={name}
            name={name}
            value={params[name]}
            flagged={flagged.has(name)}
            onChange={updateParam}
          />
        ))}
      </div>

      {(proposal.evidence_document_hashes || []).length > 0 && (
        <p className="hint">
          Evidence:{" "}
          {proposal.evidence_document_hashes.map((hash) => (
            <a key={hash} className="mono" href={`/api/documents/${hash}`} title={hash}>
              {hash.slice(0, 10)}…{" "}
            </a>
          ))}
        </p>
      )}

      {error && <p className="error">{error}</p>}

      <textarea
        placeholder="Optional note (recorded in the audit log)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      <div className="row">
        <button disabled={busy !== null || hasEdits} onClick={() => decide("approve")}>
          {busy === "approve" ? "Approving…" : "Approve"}
        </button>
        <button disabled={busy !== null || !hasEdits} onClick={() => decide("edit")}>
          {busy === "edit" ? "Saving…" : "Edit & approve"}
        </button>
        <button disabled={busy !== null} onClick={() => decide("reject")}>
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
      </div>
      {hasEdits && (
        <p className="hint">
          You changed {Object.keys(changed).join(", ")} &mdash; use
          &ldquo;Edit &amp; approve&rdquo; to run the edited version.
        </p>
      )}
    </div>
  );
}

export default function Approvals() {
  const [proposals, setProposals] = useState([]);
  const [memory, setMemory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [queue, memoryResp] = await Promise.all([listProposals("pending"), getMemory()]);
      setProposals(queue.proposals || []);
      setMemory(memoryResp.entries || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function precedentFor(tool) {
    const entry = memory.find((m) => m.key === `tool:${tool}`);
    if (!entry?.last_decision) return null;
    return entry.last_decision === "approved" ? "approved" : "rejected";
  }

  return (
    <section>
      <h2>Approvals</h2>
      <p className="hint">
        Nothing runs until you approve it. Edit any field before approving, and
        every decision is written to the audit log.
      </p>

      {error && <p className="error">Error: {error}</p>}

      <div className="row">
        <button onClick={refresh} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {!loading && proposals.length === 0 && (
        <div className="card">
          <p>No proposals waiting.</p>
          <p className="hint">
            Ask a question on the Chat page about something with an expiry date
            &mdash; for example &ldquo;When does my Dell laptop warranty
            expire?&rdquo; &mdash; and a reminder will be proposed here.
          </p>
        </div>
      )}

      {proposals.map((proposal) => (
        <ProposalCard
          key={proposal.id}
          proposal={proposal}
          precedent={precedentFor(proposal.tool)}
          onDecided={refresh}
        />
      ))}

      <h3>Memory</h3>
      <p className="hint">
        The last decision LifeVault recorded for each action, and the defaults
        it learned from your edits.
      </p>
      {memory.length === 0 ? (
        <p className="hint">Nothing remembered yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Last decision</th>
              <th>Learned defaults</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {memory.map((entry) => (
              <tr key={entry.key}>
                <td className="mono">{entry.key.replace(/^tool:/, "")}</td>
                <td>
                  <span
                    className={
                      entry.last_decision === "approved" ? "pill pill--teal" : "pill"
                    }
                  >
                    {entry.last_decision ?? "--"}
                  </span>
                </td>
                <td className="mono">
                  {entry.context?.lead_days != null
                    ? `${entry.context.lead_days} days before expiry`
                    : "--"}
                </td>
                <td>{entry.updated_at?.slice(0, 19).replace("T", " ") ?? "--"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
