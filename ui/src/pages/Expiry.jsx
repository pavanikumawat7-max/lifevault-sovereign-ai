import { useEffect, useState } from "react";
import { listFacts } from "../api/client.js";

export default function Expiry() {
  const [facts, setFacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listFacts()
      .then((data) => setFacts(data.facts))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section>
      <h2>Expiry &amp; Facts</h2>
      <p className="hint">
        S1 stub: real fact extraction (policy numbers, expiry dates, etc.)
        doesn't exist yet -- this page renders whatever GET /api/facts
        returns today, which is a single fixture fact.
      </p>

      {error && <p className="error">Error: {error}</p>}

      {loading ? (
        <p>Loading...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Value</th>
              <th>Source quote</th>
              <th>User corrected</th>
            </tr>
          </thead>
          <tbody>
            {facts.length === 0 && (
              <tr>
                <td colSpan={4}>No facts yet.</td>
              </tr>
            )}
            {facts.map((fact) => (
              <tr key={fact.id}>
                <td>{fact.field}</td>
                <td>{fact.value ?? "--"}</td>
                <td>{fact.source_quote ?? "--"}</td>
                <td>{fact.user_corrected ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
