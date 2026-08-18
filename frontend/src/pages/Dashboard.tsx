import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Clock } from 'lucide-react';
import { fetchIncidents, fetchStats, type Incident, type Stats } from '../api';

const StatusBadge = ({ status }: { status: string }) => (
  <span className={`badge badge--${status.toLowerCase()}`}>{status}</span>
);

const SeverityBadge = ({ severity }: { severity: string }) => (
  <span className={`badge badge--${severity.toLowerCase()}`}>{severity}</span>
);

const timeAgo = (dt: string) => {
  const diff = Date.now() - new Date(dt).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

export default function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const load = async () => {
      const [inc, st] = await Promise.all([
        fetchIncidents({ limit: 10 }).catch(() => []),
        fetchStats().catch(() => null),
      ]);
      setIncidents(inc);
      setStats(st);
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const byStatus = stats?.incidents_by_status || {};
  const active = (byStatus['INVESTIGATING'] || 0) + (byStatus['REMEDIATING'] || 0) + (byStatus['VERIFYING'] || 0) + (byStatus['AWAITING_APPROVAL'] || 0);
  const resolved = byStatus['RESOLVED'] || 0;
  const awaiting = byStatus['AWAITING_APPROVAL'] || 0;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-sub">Real-time incident overview — auto-refreshes every 10s</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-card__label">Active Incidents</div>
          <div className="stat-card__value" style={{ color: active > 0 ? 'var(--red)' : 'var(--green)' }}>{active}</div>
          <div className="stat-card__delta">Currently being investigated</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Awaiting Approval</div>
          <div className="stat-card__value" style={{ color: awaiting > 0 ? 'var(--yellow)' : 'var(--text-muted)' }}>{awaiting}</div>
          <div className="stat-card__delta">Requires human decision</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Resolved Today</div>
          <div className="stat-card__value" style={{ color: 'var(--green)' }}>{resolved}</div>
          <div className="stat-card__delta">Successfully remediated</div>
        </div>
        <div className="stat-card">
          <div className="stat-card__label">Total Incidents</div>
          <div className="stat-card__value">{stats?.total || 0}</div>
          <div className="stat-card__delta">All time</div>
        </div>
      </div>

      <div className="card">
        <div className="card__title">Recent Incidents</div>
        {loading ? (
          <div className="loading"><Clock size={18} /> Loading incidents...</div>
        ) : incidents.length === 0 ? (
          <div className="empty">
            <div className="empty__icon">✨</div>
            <div className="empty__text">No incidents — system is healthy</div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Service</th>
                  <th>Title</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Root Cause</th>
                  <th>Age</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map(inc => (
                  <tr key={inc.id} onClick={() => navigate(`/incidents/${inc.id}`)}>
                    <td><code style={{ background: 'var(--surface-2)', padding: '2px 8px', borderRadius: 4, fontSize: 12 }}>{inc.service}</code></td>
                    <td style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{inc.title}</td>
                    <td><SeverityBadge severity={inc.severity} /></td>
                    <td><StatusBadge status={inc.status} /></td>
                    <td style={{ color: 'var(--text-muted)', fontSize: 13, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {inc.root_cause ? `${inc.root_cause.slice(0, 60)}…` : '—'}
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: 13, whiteSpace: 'nowrap' }}>{timeAgo(inc.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
