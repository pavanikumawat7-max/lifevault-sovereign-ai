// Thin wrapper around the frozen S1 API contracts (see api/schemas.py).
// Every function here maps 1:1 to one endpoint. Deliberately no caching,
// retries, or state management beyond that -- this is S1's job only: prove
// the UI can round-trip real requests/responses through the real API.

async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new Error(`${options.method || "GET"} ${path} failed (${resp.status}): ${detail}`);
  }
  return resp.json();
}

// --- Roots ---------------------------------------------------------------
export const listRoots = () => request("/api/roots");
export const createRoot = (path, excludePatterns = []) =>
  request("/api/roots", {
    method: "POST",
    body: JSON.stringify({ path, exclude_patterns: excludePatterns }),
  });
export const deleteRoot = (id) => request(`/api/roots/${id}`, { method: "DELETE" });

// --- Index -----------------------------------------------------------------
export const pauseIndex = () => request("/api/index/pause", { method: "POST" });
export const resumeIndex = () => request("/api/index/resume", { method: "POST" });
export const getIndexStatus = () => request("/api/index/status");
export const startIndexing = (rootId = null) =>
  request("/api/index/start", {
    method: "POST",
    body: JSON.stringify({ root_id: rootId }),
  });

// --- Chat --------------------------------------------------------------------
export const sendChatMessage = (message, conversationId = null, history = []) =>
  request("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, conversation_id: conversationId, history }),
  });

// --- Documents -----------------------------------------------------------------
export const getDocument = (hash) => request(`/api/documents/${hash}`);
export const previewDocument = (hash) => request(`/api/documents/${hash}/preview`);
export const openDocument = (hash, path = null) =>
  request(`/api/documents/${hash}/open`, { method: "POST", body: JSON.stringify({ path }) });
export const revealDocument = (hash) =>
  request(`/api/documents/${hash}/reveal`, { method: "POST" });

// --- Facts -----------------------------------------------------------------------
export const listFacts = () => request("/api/facts");
export const updateFact = (id, updates) =>
  request(`/api/facts/${id}`, { method: "PATCH", body: JSON.stringify(updates) });

// --- Approvals ---------------------------------------------------------------------
export const decideApproval = (proposalId, decision, note = null) =>
  request(`/api/approvals/${proposalId}`, {
    method: "POST",
    body: JSON.stringify({ decision, note }),
  });

// --- Memory ------------------------------------------------------------------------
export const getMemory = () => request("/api/memory");

// --- Audit -------------------------------------------------------------------------
export const listAudit = (limit = 100) => request(`/api/audit?limit=${limit}`);
export const verifyAudit = () => request("/api/audit/verify");

// --- Health ------------------------------------------------------------------------
export const getHealth = () => request("/api/health");
