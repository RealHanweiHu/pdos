export type Department = {
  id: string;
  name: string;
  parent_department_id: string | null;
  created_at: string;
  updated_at: string;
};

export type Delegation = {
  id: string;
  principal_user_id: string;
  delegate_user_id: string;
  starts_at: string;
  ends_at: string;
  reason: string;
  created_by_user_id: string;
  revoked_at: string | null;
  revoked_by_user_id: string | null;
  created_at: string;
};

export type DelegationCreate = {
  principal_user_id: string;
  delegate_user_id: string;
  starts_at: string;
  ends_at: string;
  reason: string;
};

export type HandoverResult = {
  from_user_id: string;
  to_user_id: string;
  transferred_counts: Record<string, number>;
  deactivated: boolean;
};

export const HANDOVER_COUNT_LABELS: Record<string, string> = {
  issue_owner: "问题负责人",
  issue_verifier: "问题验证人",
  task_assignee: "任务负责人",
  risk_owner: "风险负责人",
  project_owner: "项目负责人",
  direct_reports: "直接下属",
  successor_reporting_line: "接手人汇报关系",
  delegations_revoked: "撤销的代理",
  project_memberships_added: "补齐项目成员资格",
};

export function delegationState(
  delegation: Delegation,
  now: Date,
): "active" | "scheduled" | "expired" | "revoked" {
  if (delegation.revoked_at !== null) return "revoked";
  const starts = new Date(delegation.starts_at);
  const ends = new Date(delegation.ends_at);
  if (now < starts) return "scheduled";
  if (now >= ends) return "expired";
  return "active";
}

export type HandoverPreview = {
  from_user_id: string;
  to_user_id: string;
  basis_digest: string;
  transfer_count: number;
  manual_count: number;
  delegations_to_revoke: number;
  project_access_count: number;
  groups: Array<{
    key: string;
    label: string;
    count: number;
    can_transfer: boolean;
    reasons: string[];
    items: Array<{ id: string; title: string; href: string }>;
  }>;
};
