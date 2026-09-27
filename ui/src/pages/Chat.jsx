import { useState } from "react";
import { sendChatMessage } from "../api/client.js";
import CitationViewer from "../components/CitationViewer.jsx";

function CitationChip({ citation, onOpen }) {
  const filename = citation.path ? citation.path.split("/").pop() : "source";
  const pageSuffix = citation.page ? ` p.${citation.page}` : "";
  return (
    <button
      type="button"
      className="citation-chip"
      onClick={() => onOpen(citation)}
      title={citation.path || citation.document_hash}
    >
      {citation.label ? `${citation.label}: ` : ""}
      {filename}
      {pageSuffix}
    </button>
  );
}

export default function Chat() {
  const [conversationId, setConversationId] = useState(null);
  const [history, setHistory] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [activeCitation, setActiveCitation] = useState(null);

  async function handleSend(e) {
    e.preventDefault();
    const message = input.trim();
    if (!message) return;

    setSending(true);
    setError(null);
    const nextHistory = [...history, { role: "user", content: message }];
    setHistory(nextHistory);
    setInput("");

    try {
      const resp = await sendChatMessage(message, conversationId, history);
      setConversationId(resp.conversation_id);
      setHistory([
        ...nextHistory,
        {
          role: "assistant",
          content: resp.answer,
          citations: resp.citations || [],
          grounded: resp.grounded,
          confidence: resp.confidence,
          verificationReason: resp.verification_reason,
        },
      ]);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <section>
      <h2>Chat</h2>
      <p className="hint">
        Ask a question about your indexed documents. Answers are grounded in
        retrieved chunks; click a citation chip to preview the source.
      </p>

      {error && <p className="error">Error: {error}</p>}

      <div className="chat-log">
        {history.length === 0 && <p className="hint">Ask something to get started.</p>}
        {history.map((m, i) => (
          <div key={i} className={`chat-message chat-${m.role}`}>
            <strong>{m.role === "user" ? "You" : "LifeVault"}:</strong> {m.content}
            {m.role === "assistant" && m.grounded === false && (
              <span className="badge badge-warn" title={m.verificationReason || ""}>
                unverified
              </span>
            )}
            {m.role === "assistant" && m.citations && m.citations.length > 0 && (
              <div className="citation-row">
                {m.citations.map((c, ci) => (
                  <CitationChip key={ci} citation={c} onOpen={setActiveCitation} />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form className="row" onSubmit={handleSend}>
        <input
          type="text"
          placeholder="Ask a question..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
        />
        <button type="submit" disabled={sending}>
          {sending ? "Sending..." : "Send"}
        </button>
      </form>

      {activeCitation && (
        <CitationViewer citation={activeCitation} onClose={() => setActiveCitation(null)} />
      )}
    </section>
  );
}
