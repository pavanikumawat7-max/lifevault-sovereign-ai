import { useCallback, useEffect, useMemo, useState } from "react";
import { listFacts, updateFact } from "../api/client.js";

/**
 * S8 expiry dashboard.
 *
 * Two views over GET /api/facts: what expires soon (the default 60-day window
 * the handover plan asks for) and every extracted fact.
 *
 * Values are editable inline. A PATCH sets `user_corrected`, which makes the
 * row immune to being overwritten by the next re-index -- so correcting a
 * misread date fixes it permanently, not until the next scan.
 */

const WINDOWS = [30, 60, 90, 365];

function daysUntil(iso) {
  if (!iso) return null;
  const then = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(then.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((then - today) / 86400000);
}

function ExpiryBadge({ iso }) {
  const days = daysUntil(iso);
  if (days == null) return null;
  if (days < 0) return <span className="pill pill--warn">expired {Math.abs(days)}d ago</span>;
  if (days <= 30) return <span className="pill pill--warn">in {days}d</span>;
  return <span className="pill pill--teal">in {days}d</span>;
}

function EditableValue({ fact, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(fact.value ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await updateFact(fact.id, { value, user_corrected: true });
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <span>
        {fact.value ?? "--"}{" "}
        <button className="link-button" onClick={() => setEditing(true)}>
          edit
        </button>
        {fact.user_corrected ? <span className="pill">corrected</span> : null}
      </span>
    );
  }

  return (
    <span className="row">
      <input value={value} onChange={(e) => setValue(e.target.value)} />
      <button onClick={save} disabled={busy}>
        {busy ? "Saving…" : "Save"}
      </button>
      <button
        className="link-button"
        onClick={() => {
          setValue(fact.value ?? "");
          setEditing(false);
        }}
      >
        cancel
      </button>
      {error && <span className="error">{error}</span>}
    </span>
  );
}

export default function Expiry() {
  const [window, setWindow] = useState(60);
  const [expiring, setExpiring] = useState([]);
  const [all, setAll] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [soon, everything] = await Promise.all([
        listFacts({ expiringWithin: window }),
        listFacts(),
      ]);
      setExpiring(soon.facts || []);
      setAll(everything.facts || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [window]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const byType = useMemo(() => {
    const counts = {};
    all.forEach((fact) => {
      counts[fact.type] = (counts[fact.type] || 0) + 1;
    });
    return counts;
  }, [all]);

  return (
    <section>
      <h2>Expiry &amp; Facts</h2>
      <p className="hint">
        Extracted from your own documents, each with the sentence it came from.
        Correct any value and it stays corrected through future re-indexing.
      </p>

      {error && <p className="error">Error: {error}</p>}

      <div className="row">
        <span className="hint">Expiring within</span>
        {WINDOWS.map((days) => (
          <button
            key={days}
            className={days === window ? "" : "link-button"}
            onClick={() => setWindow(days)}
          >
            {days === 365 ? "1 year" : `${days} days`}
          </button>
        ))}
        <button onClick={refresh} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {expiring.length === 0 ? (
        <div className="card">
          <p>Nothing expiring within {window} days.</p>
          <p className="hint">
            {all.length === 0
              ? "No facts extracted yet — index a folder on the Consent page first."
              : `${all.length} fact(s) extracted, none with an expiry date in this window.`}
          </p>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Document</th>
              <th>Expires</th>
              <th>When</th>
              <th>Source quote</th>
            </tr>
          </thead>
          <tbody>
            {expiring.map((fact) => (
              <tr key={fact.id}>
                <td>{fact.document_title ?? "--"}</td>
                <td>
                  <EditableValue fact={fact} onSaved={refresh} />
                </td>
                <td>
                  <ExpiryBadge iso={fact.norm_value} />
                </td>
                <td className="hint">{fact.source_quote ?? "--"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>All extracted facts</h3>
      <p className="hint">
        {Object.entries(byType)
          .map(([type, count]) => `${count} ${type}`)
          .join(" · ") || "none yet"}
      </p>
      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th>Field</th>
            <th>Value</th>
            <th>Normalized</th>
            <th>Document</th>
            <th>Source quote</th>
          </tr>
        </thead>
        <tbody>
          {all.length === 0 && (
            <tr>
              <td colSpan={6}>No facts yet.</td>
            </tr>
          )}
          {all.map((fact) => (
            <tr key={fact.id}>
              <td>{fact.type}</td>
              <td>{fact.label ?? fact.field}</td>
              <td>
                <EditableValue fact={fact} onSaved={refresh} />
              </td>
              <td className="mono">{fact.norm_value ?? "--"}</td>
              <td>{fact.document_title ?? "--"}</td>
              <td className="hint">{fact.source_quote ?? "--"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
