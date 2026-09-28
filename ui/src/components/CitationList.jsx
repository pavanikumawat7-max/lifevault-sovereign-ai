import { citationDisplay } from "../utils/citations.js";

/**
 * Sources for one assistant answer. Takes the `citations` array from
 * POST /api/chat (api/schemas.py::Citation) and renders filename, page and
 * supporting quote for each. Renders nothing when there are no citations.
 */
export default function CitationList({ citations }) {
  const items = (citations || []).map(citationDisplay);
  if (items.length === 0) return null;

  return (
    <div className="citation-list">
      <span className="citation-list-title">Sources</span>
      <ol className="citation-items">
        {items.map((c) => (
          <li key={c.key} className="citation-card">
            <div className="citation-card-head">
              {c.label && <span className="citation-label">{c.label}</span>}
              <span className="citation-file" title={c.path || undefined}>
                {c.fileName}
              </span>
              {c.page && <span className="citation-page">Page {c.page}</span>}
            </div>
            {c.quote && (
              <blockquote className="citation-card-quote">&ldquo;{c.quote}&rdquo;</blockquote>
            )}
            {c.alsoFoundAt.length > 0 && (
              <p className="citation-also">Also found at: {c.alsoFoundAt.join(", ")}</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
