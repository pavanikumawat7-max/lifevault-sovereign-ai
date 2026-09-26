import { useState } from "react";
import { sendChatMessage } from "../api/client.js";

export default function Chat() {
  const [conversationId, setConversationId] = useState(null);
  const [history, setHistory] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

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
      setHistory([...nextHistory, { role: "assistant", content: resp.answer }]);
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
        S1 stub: answers come from <code>llm.chat()</code> in fixture mode --
        no retrieval, grounding, or citations yet.
      </p>

      {error && <p className="error">Error: {error}</p>}

      <div className="chat-log">
        {history.length === 0 && <p className="hint">Ask something to get started.</p>}
        {history.map((m, i) => (
          <div key={i} className={`chat-message chat-${m.role}`}>
            <strong>{m.role === "user" ? "You" : "LifeVault"}:</strong> {m.content}
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
    </section>
  );
}
