export const FINDING_TYPES = [
  "risk_suggestion",
  "blocker_alert",
  "gate_readiness_anomaly",
  "knowledge_draft",
  "meeting_minutes", "meeting_action", "meeting_decision", "meeting_issue", "meeting_risk", "meeting_change",
  "bom_impact_suggestion",
  "change_impact_suggestion",
  "change_work_package",
  "quality_cluster_alert",
  "capa_suggestion",
  "capa_work_package",
  "test_plan_change",
  "supplier_delay_risk",
  "supplier_recovery",
  "cost_reduction",
  "executive_portfolio_brief",
] as const;

export const FINDING_STATUSES = [
  "pending_review",
  "accepted",
  "rejected",
  "applied",
  "archived",
] as const;

export type FindingType = (typeof FINDING_TYPES)[number];
export type FindingStatus = (typeof FINDING_STATUSES)[number];

export type FindingEvidence = {
  event_row_id: number;
  label: string;
  href: string;
};

export type AiFinding = {
  review_undo_until?: string | null;
  superseded_by?: string | null;
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

export type AgentRunSummary = {
  id: string;
  agent_key: string;
  status: string;
  window_started_at: string;
  window_ended_at: string;
  event_count: number;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  created_at: string;
  can_cancel?: boolean;
  can_pause?: boolean;
  can_resume?: boolean;
  input_wait?: {
    id: string; finding_id: string; owner_user_id: string; questions: string[];
    summary: string; expires_at: string; resolved_at: string | null;
    resolution: string | null; continuation_run_id: string | null;
  } | null;
};

export type AgentRunList = {
  items: AgentRunSummary[];
  pending_review_findings: number;
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

export type AiChatOperation = {
  run_id: string;
  project_id: string;
  request_id: string;
  status: "queued" | "running" | "succeeded" | "degraded" | "failed" | "cancelled";
  result: AiChatResponse | null;
  error_code: string | null;
};

export const INBOX_ITEM_KINDS = ["finding", "risk_candidate", "import_batch"] as const;
export type InboxItemKind = (typeof INBOX_ITEM_KINDS)[number];

export type ReviewInboxItem = {
  kind: InboxItemKind;
  id: string;
  title: string;
  agent_key: string | null;
  finding_type: string | null;
  confidence_basis_points: number | null;
  quality_acceptance_basis_points: number | null;
  href: string;
  created_at: string;
};

export type ReviewInboxGroup = {
  project_id: string;
  project_name: string;
  items: ReviewInboxItem[];
};

export type ReviewInboxDigest = {
  groups: ReviewInboxGroup[];
  finding_count: number;
  risk_candidate_count: number;
  import_batch_count: number;
  archived_count: number;
};

export type AiCapability = {
  capability_key: string;
  agent_key: string;
  zone: "free" | "confirm" | "hard_gate";
  rollout: "live" | "shadow";
  prompt_version: string;
  finding_types: string[];
  projections: string[];
  tools: string[];
  quality_control: string;
  controls: AiQualityControl[];
};

export type AiTouchpoint = {
  key: string;
  label: string;
  state: "enabled" | "degraded" | "disabled";
  reason_code: string | null;
  manual_alternative: string;
};

export type AiUsageRow = {
  agent_key: string;
  prompt_version: string;
  invocation_count: number;
  succeeded_count: number;
  total_tokens: number;
};

export type AiUsage = {
  daily_token_budget: number | null;
  used_tokens_today: number | null;
  remaining_tokens_today: number | null;
  budget_exhausted: boolean;
  rows: AiUsageRow[];
};

export type RiskCandidate = {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  likelihood: number;
  impact: number;
  score: number;
  created_at: string;
  updated_at?: string;
};


export type AgentRunProgress = {
  run_id: string; status: string; phase: string; as_of: string; stop_code: string | null;
  saved_tool_steps: number; tool_dispatches: number; observations: number;
  model_receipts: number; saved_results: number; last_tool: string | null;
  budget: {
    lineage_id: string; token_limit: number; charged_tokens: number; held_tokens: number;
    remaining_tokens: number; unresolved_calls: number; active_seconds: number | null;
    active_limit_seconds: number; remaining_active_seconds: number | null;
    absolute_deadline: string; priced_model_cost_microusd: number; model_cost_complete: boolean;
  } | null;
};

export const FINDING_TYPE_LABELS: Record<FindingType, string> = {
  risk_suggestion: "风险建议",
  blocker_alert: "阻塞预警",
  gate_readiness_anomaly: "Gate 异常",
  knowledge_draft: "知识草稿",
  meeting_minutes: "会议纪要",
  meeting_action: "会议行动",
  meeting_decision: "会议决策",
  meeting_issue: "会议问题", meeting_risk: "会议风险", meeting_change: "会议变更申请",
  bom_impact_suggestion: "BOM 影响建议",
  change_impact_suggestion: "变更影响建议",
  change_work_package: "变更影响与专业工作包",
  quality_cluster_alert: "质量聚类预警",
  capa_suggestion: "CAPA 建议",
  capa_work_package: "品质调查与整改工作包",
  test_plan_change: "测试计划调整",
  supplier_delay_risk: "供应商交期风险",
  supplier_recovery: "供应恢复方案",
  cost_reduction: "降本备选建议",
  executive_portfolio_brief: "组合例外简报",
};
