import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Activity, Cpu, GitBranch, Shield } from 'lucide-react';
import { fetchIncident, type IncidentDetail } from '../api';

const StatusBadge = ({ status }: { status: string }) => (
  <span className={`badge badge--${status.toLowerCase()}`}>{status}</span>
);

const RiskBadge = ({ risk }: { risk: string }) => {
  const map: Record<string, string> = { LOW: 'low', MEDIUM: 'medium', HIGH: 'high', FORBIDDEN: 'forbidden' };
  return <span className={`badge badge--${map[risk] || 'medium'}`}>{risk}</span>;
};

const fmtFull = (dt: string | null) => dt ? new Date(dt).toLocaleString() : '—';

const TIMELINE_ICONS: Record<string, string> = {
  INCIDENT_CREATED: '🚨',
  ALERT_CORRELATED: '🔗',
  INVESTIGATION_STARTED: '🔍',
  RCA_COMPLETED: '🧠',
  AWAITING_APPROVAL: '⏳',
  APPROVAL_REQUESTED: '🔔',
  REMEDIATION_EXECUTED: '⚡',
  AUTO_REMEDIATED: '⚡',
  VERIFICATION_COMPLETED: '✅',
  STATUS_CHANGED: '🔄',
  POLICY_REJECTED: '🛡️',
};

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (!id) return;
    const load = () =>
      fetchIncident(id)
        .then(setDetail)
        .catch(() => {})
        .finally(() => setLoading(false));
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [id]);

  if (loading) return <div className="loading">Loading incident…</div>;
  if (!detail) return <div className="empty"><div className="empty__text">Incident not found</div></div>;

  const { incident, timeline, investigations, remediation_plans } = detail;
  const latestInv = investigations[investigations.length - 1];
  const latestPlan = remediation_plans[remediation_plans.length - 1];

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 28 }}>
        <button className="btn btn--ghost" style={{ padding: '8px 12px' }} onClick={() => navigate('/incidents')}>
          <ArrowLeft size={16} />
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <StatusBadge status={incident.status} />
            <span className={`badge badge--${incident.severity.toLowerCase()}`}>{incident.severity}</span>
            <code style={{ fontSize: 11, color: 'var(--text-muted)', background: 'var(--surface-2)', padding: '2px 8px', borderRadius: 4 }}>
              {incident.id.slice(0, 8)}
            </code>
          </div>
          <h1 className="page-title">{incident.title}</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
            <strong style={{ color: 'var(--text-dim)' }}>{incident.service}</strong> · {incident.namespace} · Created {fmtFull(incident.created_at)}
            {incident.resolved_at && ` · Resolved ${fmtFull(incident.resolved_at)}`}
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20 }}>
        {/* Left column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* Timeline */}
          <div className="card">
            <div className="card__title">
              <Activity size={14} style={{ display: 'inline', marginRight: 6 }} />
              Incident Timeline
            </div>
            <div className="timeline">
              {timeline.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>No timeline events yet</div>
              ) : timeline.map((ev, i) => (
                <div key={ev.id} className="timeline-item">
                  <div className={`timeline-dot ${i === timeline.length - 1 ? 'timeline-dot--active' : ''}`}>
                    <span style={{ fontSize: 10 }}>{TIMELINE_ICONS[ev.event_type] || '•'}</span>
                  </div>
                  <div className="timeline-content">
                    <div className="timeline-event-type">{ev.event_type.replace(/_/g, ' ')}</div>
                    <div className="timeline-desc">{ev.description}</div>
                    <div className="timeline-time">{fmtFull(ev.created_at)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* AI Investigation */}
          {latestInv && (
            <div className="card">
              <div className="card__title">
                <Cpu size={14} style={{ display: 'inline', marginRight: 6 }} />
                AI Root Cause Analysis
              </div>
              <div className="rca-card" style={{ padding: 0, border: 'none', background: 'transparent' }}>
                {latestInv.root_cause && (
                  <>
                    <div className="rca-root-cause">{latestInv.root_cause}</div>
                    {latestInv.confidence !== null && (
                      <div className="confidence-bar" style={{ marginBottom: 16 }}>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 70 }}>Confidence</span>
                        <div className="confidence-bar__track">
                          <div className="confidence-bar__fill" style={{ width: `${(latestInv.confidence * 100).toFixed(0)}%` }} />
                        </div>
                        <div className="confidence-bar__value">{(latestInv.confidence * 100).toFixed(0)}%</div>
                      </div>
                    )}
                  </>
                )}
                {latestInv.reasoning_steps.length > 0 && (
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      Reasoning Steps
                    </div>
                    <div className="rca-steps">
                      {latestInv.reasoning_steps.map((step, i) => (
                        <div key={i} className="rca-step">
                          <div className="rca-step-num">{i + 1}</div>
                          <div>{step}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                  Tokens used: {latestInv.llm_tokens_used} ·
                  Duration: {latestInv.duration_seconds ? `${latestInv.duration_seconds.toFixed(1)}s` : 'N/A'}
                </div>
              </div>
            </div>
          )}

          {/* Remediation Plan */}
          {latestPlan && (
            <div className="card">
              <div className="card__title">
                <Shield size={14} style={{ display: 'inline', marginRight: 6 }} />
                Remediation Plan
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>ACTION</div>
                    <code style={{ background: 'var(--surface-2)', padding: '4px 10px', borderRadius: 6, fontSize: 13 }}>{latestPlan.action}</code>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>TARGET</div>
                    <code style={{ background: 'var(--surface-2)', padding: '4px 10px', borderRadius: 6, fontSize: 13 }}>{latestPlan.target}</code>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>RISK</div>
                    <RiskBadge risk={latestPlan.risk_level} />
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>STATUS</div>
                    <StatusBadge status={latestPlan.status} />
                  </div>
                </div>
                <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '12px 16px' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>REASON</div>
                  <div style={{ fontSize: 14 }}>{latestPlan.reason}</div>
                </div>
                {latestPlan.requires_approval && latestPlan.status === 'PROPOSED' && (
                  <div style={{ padding: '12px 16px', background: 'rgba(234,179,8,0.1)', border: '1px solid rgba(234,179,8,0.3)', borderRadius: 8, fontSize: 14, color: '#facc15' }}>
                    ⏳ This action requires human approval. Visit the <a href="/approvals" style={{ color: '#facc15' }}>Approvals</a> page to review.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Metadata */}
          <div className="card">
            <div className="card__title">Metadata</div>
            {[
              ['Service', incident.service],
              ['Namespace', incident.namespace],
              ['Severity', incident.severity],
              ['Status', incident.status],
              ['Correlation ID', incident.correlation_id.slice(0, 12) + '…'],
              ['Alert Count', incident.alert_ids.length.toString()],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
                <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                <span style={{ color: 'var(--text)', fontWeight: 500 }}>{v}</span>
              </div>
            ))}
          </div>

          {/* Service Dependency */}
          <div className="card">
            <div className="card__title">
              <GitBranch size={14} style={{ display: 'inline', marginRight: 6 }} />
              Dependencies
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {incident.service === 'checkout' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ color: 'var(--accent)', fontWeight: 600 }}>checkout</div>
                  <div style={{ paddingLeft: 16 }}>→ payment → <span style={{ color: 'var(--text-muted)' }}>postgres</span></div>
                  <div style={{ paddingLeft: 16 }}>→ inventory → <span style={{ color: 'var(--text-muted)' }}>redis</span></div>
                </div>
              )}
              {incident.service === 'payment' && (
                <div>
                  checkout → <span style={{ color: 'var(--accent)', fontWeight: 600 }}>payment</span> → postgres
                </div>
              )}
              {incident.service === 'inventory' && (
                <div>
                  checkout → <span style={{ color: 'var(--accent)', fontWeight: 600 }}>inventory</span> → redis
                </div>
              )}
              {!['checkout', 'payment', 'inventory'].includes(incident.service) && (
                <div>No dependency graph available</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
