import { NavLink, Route, Routes } from "react-router";
import { Icon } from "./components/Icon";
import { Connection } from "./components/Connection";
import { Dashboard } from "./pages/Dashboard";
import { Live } from "./pages/Live";
import { Sessions, SessionDetail, NotFound } from "./pages/Sessions";
import { Hands, HandDetail } from "./hands/Hands";

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/" aria-label="Zeros, inicio">
          <span className="brand-mark">z</span>zeros
          <span className="brand-dot">.</span>
        </NavLink>
        <div className="workspace-label">
          POKER LAB <span>v0.22</span>
        </div>
        <nav aria-label="Navegación principal">
          <NavLink to="/" end>
            <Icon name="dashboard" />
            Resumen
          </NavLink>
          <NavLink to="/live">
            <Icon name="live" />
            En directo
            <span className="nav-dot" />
          </NavLink>
          <NavLink to="/sessions">
            <Icon name="sessions" />
            Sesiones
          </NavLink>
          <NavLink to="/hands">
            <Icon name="sessions" />
            Manos
          </NavLink>
        </nav>
        <div className="sidebar-bottom">
          <div className="build-note">
            <span className="small-label">EN CONSTRUCCIÓN</span>
            <strong>Una base para cada mano.</strong>
            <p>Fase 22 de 30 · Feedback según modo</p>
            <div className="progress-track">
              <span />
            </div>
          </div>
          <div className="local-profile">
            <span className="avatar">Z</span>
            <div>
              Espacio local<small>Tu laboratorio de poker</small>
            </div>
            <span className="local-dot" />
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>Tu juego, con perspectiva.</span>
          <Connection />
        </header>
        <main>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/live" element={<Live />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/hands" element={<Hands />} />
            <Route path="/hands/:id" element={<HandDetail />} />
            <Route path="/session/:id" element={<SessionDetail />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
        <footer>
          <span>ZEROS POKER LAB</span>
          <span>Observa. Comprende. Evoluciona.</span>
        </footer>
      </div>
    </div>
  );
}
