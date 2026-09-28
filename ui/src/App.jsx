import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import Consent from "./pages/Consent.jsx";
import Chat from "./pages/Chat.jsx";
import IndexStatus from "./pages/IndexStatus.jsx";
import Approvals from "./pages/Approvals.jsx";
import Audit from "./pages/Audit.jsx";
import Expiry from "./pages/Expiry.jsx";
import { getHealth, getIndexStatus } from "./api/client.js";

function IconChat() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a8.5 8.5 0 0 1-8.5 8.5c-1.3 0-2.53-.3-3.62-.83L3 21l1.4-4.2A8.4 8.4 0 0 1 3.5 12 8.5 8.5 0 0 1 12 3.5 8.5 8.5 0 0 1 21 12Z" />
    </svg>
  );
}

function IconFolder() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v8.5A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5v-11Z" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 7 10.5 17 4.5 11.5" />
      <rect x="3" y="3" width="18" height="18" rx="4.5" opacity="0.25" />
    </svg>
  );
}

function IconAudit() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 3.5h8l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19V5A1.5 1.5 0 0 1 7 3.5Z" />
      <path d="M15 3.5V8h4M9 12.5h6M9 16h6" />
    </svg>
  );
}

function IconClock() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

const NAV_ITEMS = [
  { to: "/", label: "Chat", end: true, Icon: IconChat },
  { to: "/consent", label: "Consent & Roots", Icon: IconFolder },
  { to: "/index-status", label: "Index Status", Icon: IconClock },
  { to: "/approvals", label: "Approvals", Icon: IconCheck },
  { to: "/audit", label: "Audit Log", Icon: IconAudit },
  { to: "/expiry", label: "Expiry & Facts", Icon: IconClock },
];

export default function App() {
  const location = useLocation();
  const isChatRoute = location.pathname === "/";
  const [badge, setBadge] = useState({ text: "Connecting...", tone: "neutral" });

  useEffect(() => {
    let cancelled = false;

    async function refreshBadge() {
      try {
        await getHealth();
        const { status } = await getIndexStatus();
        if (cancelled) return;
        setBadge({
          text: `Connected \u00b7 ${status.documents_indexed} doc${status.documents_indexed === 1 ? "" : "s"} indexed`,
          tone: status.state === "error" ? "error" : "ok",
        });
      } catch {
        if (!cancelled) setBadge({ text: "Backend offline", tone: "error" });
      }
    }

    refreshBadge();
    const timer = setInterval(refreshBadge, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand">
          <span className="brand-mark">LV</span>
          <div className="brand-text">
            <span className="brand-name">LifeVault</span>
            <span className={`badge badge--${badge.tone}`}>{badge.text}</span>
          </div>
        </div>

        <nav className="app-nav">
          {NAV_ITEMS.map(({ to, label, end, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              <span className="nav-icon" aria-hidden="true">
                <Icon />
              </span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="hint">Local-first · no cloud calls</span>
        </div>
      </aside>

      <main className={isChatRoute ? "app-main app-main--chat" : "app-main"}>
        <div className={isChatRoute ? "app-main-inner app-main-inner--chat" : "app-main-inner"}>
          <Routes>
            <Route path="/" element={<Chat />} />
            <Route path="/consent" element={<Consent />} />
            <Route path="/index-status" element={<IndexStatus />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/expiry" element={<Expiry />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
