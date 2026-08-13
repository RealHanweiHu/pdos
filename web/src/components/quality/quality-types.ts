export type ComplaintStatus = "open" | "triaged" | "investigating" | "resolved" | "closed";
export type NcrStatus = "open" | "containment" | "root_cause" | "action" | "verification" | "closed";

export type Complaint = {
  id: string;
  project_id: string;
  customer_id: string | null;
  reported_by_user_id: string;
  owner_user_id: string;
  closed_by_user_id: string | null;
  code: string;
  title: string;
  description: string;
  source: "customer" | "field" | "rma" | "internal";
  severity: "critical" | "high" | "medium" | "low";
  status: ComplaintStatus;
  occurred_at: string;
  reported_at: string;
  customer_reference: string | null;
  affected_scope: string | null;
  document_refs: string[];
  resolution_summary: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Ncr = {
  id: string;
  project_id: string;
  complaint_id: string;
  owner_user_id: string;
  created_by_user_id: string;
  preventive_disposition_approved_by_user_id: string | null;
  closed_by_user_id: string | null;
  code: string;
  nonconformity: string;
  requirement_reference: string;
  severity: Complaint["severity"];
  status: NcrStatus;
  target_date: string;
  containment_action: string | null;
  containment_completed_at: string | null;
  affected_quantity: number | null;
  affected_scope: string | null;
  preventive_not_applicable_reason: string | null;
  preventive_disposition_approved_at: string | null;
  effectiveness_criteria: string | null;
  observation_due_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RootCause = {
  id: string;
  analyst_user_id: string;
  approved_by_user_id: string | null;
  version: number;
  method: string;
  analysis: string;
  root_cause: string;
  status: "draft" | "approved" | "superseded";
  created_at: string;
};

export type CapaAction = {
  id: string;
  owner_user_id: string;
  action_type: "corrective" | "preventive";
  description: string;
  due_date: string;
  status: "planned" | "in_progress" | "completed";
  completion_summary: string | null;
  evidence_refs: { kind: "document" | "event"; reference: string }[];
  completed_at: string | null;
};

export type EffectivenessReview = {
  id: string;
  reviewer_user_id: string;
  review_number: number;
  criteria: string;
  observation_due_at: string;
  actual_result: string;
  result: "effective" | "ineffective";
  reviewed_at: string;
};

export type NcrDetail = {
  ncr: Ncr;
  root_causes: RootCause[];
  actions: CapaAction[];
  effectiveness_reviews: EffectivenessReview[];
};

export type ComplaintCreateInput = {
  title: string;
  description: string;
  source: Complaint["source"];
  severity: Complaint["severity"];
  occurred_at: string;
  owner_user_id: string;
  customer_reference: string | null;
  affected_scope: string | null;
};

export type NcrCreateInput = {
  nonconformity: string;
  requirement_reference: string;
  severity: Complaint["severity"];
  owner_user_id: string;
  target_date: string;
  affected_quantity: number | null;
  affected_scope: string | null;
};
