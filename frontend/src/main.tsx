import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";

import { currentSession, setUnauthorizedHandler, signOut, type Session } from "./api";
import "./index.css";
import { SignIn } from "./views/SignIn";
import { Status } from "./views/Status";
import { ThingDetailView } from "./views/ThingDetail";
import { Tree } from "./views/Tree";
import { UserModelView } from "./views/UserModel";

/** `undefined` while `/api/auth/me` is being asked, `null` when it answered 401. */
type SessionState = Session | null | undefined;

function App() {
  const [session, setSession] = useState<SessionState>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => setSession(null));
    currentSession()
      .then(setSession)
      .catch((reason: unknown) => setError(String(reason)));
  }, []);

  function leave() {
    signOut()
      .then(() => setSession(null))
      .catch((reason: unknown) => setError(String(reason)));
  }

  if (session === undefined) {
    return (
      <main>
        <Status loading={error === null} error={error} />
      </main>
    );
  }
  if (session === null) {
    return (
      <main>
        <SignIn />
      </main>
    );
  }
  return (
    <BrowserRouter>
      <header className="masthead">
        <span className="brand">Reli</span>
        <nav>
          <Link to="/">Tree</Link>
          <Link to="/user-model">User model</Link>
        </nav>
        <span className="session">
          {session.email}
          <button className="sign-out" onClick={leave}>
            Sign out
          </button>
        </span>
      </header>
      <main>
        {error !== null && <p className="status error">{error}</p>}
        <Routes>
          <Route path="/" element={<Tree />} />
          <Route path="/things/:id" element={<ThingDetailView />} />
          <Route path="/user-model" element={<UserModelView />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
