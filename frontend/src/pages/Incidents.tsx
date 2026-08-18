import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, ArrowRight } from 'lucide-react';
import { fetchIncidents, type Incident } from '../api';

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

export default function Incidents() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    fetchIncidents({ limit: 100, status: statusFilter || undefined })
      .then(setIncidents)
      .catch(() => setIncidents([]))
      .finally(() => setLoading(false));
  }, [statusFilter]);

  const filteredIncidents = incidents.filter(i => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      i.title.toLowerCase().includes(q) ||
      i.service.toLowerCase().includes(q) ||
      i.namespace.toLowerCase().includes(q) ||
      (i.root_cause && i.root_cause.toLowerCase().includes(q))
    );
  });

  const filterTabs = [
    { label: 'All', value: '' },
    { label: 'Awaiting Approval', value: 'AWAITING_APPROVAL' },
    { label: 'Investigating', value: 'INVESTIGATING' },
    { label: 'Resolved', value: 'RESOLVED' },
    { label: 'Failed', value: 'FAILED' },
  ];

  return (
    <div>
      {/* Header */}
      <div className="page-hero">
        <div>
          <h1 className="page-hero__title">Incident Center</h1>
          <p className="page-hero__subtitle">Real-time correlated failures, AI root-cause diagnostics, and remediation states</p>
        </div>
      </div>

      {/* Control Bar: Segmented filter + Search */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        <div className="segmented-control">
          {filterTabs.map(tab => (
            <button
              key={tab.value}
              className={`segmented-btn ${statusFilter === tab.value ? 'segmented-btn--active' : ''}`}
              onClick={() => {
                setLoading(true);
                setStatusFilter(tab.value);
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Apple Glass Search Input */}
        <div style={{ position: 'relative', minWidth: 260 }}>
          <Search size={15} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-tertiary)' }} />
          <input
            type="text"
            placeholder="Filter by service, root cause..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid var(--border-glass)',
              borderRadius: 'var(--radius-pill)',
              padding: '8px 16px 8px 36px',
              fontSize: 13,
              color: 'var(--text-primary)',
              outline: 'none',
              transition: 'all var(--transition-fast)',
            }}
          />
        </div>
      </div>

      {/* Incident List */}
      <div className="glass-card">
        {loading ? (
          <div className="apple-loading">
            <div className="apple-spinner" />
            <span>Loading incidents…</span>
          </div>
        ) : filteredIncidents.length === 0 ? (
          <div className="apple-empty">
            <div className="apple-empty__icon">✨</div>
            <div className="apple-empty__title">No Incidents Found</div>
            <div className="apple-empty__desc">No incident records matched the active filter or query.</div>
          </div>
        ) : (
          <div className="incident-list">
            {filteredIncidents.map(inc => (
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
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>
                      ID: {inc.id.slice(0, 8)}
                    </span>
                    <span>•</span>
                    <span>Service: <strong>{inc.service}</strong></span>
                    <span>•</span>
                    <span>Namespace: <strong>{inc.namespace}</strong></span>
                    {inc.root_cause && (
                      <>
                        <span>•</span>
                        <span style={{ color: 'var(--apple-purple)' }}>
                          RCA: {inc.root_cause}
                        </span>
                      </>
                    )}
                  </div>
                </div>

                <div className="incident-row__right">
                  {inc.confidence !== null && (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, minWidth: 80 }}>
                      <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Confidence</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ width: 44, height: 4, background: 'rgba(255, 255, 255, 0.1)', borderRadius: 2 }}>
                          <div style={{ width: `${(inc.confidence * 100).toFixed(0)}%`, height: '100%', background: 'var(--apple-green)', borderRadius: 2 }} />
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--apple-green)' }}>
                          {(inc.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  )}

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
