import { useEffect, useState } from "react";
import {
  createRoot,
  deleteRoot,
  getIndexStatus,
  listRoots,
  pauseIndex,
  resumeIndex,
} from "../api/client.js";

export default function Consent() {
  const [roots, setRoots] = useState([]);
  const [newPath, setNewPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [indexPaused, setIndexPaused] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [rootsData, statusData] = await Promise.all([listRoots(), getIndexStatus()]);
      setRoots(rootsData.roots);
      setIndexPaused(statusData.status.state === "paused");
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

  async function toggleIndexing() {
    setBusy(true);
    setError(null);
    try {
      if (indexPaused) {
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

  return (
    <section>
      <h2>Consent &amp; Index Roots</h2>
      <p className="hint">
        Folders LifeVault has permission to scan and index. Adding a folder
        here is what grants access -- nothing outside these paths is ever
        touched.
      </p>

      {error && <p className="error">Error: {error}</p>}

      <div className="row" style={{ alignItems: "center" }}>
        <button disabled={busy || loading} onClick={toggleIndexing}>
          {indexPaused ? "Resume indexing" : "Pause indexing"}
        </button>
        <span className="hint">
          {indexPaused ? "Indexing is paused for all folders." : "Indexing is active."}
        </span>
      </div>

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
      ) : roots.length === 0 ? (
        <p className="hint">No folders granted yet. Add one above to get started.</p>
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
                <td className="mono">{root.path}</td>
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
