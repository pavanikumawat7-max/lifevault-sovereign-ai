// Helpers for the chat UI's handling of POST /api/chat responses.
//
// The response shape is api/schemas.py::ChatResponse. Each entry of its
// `citations` list is api/schemas.py::Citation:
//   { document_hash, chunk_id, quote, path, page, also_found_at, label }
// Only `document_hash` and `quote` are guaranteed; `path`, `page`, `label`
// and `chunk_id` are optional, so everything here tolerates them missing.
// Nothing in this file invents data: a field the backend did not send is
// simply not shown.

/** Last segment of a file path. Handles both "/" and "\" separators. */
export function fileNameFromPath(path) {
  if (typeof path !== "string") return "";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : "";
}

/** Convert one backend Citation into what the UI displays. */
export function citationDisplay(citation, index = 0) {
  const path = typeof citation.path === "string" && citation.path ? citation.path : null;
  const label = typeof citation.label === "string" && citation.label ? citation.label : null;
  const quote = typeof citation.quote === "string" ? citation.quote.trim() : "";
  const alsoFoundAt = Array.isArray(citation.also_found_at)
    ? citation.also_found_at.filter((p) => typeof p === "string" && p)
    : [];
  const page = Number.isInteger(citation.page) && citation.page > 0 ? citation.page : null;
  const fileName = fileNameFromPath(path) || "Unknown file";

  return {
    key: `${label ?? "cite"}-${citation.chunk_id ?? citation.document_hash ?? ""}-${index}`,
    label,
    path,
    fileName,
    page,
    quote,
    alsoFoundAt,
  };
}

/**
 * The assistant chat message to store for a ChatResponse. Keeps the answer
 * plus the fields the UI needs to explain it (citations, grounding result).
 */
export function assistantMessageFromResponse(resp) {
  const citations = Array.isArray(resp?.citations)
    ? resp.citations.filter((c) => c && typeof c === "object")
    : [];
  return {
    role: "assistant",
    content: typeof resp?.answer === "string" ? resp.answer : "",
    citations,
    grounded: resp?.grounded === true,
    verificationReason: resp?.verification_reason || null,
    model: resp?.model || null,
  };
}

/**
 * History payload for the next request. ChatRequest.history only takes
 * { role, content }, so UI-only fields (citations etc.) are stripped.
 */
export function toRequestHistory(history) {
  return history.map((m) => ({ role: m.role, content: m.content }));
}
