import { useEffect, useState } from "react";
import { createRoot, deleteRoot, listRoots } from "../api/client.js";

export default function Consent() {
  const [roots, setRoots] = useState([]);
  const [newPath, setNewPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const data = await listRoots();
      setRoots(data.roots);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!newPath.trim()) return;
    try {
      await createRoot(newPath.trim());
      setNewPath("");
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    try {
      await deleteRoot(id);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section>
      <h2>Consent &amp; Index Roots</h2>
      <p className="hint">
        Folders LifeVault has permission to scan. S1 stub: additions/removals
        aren't persisted to disk yet -- this proves the round trip through
        the real API.
      </p>

      {error && <p className="error">Error: {error}</p>}

      <form className="row" onSubmit={handleAdd}>
        <input
          type="text"
          placeholder="/path/to/folder"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
        />
        <button type="submit">Grant access</button>
      </form>

      {loading ? (
        <p>Loading...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Path</th>
              <th>Enabled</th>
              <th>Paused</th>
              <th>Granted at</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {roots.map((root) => (
              <tr key={root.id}>
                <td>{root.path}</td>
                <td>{root.enabled ? "yes" : "no"}</td>
                <td>{root.paused ? "yes" : "no"}</td>
                <td>{root.granted_at ?? "--"}</td>
                <td>
                  <button onClick={() => handleDelete(root.id)}>Revoke</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
