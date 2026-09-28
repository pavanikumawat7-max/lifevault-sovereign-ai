import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createRoot,
  deleteRoot,
  getIndexStatus,
  listRoots,
  pauseIndex,
  resumeIndex,
  startIndexing,
} from "../api/client.js";

export default function Consent() {
  const [roots, setRoots] = useState([]);
  const [newPath, setNewPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [indexPaused, setIndexPaused] = useState(false);
  const [indexMessage, setIndexMessage] = useState(null);

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
    setIndexMessage(null);
    try {
      const created = await createRoot(newPath.trim());
      setNewPath("");
      await refresh();
      // Granting a folder is consent to index it -- start automatically,
      // no manual scripts/index_folder.py needed.
      try {
        const result = await startIndexing(created.root.id);
        setIndexMessage(result.message);
      } catch (indexErr) {
        setIndexMessage(`Indexing did not start: ${indexErr.message}`);
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleIndexNow(rootId = null) {
    setIndexMessage(null);
    try {
      const result = await startIndexing(rootId);
      setIndexMessage(result.message);
    } catch (err) {
      setIndexMessage(`Indexing did not start: ${err.message}`);
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
      {indexMessage && <p className="hint">{indexMessage}</p>}

      <div className="row" style={{ alignItems: "center" }}>
        <button disabled={busy || loading} onClick={toggleIndexing}>
          {indexPaused ? "Resume indexing" : "Pause indexing"}
        </button>
        <button disabled={busy || loading} onClick={() => handleIndexNow(null)}>
          Index all now
        </button>
        <span className="hint">
          {indexPaused ? "Indexing is paused for all folders." : "Indexing is active."}
          {" "}
          <Link to="/index-status">View progress &rarr;</Link>
        </span>
      </div>

      <form className="row" onSubmit={handleAdd}>
        <input
          type="text"
          placeholder="/path/to/folder"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
        />
        <button type="submit">Grant access &amp; index</button>
      </form>
      <p className="hint">
        Granting a folder above starts indexing it automatically -- you
        don't need to run any script yourself.
      </p>

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
                  <button onClick={() => handleIndexNow(root.id)} disabled={!root.enabled || root.paused}>
                    Index now
                  </button>{" "}
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
