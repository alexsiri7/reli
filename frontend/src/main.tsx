import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";

import "./index.css";
import { ThingDetailView } from "./views/ThingDetail";
import { Tree } from "./views/Tree";
import { UserModelView } from "./views/UserModel";

function App() {
  return (
    <BrowserRouter>
      <header className="masthead">
        <span className="brand">Reli</span>
        <nav>
          <Link to="/">Tree</Link>
          <Link to="/user-model">User model</Link>
        </nav>
      </header>
      <main>
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
