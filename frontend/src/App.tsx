import React from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { AlertTriangle, Shield, BarChart2, Bell } from 'lucide-react';
import Dashboard from './pages/Dashboard';
import Incidents from './pages/Incidents';
import IncidentDetail from './pages/IncidentDetail';
import Approvals from './pages/Approvals';
import './App.css';

const NavItem = ({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) => (
  <NavLink
    to={to}
    className={({ isActive }) =>
      `nav-item ${isActive ? 'nav-item--active' : ''}`
    }
  >
    <Icon size={18} />
    <span>{label}</span>
  </NavLink>
);

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <aside className="sidebar">
          <div className="sidebar__logo">
            <Shield size={28} className="logo-icon" />
            <div>
              <div className="logo-title">Aegis</div>
              <div className="logo-sub">Autonomous SRE</div>
            </div>
          </div>
          <nav className="sidebar__nav">
            <NavItem to="/" icon={BarChart2} label="Dashboard" />
            <NavItem to="/incidents" icon={AlertTriangle} label="Incidents" />
            <NavItem to="/approvals" icon={Bell} label="Approvals" />
          </nav>
          <div className="sidebar__status">
            <div className="status-dot status-dot--green" />
            <span>System Operational</span>
          </div>
        </aside>

        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/approvals" element={<Approvals />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
