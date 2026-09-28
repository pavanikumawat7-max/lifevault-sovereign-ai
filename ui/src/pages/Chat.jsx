import { useEffect, useRef, useState } from "react";
import { sendChatMessage } from "../api/client.js";
import CitationList from "../components/CitationList.jsx";
import { assistantMessageFromResponse, toRequestHistory } from "../utils/citations.js";

const SUGGESTIONS = [
  "What documents have been indexed so far?",
  "Summarize the most recent document.",
  "Which documents mention an expiry date?",
];

export default function Chat() {
  const [conversationId, setConversationId] = useState(null);
  const [history, setHistory] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [history, sending]);

  async function sendMessage(message) {
    setSending(true);
    setError(null);
    const nextHistory = [...history, { role: "user", content: message }];
    setHistory(nextHistory);
    setInput("");

    try {
      const resp = await sendChatMessage(message, conversationId, toRequestHistory(history));
      setConversationId(resp.conversation_id);
      setHistory([...nextHistory, assistantMessageFromResponse(resp)]);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  function handleSend(e) {
    e.preventDefault();
    const message = input.trim();
    if (!message) return;
    sendMessage(message);
  }

  function handleSuggestion(text) {
    if (sending) return;
    sendMessage(text);
  }

  const userTurns = history.filter((m) => m.role === "user").length;
  const lastModel = [...history].reverse().find((m) => m.role === "assistant" && m.model)?.model;

  return (
    <section className="chat-page">
      <header className="chat-page-header">
        <div>
          <h2>Chat</h2>
          <p className="hint">
            Answers are drawn from your indexed files. Sources are listed under each answer; if an
            answer can&apos;t be verified against them, the reason is shown instead.
          </p>
        </div>
      </header>

      <div className="chat-grid">
        <div className="chat-panel">
          <div className="chat-log" ref={logRef}>
            {history.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-empty-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12a8.5 8.5 0 0 1-8.5 8.5c-1.3 0-2.53-.3-3.62-.83L3 21l1.4-4.2A8.4 8.4 0 0 1 3.5 12 8.5 8.5 0 0 1 12 3.5 8.5 8.5 0 0 1 21 12Z" />
                  </svg>
                </div>
                <p className="chat-empty-title">Ask LifeVault something</p>
                <p className="chat-empty-subtitle">
                  Answers come from your indexed files, with the sources shown under each one.
                  Try a prompt on the right or ask your own question.
                </p>
              </div>
            ) : (
              <div className="chat-messages">
                {history.map((m, i) => (
                  <div key={i} className={`chat-bubble-row chat-bubble-row--${m.role}`}>
                    <div className="chat-avatar" aria-hidden="true">
                      {m.role === "user" ? "U" : "LV"}
                    </div>
                    <div className="chat-bubble">
                      <span className="chat-bubble-label">
                        {m.role === "user" ? "You" : "LifeVault"}
                      </span>
                      <p className="chat-bubble-text">{m.content}</p>
                      {m.role === "assistant" && !m.grounded && m.verificationReason && (
                        <p className="chat-note">Not verified: {m.verificationReason}</p>
                      )}
                      {m.role === "assistant" && <CitationList citations={m.citations} />}
                    </div>
                  </div>
                ))}
                {sending && (
                  <div className="chat-bubble-row chat-bubble-row--assistant">
                    <div className="chat-avatar" aria-hidden="true">LV</div>
                    <div className="chat-bubble">
                      <span className="chat-bubble-label">LifeVault</span>
                      <p className="chat-typing">
                        <span></span>
                        <span></span>
                        <span></span>
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {error && <p className="error chat-error">Error: {error}</p>}

          <form className="composer" onSubmit={handleSend}>
            <input
              type="text"
              className="composer-input"
              placeholder="Ask a question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button type="submit" className="composer-send" disabled={sending || !input.trim()}>
              {sending ? (
                "Sending…"
              ) : (
                <>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 12h16M13 5l7 7-7 7" />
                  </svg>
                  <span>Send</span>
                </>
              )}
            </button>
          </form>
        </div>

        <aside className="chat-side">
          <div className="side-card">
            <div className="side-card-title">
              <span className="side-icon side-icon--teal" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="8.5" />
                  <path d="M12 7.5V12l3 2" />
                </svg>
              </span>
              Session
            </div>
            <dl className="side-stats">
              <div className="side-stat">
                <dt>Status</dt>
                <dd>
                  <span className="pill pill--teal">{lastModel ? `Model: ${lastModel}` : "Ready"}</span>
                </dd>
              </div>
              <div className="side-stat">
                <dt>Conversation</dt>
                <dd className="mono">{conversationId ?? "not started"}</dd>
              </div>
              <div className="side-stat">
                <dt>Messages sent</dt>
                <dd>{userTurns}</dd>
              </div>
            </dl>
          </div>

          <div className="side-card">
            <div className="side-card-title">
              <span className="side-icon side-icon--pink" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3.5 14.3 9l6 .5-4.6 3.9 1.5 5.9L12 16.2 6.8 19.3l1.5-5.9L3.7 9.5l6-.5L12 3.5Z" />
                </svg>
              </span>
              Try asking
            </div>
            <div className="suggestion-list">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="suggestion-chip"
                  onClick={() => handleSuggestion(s)}
                  disabled={sending}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="side-card side-card--muted">
            <div className="side-card-title">
              <span className="side-icon side-icon--blue" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M7 3.5h8l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19V5A1.5 1.5 0 0 1 7 3.5Z" />
                  <path d="M15 3.5V8h4M9 12.5h6M9 16h6" />
                </svg>
              </span>
              About sources
            </div>
            <p className="hint side-hint">
              Each answer lists the files and pages it was drawn from, with the supporting quote.
            </p>
          </div>
        </aside>
      </div>
    </section>
  );
}
