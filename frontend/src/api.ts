import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({ baseURL: API_BASE, timeout: 10000 });

export interface Incident {
  id: string;
  title: string;
  service: string;
  namespace: string;
  severity: string;
  status: string;
  root_cause: string | null;
  confidence: number | null;
  correlation_id: string;
  alert_ids: string[];
  labels: Record<string, string>;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface TimelineEvent {
  id: string;
  event_type: string;
  description: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface Investigation {
  id: string;
  status: string;
  root_cause: string | null;
  confidence: number | null;
  suspected_component: string | null;
  reasoning_steps: string[];
  recommended_actions: Record<string, unknown>[];
  llm_tokens_used: number;
  duration_seconds: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface RemediationPlan {
  id: string;
  action: string;
  namespace: string;
  target: string;
  parameters: Record<string, unknown>;
  reason: string;
  risk_level: string;
  requires_approval: boolean;
  status: string;
  policy_allowed: boolean | null;
  proposed_at: string | null;
}

export interface IncidentDetail {
  incident: Incident;
  timeline: TimelineEvent[];
  investigations: Investigation[];
  remediation_plans: RemediationPlan[];
}

export interface PendingApproval {
  approval_id: string;
  plan_id: string;
  incident_id: string;
  action: string;
  target: string;
  namespace: string;
  risk_level: string;
  reason: string;
  requested_at: string;
}

export interface Stats {
  incidents_by_status: Record<string, number>;
  total: number;
}

export const fetchIncidents = (params?: { status?: string; service?: string; limit?: number }) =>
  api.get<Incident[]>('/api/v1/incidents', { params }).then(r => r.data);

export const fetchIncident = (id: string) =>
  api.get<IncidentDetail>(`/api/v1/incidents/${id}`).then(r => r.data);

export const fetchPendingApprovals = () =>
  api.get<PendingApproval[]>('/api/v1/approvals/pending').then(r => r.data);

export const submitApproval = (approvalId: string, decision: 'approved' | 'rejected', approvedBy: string, notes?: string) =>
  api.post(`/api/v1/approvals/${approvalId}/approve`, { decision, approved_by: approvedBy, notes: notes || '' }).then(r => r.data);

export const fetchStats = () =>
  api.get<Stats>('/api/v1/stats').then(r => r.data);
