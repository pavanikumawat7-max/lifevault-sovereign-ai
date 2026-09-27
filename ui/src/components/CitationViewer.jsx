import { useEffect, useState } from "react";
import { openDocument, previewDocument, revealDocument } from "../api/client.js";

/**
 * Modal that previews a cited source document and lets the user open it in
 * its default application or reveal it in the file manager. Takes a
 * `citation` object shaped like api/schemas.py::Citation (document_hash,
 * path, page, label, quote, also_found_at) and an `onClose` callback.
 */
export default function CitationViewer({ citation, onClose }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setActionMessage(null);
    previewDocument(citation.document_hash)
      .then((data) => {
        if (!cancelled) setPreview(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [citation.document_hash]);

  async function handleOpen() {
    setBusy(true);
    setActionMessage(null);
    try {
      const resp = await openDocument(citation.document_hash, citation.path || null);
      setActionMessage(resp.message || (resp.opened ? "Opened." : "Could not open."));
    } catch (err) {
      setActionMessage(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReveal() {
    setBusy(true);
    setActionMessage(null);
    try {
      const resp = await revealDocument(citation.document_hash);
      setActionMessage(resp.message || (resp.revealed ? "Revealed." : "Could not reveal."));
    } catch (err) {
      setActionMessage(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>
            {citation.label ? `${citation.label} -- ` : ""}
            {citation.path ? citation.path.split("/").pop() : "Source"}
          </h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <div className="citation-meta">
          {citation.path && (
            <p className="mono hint" title={citation.path}>
              {citation.path}
              {citation.page ? ` (page ${citation.page})` : ""}
            </p>
          )}
          {citation.also_found_at && citation.also_found_at.length > 0 && (
            <p className="hint">
              Also found at: {citation.also_found_at.join(", ")}
            </p>
          )}
          {citation.quote && (
            <blockquote className="citation-quote">&ldquo;{citation.quote}&rdquo;</blockquote>
          )}
        </div>

        {error && <p className="error">Error: {error}</p>}
        {loading && <p className="hint">Loading preview...</p>}

        {!loading && preview && (
          <div className="preview-box">
            <pre>{preview.preview_text}</pre>
            {preview.page_count != null && (
              <p className="hint">{preview.page_count} page(s) total</p>
            )}
          </div>
        )}

        <div className="row">
          <button disabled={busy} onClick={handleOpen}>
            Open original
          </button>
          <button disabled={busy} onClick={handleReveal}>
            Reveal in file manager
          </button>
        </div>
        {actionMessage && <p className="hint">{actionMessage}</p>}
      </div>
    </div>
  );
}
