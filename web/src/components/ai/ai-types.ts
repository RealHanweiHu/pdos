export const FINDING_TYPES = [
  "risk_suggestion",
  "blocker_alert",
  "gate_readiness_anomaly",
  "knowledge_draft",
  "bom_impact_suggestion",
  "change_impact_suggestion",
  "quality_cluster_alert",
  "capa_suggestion",
] as const;

export const FINDING_STATUSES = [
  "pending_review",
  "accepted",
  "rejected",
  "applied",
] as const;

export type FindingType = (typeof FINDING_TYPES)[number];
export type FindingStatus = (typeof FINDING_STATUSES)[number];

export type FindingEvidence = {
  event_row_id: number;
  label: string;
  href: string;
};

export type AiFinding = {
  id: string;
  project_id: string;
  run_id: string;
  model_invocation_id: string;
  agent_key: string;
  finding_type: FindingType;
  origin_key: string;
  status: FindingStatus;
  title: string;
  summary: string;
  proposed_payload: Record<string, unknown>;
  accepted_payload: Record<string, unknown> | null;
  evidence_event_ids: number[];
  evidence: FindingEvidence[];
  confidence_basis_points: number;
  preflight_version: string;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  applied_by_user_id: string | null;
  applied_at: string | null;
  applied_entity_type: string | null;
  applied_entity_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AiBriefItem = {
  finding_id: string;
  project_id: string;
  finding_type: FindingType;
  finding_status: FindingStatus;
  title: string;
  summary: string;
  evidence: FindingEvidence[];
  created_at: string;
  href: string;
};

export type AiBrief = {
  status: "active" | "unavailable";
  error_code: string | null;
  pending_review_count: number;
  latest_finding_at: string | null;
  reviewed_count: number;
  accepted_count: number;
  applied_count: number;
  acceptance_rate_basis_points: number | null;
  narrowed_output_count: number;
  quality_controls: AiQualityControl[];
  items: AiBriefItem[];
};

export type AiQualityControl = {
  agent_key: string;
  finding_type: FindingType;
  status: "active" | "narrowed";
  minimum_review_count: number;
  acceptance_threshold_basis_points: number;
  reviewed_count: number;
  accepted_count: number;
  applied_count: number;
  acceptance_rate_basis_points: number | null;
  narrowed_at: string | null;
  narrowed_reason: string | null;
};

export type ChatCitation = {
  reference_id: string;
  entity: string;
  entity_id: string;
  label: string;
  href: string;
  excerpt: string;
};

export type AiChatResponse = {
  status: "answered" | "insufficient_evidence" | "unavailable";
  answer: string | null;
  citations: ChatCitation[];
  error_code: string | null;
};
