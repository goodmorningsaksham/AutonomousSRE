import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCircle, XCircle, ExternalLink } from 'lucide-react';
import { fetchPendingApprovals, submitApproval, type PendingApproval } from '../api';

const RiskBadge = ({ risk }: { risk: string }) => {
  const map: Record<string, string> = { LOW: 'low', MEDIUM: 'medium', HIGH: 'high', FORBIDDEN: 'forbidden' };
  return <span className={`badge badge--${map[risk] || 'medium'}`}>{risk}</span>;
};

const fmt = (dt: string) => new Date(dt).toLocaleString();

interface ApprovalModal {
  approval: PendingApproval;
  decision: 'approved' | 'rejected';
}

export default function Approvals() {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<ApprovalModal | null>(null);
  const [approvedBy, setApprovedBy] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const load = async () => {
    fetchPendingApprovals().then(setApprovals).catch(() => setApprovals([])).finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const openModal = (approval: PendingApproval, decision: 'approved' | 'rejected') => {
    setModal({ approval, decision });
    setApprovedBy('');
    setNotes('');
  };

  const handleSubmit = async () => {
    if (!modal || !approvedBy.trim()) return;
    setSubmitting(true);
    try {
      await submitApproval(modal.approval.approval_id, modal.decision, approvedBy.trim(), notes);
      setModal(null);
      await load();
    } catch (e) {
      alert('Failed to submit approval decision. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Pending Approvals</h1>
        <p className="page-sub">Remediation actions requiring human review before execution</p>
      </div>

      {loading ? (
        <div className="loading">Loading approvals…</div>
      ) : approvals.length === 0 ? (
        <div className="empty">
          <div className="empty__icon">✅</div>
          <div className="empty__text">No pending approvals</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {approvals.map(ap => (
            <div key={ap.approval_id} className="card" style={{ border: '1px solid rgba(234,179,8,0.3)' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                    <Bell size={16} style={{ color: 'var(--yellow)' }} />
                    <span style={{ fontWeight: 600, fontSize: 16 }}>{ap.action}</span>
                    <RiskBadge risk={ap.risk_level} />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 14 }}>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>TARGET</div>
                      <code style={{ fontSize: 13 }}>{ap.target}</code>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>NAMESPACE</div>
                      <code style={{ fontSize: 13 }}>{ap.namespace}</code>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>REQUESTED</div>
                      <span style={{ fontSize: 13 }}>{fmt(ap.requested_at)}</span>
                    </div>
                  </div>

                  <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: 'var(--text-dim)' }}>
                    {ap.reason}
                  </div>

                  <button
                    className="btn btn--ghost"
                    style={{ marginTop: 12, padding: '6px 12px', fontSize: 12 }}
                    onClick={() => navigate(`/incidents/${ap.incident_id}`)}
                  >
                    <ExternalLink size={13} />
                    View Incident
                  </button>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
                  <button
                    className="btn btn--primary"
                    onClick={() => openModal(ap, 'approved')}
                  >
                    <CheckCircle size={15} />
                    Approve
                  </button>
                  <button
                    className="btn btn--danger"
                    onClick={() => openModal(ap, 'rejected')}
                  >
                    <XCircle size={15} />
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Approval Modal */}
      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal__title">
              {modal.decision === 'approved' ? '✅ Approve Remediation' : '❌ Reject Remediation'}
            </div>
            <div className="modal__sub">
              {modal.decision === 'approved'
                ? `This will execute ${modal.approval.action} on ${modal.approval.target} in ${modal.approval.namespace}.`
                : `This will cancel the remediation for ${modal.approval.action} on ${modal.approval.target}.`
              }
            </div>

            <div className="form-group">
              <label htmlFor="approvedBy">Your name *</label>
              <input
                id="approvedBy"
                className="input"
                placeholder="e.g. jane.smith"
                value={approvedBy}
                onChange={e => setApprovedBy(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="notes">Notes (optional)</label>
              <textarea
                id="notes"
                className="input"
                style={{ resize: 'vertical', minHeight: 80 }}
                placeholder="Any relevant context..."
                value={notes}
                onChange={e => setNotes(e.target.value)}
              />
            </div>

            <div className="modal__actions">
              <button
                className={modal.decision === 'approved' ? 'btn btn--primary' : 'btn btn--danger'}
                disabled={submitting || !approvedBy.trim()}
                onClick={handleSubmit}
              >
                {submitting ? 'Submitting…' : modal.decision === 'approved' ? 'Confirm Approval' : 'Confirm Rejection'}
              </button>
              <button className="btn btn--ghost" onClick={() => setModal(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
