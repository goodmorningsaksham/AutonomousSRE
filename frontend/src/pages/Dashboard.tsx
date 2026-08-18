import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle2, Clock, ArrowRight, Layers, Cpu, Database, Server } from 'lucide-react';
import { fetchIncidents, fetchStats, type Incident, type Stats } from '../api';

const timeAgo = (dt: string) => {
  const diff = Date.now() - new Date(dt).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

const getStatusBadgeClass = (status: string) => {
  switch (status.toUpperCase()) {
    case 'RESOLVED': return 'badge-resolved';
    case 'AWAITING_APPROVAL': return 'badge-awaiting';
    case 'INVESTIGATING':
    case 'REMEDIATING':
    case 'VERIFYING': return 'badge-remediating';
    case 'FAILED': return 'badge-failed';
    default: return 'badge-low';
  }
};

const getSeverityBadgeClass = (sev: string) => {
  switch (sev.toLowerCase()) {
    case 'critical': return 'badge-critical';
    case 'high': return 'badge-high';
    case 'medium': return 'badge-medium';
    default: return 'badge-low';
  }
};

export default function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const load = async () => {
      const [inc, st] = await Promise.all([
        fetchIncidents({ limit: 8 }).catch(() => []),
        fetchStats().catch(() => null),
      ]);
      setIncidents(inc);
      setStats(st);
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 8000);
    return () => clearInterval(interval);
  }, []);

  const byStatus = stats?.incidents_by_status || {};
  const active = (byStatus['INVESTIGATING'] || 0) + (byStatus['REMEDIATING'] || 0) + (byStatus['VERIFYING'] || 0) + (byStatus['AWAITING_APPROVAL'] || 0);
  const resolved = byStatus['RESOLVED'] || 0;
  const awaiting = byStatus['AWAITING_APPROVAL'] || 0;
  const total = stats?.total || 0;

  return (
    <div>
      {/* Hero Header */}
      <div className="page-hero">
        <div>
          <h1 className="page-hero__title">System Overview</h1>
          <p className="page-hero__subtitle">Autonomous incident detection, correlation, and recovery mesh</p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="apple-btn apple-btn--primary" onClick={() => navigate('/incidents')}>
            Explore All Incidents
            <ArrowRight size={15} />
          </button>
        </div>
      </div>

      {/* 4 Stat Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-card__top">
            <span className="stat-card__label">Active Incidents</span>
            <div className="stat-card__icon-wrap" style={{ background: active > 0 ? 'rgba(255, 69, 58, 0.15)' : 'rgba(48, 209, 88, 0.15)', color: active > 0 ? 'var(--apple-red)' : 'var(--apple-green)' }}>
              <AlertCircle size={18} />
            </div>
          </div>
          <div className="stat-card__value" style={{ color: active > 0 ? 'var(--apple-red)' : 'var(--text-primary)' }}>
            {active}
          </div>
          <div className="stat-card__footer">
            <span>{active > 0 ? 'Requires attention' : 'All systems nominal'}</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__top">
            <span className="stat-card__label">Awaiting Approval</span>
            <div className="stat-card__icon-wrap" style={{ background: awaiting > 0 ? 'rgba(255, 214, 10, 0.15)' : 'rgba(255, 255, 255, 0.05)', color: awaiting > 0 ? 'var(--apple-yellow)' : 'var(--text-tertiary)' }}>
              <Clock size={18} />
            </div>
          </div>
          <div className="stat-card__value" style={{ color: awaiting > 0 ? 'var(--apple-yellow)' : 'var(--text-primary)' }}>
            {awaiting}
          </div>
          <div className="stat-card__footer">
            <span>Human verification gate</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__top">
            <span className="stat-card__label">Resolved Incidents</span>
            <div className="stat-card__icon-wrap" style={{ background: 'rgba(48, 209, 88, 0.15)', color: 'var(--apple-green)' }}>
              <CheckCircle2 size={18} />
            </div>
          </div>
          <div className="stat-card__value" style={{ color: 'var(--apple-green)' }}>
            {resolved}
          </div>
          <div className="stat-card__footer">
            <span>Auto & human remediated</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__top">
            <span className="stat-card__label">Total Recorded</span>
            <div className="stat-card__icon-wrap" style={{ background: 'rgba(41, 151, 255, 0.15)', color: 'var(--apple-blue)' }}>
              <Layers size={18} />
            </div>
          </div>
          <div className="stat-card__value">
            {total}
          </div>
          <div className="stat-card__footer">
            <span>Lifetime event stream</span>
          </div>
        </div>
      </div>

      {/* Microservice Topology Matrix */}
      <div className="glass-card" style={{ marginBottom: 32 }}>
        <div className="card-header">
          <div className="card-header__title">
            <Server size={17} style={{ color: 'var(--apple-blue)' }} />
            Production Topology & Dependencies
          </div>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>OpenTelemetry Traced</span>
        </div>

        <div className="topology-grid">
          <div className="topology-node">
            <div className="topology-node__left">
              <div className="topology-node__icon"><Cpu size={16} /></div>
              <div>
                <div className="topology-node__name">checkout-service</div>
                <div className="topology-node__role">Port 3001 • Edge Gateway</div>
              </div>
            </div>
            <span className="apple-badge badge-resolved apple-badge--dot">Online</span>
          </div>

          <div className="topology-node">
            <div className="topology-node__left">
              <div className="topology-node__icon"><Database size={16} /></div>
              <div>
                <div className="topology-node__name">payment-service</div>
                <div className="topology-node__role">Port 3002 • Postgres Linked</div>
              </div>
            </div>
            <span className="apple-badge badge-resolved apple-badge--dot">Online</span>
          </div>

          <div className="topology-node">
            <div className="topology-node__left">
              <div className="topology-node__icon"><Database size={16} /></div>
              <div>
                <div className="topology-node__name">inventory-service</div>
                <div className="topology-node__role">Port 3003 • Redis Linked</div>
              </div>
            </div>
            <span className="apple-badge badge-resolved apple-badge--dot">Online</span>
          </div>
        </div>
      </div>

      {/* Recent Incidents Feed */}
      <div className="glass-card">
        <div className="card-header">
          <div className="card-header__title">
            <AlertCircle size={17} style={{ color: 'var(--apple-orange)' }} />
            Recent Incidents Stream
          </div>
          <button className="apple-btn apple-btn--glass" style={{ padding: '4px 12px', fontSize: 12 }} onClick={() => navigate('/incidents')}>
            View All
          </button>
        </div>

        {loading ? (
          <div className="apple-loading">
            <div className="apple-spinner" />
            <span>Streaming incident events…</span>
          </div>
        ) : incidents.length === 0 ? (
          <div className="apple-empty">
            <div className="apple-empty__icon">🛡️</div>
            <div className="apple-empty__title">All Systems Nominal</div>
            <div className="apple-empty__desc">No recent failure events or active alerts detected across the mesh.</div>
          </div>
        ) : (
          <div className="incident-list">
            {incidents.map((inc) => (
              <div
                key={inc.id}
                className="incident-row"
                onClick={() => navigate(`/incidents/${inc.id}`)}
              >
                <div
                  className="incident-row__stripe"
                  style={{
                    background: inc.severity === 'critical' ? 'var(--apple-red)' : (inc.severity === 'high' ? 'var(--apple-orange)' : 'var(--apple-blue)')
                  }}
                />
                <div className="incident-row__main">
                  <div className="incident-row__title">
                    <span>{inc.title}</span>
                    <span className={`apple-badge ${getSeverityBadgeClass(inc.severity)}`}>
                      {inc.severity.toUpperCase()}
                    </span>
                  </div>
                  <div className="incident-row__sub">
                    <span>Service: <strong>{inc.service}</strong></span>
                    <span>•</span>
                    <span>Namespace: <strong>{inc.namespace}</strong></span>
                    {inc.root_cause && (
                      <>
                        <span>•</span>
                        <span style={{ color: 'var(--apple-purple)' }}>RCA: {inc.root_cause}</span>
                      </>
                    )}
                  </div>
                </div>

                <div className="incident-row__right">
                  <span className={`apple-badge apple-badge--dot ${getStatusBadgeClass(inc.status)}`}>
                    {inc.status}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-tertiary)', minWidth: 60, textAlign: 'right' }}>
                    {timeAgo(inc.created_at)}
                  </span>
                  <ArrowRight size={16} style={{ color: 'var(--text-tertiary)' }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
