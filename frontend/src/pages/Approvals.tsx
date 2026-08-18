import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, XCircle, Clock, ArrowRight } from 'lucide-react';
import { fetchPendingApprovals, submitApproval, type PendingApproval } from '../api';

const fmt = (dt: string) => new Date(dt).toLocaleString();

interface ApprovalModal {
  approval: PendingApproval;
  decision: 'approved' | 'rejected';
}

export default function Approvals() {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<ApprovalModal | null>(null);
  const [approvedBy, setApprovedBy] = useState('sre-lead@aegis.corp');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const load = async () => {
    fetchPendingApprovals()
      .then(setApprovals)
      .catch(() => setApprovals([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  const openModal = (approval: PendingApproval, decision: 'approved' | 'rejected') => {
    setModal({ approval, decision });
    setApprovedBy('sre-lead@aegis.corp');
    setNotes(`Authorized via Apple SRE Gate at ${new Date().toLocaleTimeString()}`);
  };

  const handleSubmit = async () => {
    if (!modal || !approvedBy.trim()) return;
    setSubmitting(true);
    try {
      await submitApproval(modal.approval.approval_id, modal.decision, approvedBy.trim(), notes);
      setModal(null);
      await load();
    } catch {
      alert('Failed to submit approval decision. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      {/* Header */}
      <div className="page-hero">
        <div>
          <h1 className="page-hero__title">Approval Gate</h1>
          <p className="page-hero__subtitle">Human-in-the-loop verification for critical remediation workflows</p>
        </div>
      </div>

      {loading ? (
        <div className="apple-loading">
          <div className="apple-spinner" />
          <span>Polling pending approvals…</span>
        </div>
      ) : approvals.length === 0 ? (
        <div className="glass-card">
          <div className="apple-empty">
            <div className="apple-empty__icon">✅</div>
            <div className="apple-empty__title">No Pending Approvals</div>
            <div className="apple-empty__desc">All automated remediation plans have completed or been resolved.</div>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {approvals.map((ap) => (
            <div
              key={ap.approval_id}
              className="glass-card"
              style={{
                borderColor: 'rgba(255, 214, 10, 0.35)',
                background: 'radial-gradient(circle at 100% 0%, rgba(255, 214, 10, 0.08) 0%, rgba(15, 20, 32, 0.8) 70%)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 20 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 'var(--radius-sm)',
                        background: 'rgba(255, 214, 10, 0.15)',
                        color: 'var(--apple-yellow)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <Clock size={18} />
                    </div>
                    <span style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {ap.action}
                    </span>
                    <span className={`apple-badge ${ap.risk_level === 'HIGH' ? 'badge-critical' : 'badge-warning'}`}>
                      {ap.risk_level} RISK
                    </span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 16 }}>
                    <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px 14px', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>TARGET SERVICE</div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--apple-blue)' }}>{ap.target}</div>
                    </div>
                    <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px 14px', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>NAMESPACE</div>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{ap.namespace}</div>
                    </div>
                    <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px 14px', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>REQUESTED AT</div>
                      <div style={{ fontSize: 13 }}>{fmt(ap.requested_at)}</div>
                    </div>
                  </div>

                  <div
                    style={{
                      background: 'rgba(255, 255, 255, 0.03)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '12px 16px',
                      fontSize: 13,
                      color: 'var(--text-secondary)',
                      marginBottom: 16,
                    }}
                  >
                    <span style={{ color: 'var(--text-tertiary)' }}>AI Rationale: </span>
                    {ap.reason}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <button
                      className="apple-btn apple-btn--success"
                      onClick={() => openModal(ap, 'approved')}
                    >
                      <CheckCircle2 size={16} />
                      Approve Remediation
                    </button>
                    <button
                      className="apple-btn apple-btn--danger"
                      onClick={() => openModal(ap, 'rejected')}
                    >
                      <XCircle size={16} />
                      Reject
                    </button>
                    <button
                      className="apple-btn apple-btn--glass"
                      style={{ marginLeft: 'auto' }}
                      onClick={() => navigate(`/incidents/${ap.incident_id}`)}
                    >
                      View Incident Detail
                      <ArrowRight size={14} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confirmation Modal */}
      {modal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(12px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
          }}
        >
          <div
            className="glass-card"
            style={{
              width: 480,
              maxWidth: '90vw',
              boxShadow: '0 24px 64px rgba(0, 0, 0, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.18)',
            }}
          >
            <div className="card-header">
              <div className="card-header__title" style={{ fontSize: 17 }}>
                {modal.decision === 'approved' ? 'Confirm Remediation Approval' : 'Reject Remediation Plan'}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 24 }}>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                You are about to <strong>{modal.decision.toUpperCase()}</strong> execution of{' '}
                <strong>{modal.approval.action}</strong> on <strong>{modal.approval.target}</strong>.
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-tertiary)', display: 'block', marginBottom: 6 }}>
                  SRE Signer Email
                </label>
                <input
                  type="email"
                  value={approvedBy}
                  onChange={(e) => setApprovedBy(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '10px 14px',
                    fontSize: 13,
                    color: '#fff',
                    outline: 'none',
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-tertiary)', display: 'block', marginBottom: 6 }}>
                  Decision Audit Notes
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  style={{
                    width: '100%',
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '10px 14px',
                    fontSize: 13,
                    color: '#fff',
                    outline: 'none',
                    resize: 'none',
                  }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
              <button
                className="apple-btn apple-btn--glass"
                onClick={() => setModal(null)}
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                className={modal.decision === 'approved' ? 'apple-btn apple-btn--success' : 'apple-btn apple-btn--danger'}
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting…' : modal.decision === 'approved' ? 'Authorize & Execute' : 'Reject Action'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
