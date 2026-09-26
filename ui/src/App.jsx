import { NavLink, Route, Routes } from "react-router-dom";
import Consent from "./pages/Consent.jsx";
import Chat from "./pages/Chat.jsx";
import Approvals from "./pages/Approvals.jsx";
import Audit from "./pages/Audit.jsx";
import Expiry from "./pages/Expiry.jsx";

const NAV_ITEMS = [
  { to: "/", label: "Chat", end: true },
  { to: "/consent", label: "Consent" },
  { to: "/approvals", label: "Approvals" },
  { to: "/audit", label: "Audit" },
  { to: "/expiry", label: "Expiry" },
];

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>LifeVault</h1>
        <span className="badge">S1 -- fixture mode</span>
      </header>
      <nav className="app-nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Chat />} />
          <Route path="/consent" element={<Consent />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/expiry" element={<Expiry />} />
        </Routes>
      </main>
    </div>
  );
}
