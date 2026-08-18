import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Sparkles,
  Shield,
  Activity,
  CheckCircle,
  XCircle,
  GitBranch,
  Clock,
  FileText
} from 'lucide-react';
import {
  fetchIncident,
  fetchPendingApprovals,
  submitApproval,
  type IncidentDetail,
  type PendingApproval
} from '../api';

const fmtFull = (dt: string | null) => (dt ? new Date(dt).toLocaleString() : '—');

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

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const load = () => {
    if (!id) return;
    fetchIncident(id)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoading(false));

    fetchPendingApprovals()
      .then((apps) => {
        const found = apps.find((a) => a.incident_id === id);
        setPendingApproval(found || null);
      })
      .catch(() => setPendingApproval(null));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 3000);
    return () => clearInterval(interval);
  }, [id]);

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    if (!pendingApproval) return;
    setSubmitting(true);
    try {
      await submitApproval(
        pendingApproval.approval_id,
        decision,
        'sre-lead@aegis.corp',
        `Decision: ${decision} from Apple SRE Console`
      );
      setPendingApproval(null);
      load();
    } catch {
      alert(`Failed to submit ${decision} decision. Please try again.`);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="apple-loading">
        <div className="apple-spinner" />
        <span>Loading incident details…</span>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="apple-empty">
        <div className="apple-empty__icon">🔍</div>
        <div className="apple-empty__title">Incident Not Found</div>
        <button className="apple-btn apple-btn--glass" onClick={() => navigate('/incidents')}>
          Back to Incidents
        </button>
      </div>
    );
  }

  const { incident, timeline, investigations, remediation_plans } = detail;
  const latestInv = investigations[investigations.length - 1];
  const latestPlan = remediation_plans[remediation_plans.length - 1];

  return (
    <div>
      {/* Header Bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 28 }}>
        <button
          className="apple-btn apple-btn--glass"
          style={{ padding: '8px 14px' }}
          onClick={() => navigate('/incidents')}
        >
          <ArrowLeft size={16} />
          Back
        </button>

        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <span className={`apple-badge apple-badge--dot ${getStatusBadgeClass(incident.status)}`}>
              {incident.status}
            </span>
            <span className={`apple-badge ${getSeverityBadgeClass(incident.severity)}`}>
              {incident.severity.toUpperCase()}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>
              ID: {incident.id}
            </span>
          </div>
          <h1 className="page-hero__title" style={{ fontSize: 26 }}>
            {incident.title}
          </h1>
        </div>
      </div>

      {/* 2-Column Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
        {/* Main Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* AI Root Cause Analysis (Apple Intelligence Card) */}
          <div
            className="glass-card"
            style={{
              background: 'radial-gradient(circle at 100% 0%, rgba(191, 90, 242, 0.12) 0%, rgba(15, 20, 32, 0.8) 70%)',
              borderColor: 'rgba(191, 90, 242, 0.35)',
              boxShadow: '0 8px 32px rgba(191, 90, 242, 0.15)',
            }}
          >
            <div className="card-header" style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Sparkles size={18} style={{ color: 'var(--apple-purple)' }} />
                <span style={{ fontSize: 15, fontWeight: 700, color: '#fff' }}>
                  AI Root Cause Analysis
                </span>
              </div>
              <div
                style={{
                  background: 'rgba(191, 90, 242, 0.18)',
                  border: '1px solid rgba(191, 90, 242, 0.4)',
                  padding: '4px 10px',
                  borderRadius: 'var(--radius-pill)',
                  fontSize: 11,
                  fontWeight: 700,
                  color: 'var(--apple-purple)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Sparkles size={12} />
                Google Gemini 1.5 Flash
              </div>
            </div>

            {latestInv ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {latestInv.root_cause && (
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 }}>
                      Diagnosed Root Cause
                    </div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
                      {latestInv.root_cause}
                    </div>
                  </div>
                )}

                {latestInv.confidence !== null && (
                  <div style={{ background: 'rgba(255, 255, 255, 0.04)', borderRadius: 'var(--radius-sm)', padding: '12px 16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 12 }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Diagnostic Confidence</span>
                      <span style={{ fontWeight: 700, color: 'var(--apple-green)' }}>
                        {(latestInv.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div style={{ width: '100%', height: 6, background: 'rgba(255, 255, 255, 0.1)', borderRadius: 3 }}>
                      <div
                        style={{
                          width: `${(latestInv.confidence * 100).toFixed(0)}%`,
                          height: '100%',
                          background: 'linear-gradient(90deg, #30d158 0%, #64d2ff 100%)',
                          borderRadius: 3,
                        }}
                      />
                    </div>
                  </div>
                )}

                {latestInv.reasoning_steps && latestInv.reasoning_steps.length > 0 && (
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>
                      Reasoning Steps
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {latestInv.reasoning_steps.map((step, idx) => (
                        <div
                          key={idx}
                          style={{
                            display: 'flex',
                            gap: 12,
                            background: 'rgba(255, 255, 255, 0.03)',
                            padding: '10px 14px',
                            borderRadius: 'var(--radius-sm)',
                            border: '1px solid var(--border-subtle)',
                            fontSize: 13,
                          }}
                        >
                          <span
                            style={{
                              width: 20,
                              height: 20,
                              borderRadius: '50%',
                              background: 'rgba(191, 90, 242, 0.2)',
                              color: 'var(--apple-purple)',
                              fontSize: 11,
                              fontWeight: 700,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              flexShrink: 0,
                            }}
                          >
                            {idx + 1}
                          </span>
                          <span style={{ color: 'var(--text-primary)', lineHeight: 1.5 }}>{step}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', display: 'flex', gap: 16 }}>
                  <span>Tokens used: <strong>{latestInv.llm_tokens_used || 245}</strong></span>
                  <span>Duration: <strong>{latestInv.duration_seconds ? `${latestInv.duration_seconds.toFixed(2)}s` : '0.8s'}</strong></span>
                </div>
              </div>
            ) : (
              <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>Investigation in progress…</div>
            )}
          </div>

          {/* Remediation Plan & Approval Card */}
          {latestPlan && (
            <div className="glass-card">
              <div className="card-header">
                <div className="card-header__title">
                  <Shield size={17} style={{ color: 'var(--apple-blue)' }} />
                  Proposed Remediation Plan
                </div>
                <span className={`apple-badge ${latestPlan.risk_level === 'HIGH' ? 'badge-critical' : 'badge-warning'}`}>
                  {latestPlan.risk_level} RISK
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px 14px', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>ACTION</div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{latestPlan.action}</div>
                  </div>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px 14px', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>TARGET</div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{latestPlan.target}</div>
                  </div>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px 14px', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>STATUS</div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{latestPlan.status}</div>
                  </div>
                </div>

                <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '12px 16px', borderRadius: 'var(--radius-sm)', fontSize: 13 }}>
                  <span style={{ color: 'var(--text-tertiary)' }}>Rationale: </span>
                  <span style={{ color: 'var(--text-primary)' }}>{latestPlan.reason}</span>
                </div>

                {/* Inline Human Approval Gate */}
                {pendingApproval && (
                  <div
                    style={{
                      background: 'rgba(255, 214, 10, 0.08)',
                      border: '1px solid rgba(255, 214, 10, 0.35)',
                      borderRadius: 'var(--radius-md)',
                      padding: '20px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 14,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--apple-yellow)', fontWeight: 700, fontSize: 15 }}>
                      <Clock size={18} />
                      Human Approval Required to Proceed
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                      The AI agent proposed <strong>{pendingApproval.action}</strong> on <strong>{pendingApproval.target}</strong>.
                      Click below to authorize immediate Kubernetes execution.
                    </div>

                    <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
                      <button
                        className="apple-btn apple-btn--success"
                        disabled={submitting}
                        onClick={() => handleDecision('approved')}
                      >
                        <CheckCircle size={16} />
                        {submitting ? 'Authorizing…' : 'Approve Remediation'}
                      </button>
                      <button
                        className="apple-btn apple-btn--danger"
                        disabled={submitting}
                        onClick={() => handleDecision('rejected')}
                      >
                        <XCircle size={16} />
                        Reject Plan
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Incident Timeline */}
          <div className="glass-card">
            <div className="card-header">
              <div className="card-header__title">
                <Activity size={17} style={{ color: 'var(--apple-blue)' }} />
                Incident Lifecycle Timeline
              </div>
              <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                {timeline.length} Recorded Milestones
              </span>
            </div>

            <div className="timeline-stepper">
              {timeline.map((ev) => (
                <div key={ev.id} className="timeline-step">
                  <div className="timeline-step__marker">
                    <span>{TIMELINE_ICONS[ev.event_type] || '•'}</span>
                  </div>
                  <div className="timeline-step__card">
                    <div className="timeline-step__header">
                      <span className="timeline-step__type">
                        {ev.event_type.replace(/_/g, ' ')}
                      </span>
                      <span className="timeline-step__time">
                        {fmtFull(ev.created_at)}
                      </span>
                    </div>
                    <div className="timeline-step__desc">
                      {ev.description}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Metadata Sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Metadata Card */}
          <div className="glass-card">
            <div className="card-header">
              <div className="card-header__title">
                <FileText size={16} style={{ color: 'var(--apple-blue)' }} />
                Incident Metadata
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
              {[
                ['Service', incident.service],
                ['Namespace', incident.namespace],
                ['Severity', incident.severity.toUpperCase()],
                ['Status', incident.status],
                ['Correlation ID', incident.correlation_id.slice(0, 12) + '…'],
                ['Alert Count', incident.alert_ids.length.toString()],
                ['Created', fmtFull(incident.created_at)],
                ['Resolved', fmtFull(incident.resolved_at)],
              ].map(([k, v]) => (
                <div
                  key={k}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    padding: '8px 0',
                    borderBottom: '1px solid var(--border-subtle)',
                  }}
                >
                  <span style={{ color: 'var(--text-tertiary)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Topology Dependency Graph */}
          <div className="glass-card">
            <div className="card-header">
              <div className="card-header__title">
                <GitBranch size={16} style={{ color: 'var(--apple-cyan)' }} />
                Service Dependency Tree
              </div>
            </div>

            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
              {incident.service === 'checkout' && (
                <div>
                  <div style={{ color: 'var(--apple-blue)', fontWeight: 700 }}>checkout (edge)</div>
                  <div style={{ paddingLeft: 16 }}>↳ payment ➔ <span style={{ color: 'var(--text-tertiary)' }}>postgres</span></div>
                  <div style={{ paddingLeft: 16 }}>↳ inventory ➔ <span style={{ color: 'var(--text-tertiary)' }}>redis</span></div>
                </div>
              )}
              {incident.service === 'payment' && (
                <div>
                  <div style={{ color: 'var(--text-tertiary)' }}>checkout (upstream caller)</div>
                  <div style={{ paddingLeft: 16 }}>
                    ↳ <span style={{ color: 'var(--apple-purple)', fontWeight: 700 }}>payment (impacted)</span> ➔ postgres:5432
                  </div>
                </div>
              )}
              {incident.service === 'inventory' && (
                <div>
                  <div style={{ color: 'var(--text-tertiary)' }}>checkout (upstream caller)</div>
                  <div style={{ paddingLeft: 16 }}>
                    ↳ <span style={{ color: 'var(--apple-cyan)', fontWeight: 700 }}>inventory (impacted)</span> ➔ redis:6379
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
