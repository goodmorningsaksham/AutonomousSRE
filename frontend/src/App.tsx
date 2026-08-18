import React from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { Shield, AlertTriangle, CheckSquare, LayoutDashboard, Sparkles, ExternalLink, Activity } from 'lucide-react';
import Dashboard from './pages/Dashboard';
import Incidents from './pages/Incidents';
import IncidentDetail from './pages/IncidentDetail';
import Approvals from './pages/Approvals';
import './App.css';

const NavItem = ({ to, icon: Icon, label, badge }: { to: string; icon: React.ElementType; label: string; badge?: number }) => (
  <NavLink
    to={to}
    end={to === '/'}
    className={({ isActive }) =>
      `nav-item ${isActive ? 'nav-item--active' : ''}`
    }
  >
    <div className="nav-item__left">
      <Icon size={17} />
      <span>{label}</span>
    </div>
    {badge !== undefined && badge > 0 && (
      <span className="nav-badge">{badge}</span>
    )}
  </NavLink>
);

function TopBar() {
  const location = useLocation();
  const getPageName = () => {
    if (location.pathname === '/') return 'System Overview';
    if (location.pathname.startsWith('/incidents/')) return 'Incident Investigation';
    if (location.pathname === '/incidents') return 'Incident Center';
    if (location.pathname === '/approvals') return 'Approval Gate';
    return 'Dashboard';
  };

  return (
    <header className="top-bar">
      <div className="top-bar__breadcrumbs">
        <span>Aegis</span>
        <span>/</span>
        <span className="active">{getPageName()}</span>
      </div>

      <div className="top-bar__links">
        <a href="http://localhost:3000" target="_blank" rel="noreferrer" className="glass-pill-btn">
          <Activity size={13} />
          Grafana
          <ExternalLink size={11} />
        </a>
        <a href="http://localhost:8088" target="_blank" rel="noreferrer" className="glass-pill-btn">
          Temporal UI
          <ExternalLink size={11} />
        </a>
        <a href="http://localhost:9090" target="_blank" rel="noreferrer" className="glass-pill-btn">
          Prometheus
          <ExternalLink size={11} />
        </a>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        {/* Apple Luxury Frosted Sidebar */}
        <aside className="sidebar">
          <div className="sidebar__brand">
            <div className="brand-icon">
              <Shield size={20} />
            </div>
            <div>
              <div className="brand-title">Aegis</div>
              <div className="brand-sub">Autonomous SRE</div>
            </div>
          </div>

          <div className="sidebar__section-title">Navigation</div>
          <nav className="sidebar__nav">
            <NavItem to="/" icon={LayoutDashboard} label="Overview" />
            <NavItem to="/incidents" icon={AlertTriangle} label="Incidents" />
            <NavItem to="/approvals" icon={CheckSquare} label="Approvals" />
          </nav>

          <div className="sidebar__bottom">
            {/* Active AI Engine Badge */}
            <div className="ai-engine-badge">
              <Sparkles size={18} className="ai-sparkle" />
              <div>
                <div className="ai-text-title">Google Gemini</div>
                <div className="ai-text-sub">Gemini 1.5 Flash • Active</div>
              </div>
            </div>

            {/* System Status Pill */}
            <div className="system-status-pill">
              <div className="pulse-dot" />
              <span>Event Mesh Active</span>
            </div>
          </div>
        </aside>

        {/* Main Content Workspace */}
        <div className="main-wrapper">
          <TopBar />
          <main className="content-canvas">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/incidents/:id" element={<IncidentDetail />} />
              <Route path="/approvals" element={<Approvals />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
