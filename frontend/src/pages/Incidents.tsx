import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchIncidents, type Incident } from '../api';

const StatusBadge = ({ status }: { status: string }) => (
  <span className={`badge badge--${status.toLowerCase()}`}>{status}</span>
);

const SeverityBadge = ({ severity }: { severity: string }) => (
  <span className={`badge badge--${severity.toLowerCase()}`}>{severity}</span>
);

const fmt = (dt: string) => new Date(dt).toLocaleString();

export default function Incidents() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    fetchIncidents({ limit: 100, status: statusFilter || undefined })
      .then(setIncidents)
      .catch(() => setIncidents([]))
      .finally(() => setLoading(false));
  }, [statusFilter]);

  const statuses = ['', 'DETECTED', 'INVESTIGATING', 'DIAGNOSED', 'AWAITING_APPROVAL', 'REMEDIATING', 'VERIFYING', 'RESOLVED', 'FAILED'];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Incidents</h1>
        <p className="page-sub">All incidents detected by Aegis</p>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {statuses.map(s => (
          <button
            key={s}
            className={`btn ${statusFilter === s ? 'btn--primary' : 'btn--ghost'}`}
            style={{ padding: '6px 14px', fontSize: 13 }}
            onClick={() => { setLoading(true); setStatusFilter(s); }}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      <div className="card">
        {loading ? (
          <div className="loading">Loading incidents…</div>
        ) : incidents.length === 0 ? (
          <div className="empty">
            <div className="empty__icon">🎉</div>
            <div className="empty__text">No incidents match this filter</div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Service</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Confidence</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map(inc => (
                  <tr key={inc.id} onClick={() => navigate(`/incidents/${inc.id}`)}>
                    <td><code style={{ fontSize: 11, color: 'var(--text-muted)' }}>{inc.id.slice(0, 8)}…</code></td>
                    <td style={{ maxWidth: 280 }}>{inc.title}</td>
                    <td><code style={{ background: 'var(--surface-2)', padding: '2px 8px', borderRadius: 4, fontSize: 12 }}>{inc.service}</code></td>
                    <td><SeverityBadge severity={inc.severity} /></td>
                    <td><StatusBadge status={inc.status} /></td>
                    <td>
                      {inc.confidence !== null ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 100 }}>
                          <div style={{ flex: 1, height: 4, background: 'var(--surface-2)', borderRadius: 2 }}>
                            <div style={{ width: `${(inc.confidence * 100).toFixed(0)}%`, height: '100%', background: 'var(--green)', borderRadius: 2 }} />
                          </div>
                          <span style={{ fontSize: 12, color: 'var(--green)' }}>{(inc.confidence * 100).toFixed(0)}%</span>
                        </div>
                      ) : '—'}
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{fmt(inc.created_at)}</td>
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
