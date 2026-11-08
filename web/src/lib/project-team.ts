/** Project team read model and owner change sets (P34-1). The server decides every permission. */

export type TeamRole = { key: string; name: string; lead: boolean };
export type CatalogRole = { key: string; name: string; active: boolean };
export type GrantState = "write" | "read" | "expired" | "missing";
export type Pending = { tasks: number; commitments: number; external_waits: number };
export type TeamMember = {
  member_id: string; principal_id: string; name: string; is_owner: boolean; roles: TeamRole[];
  joined_at: string; added_by: string; added_by_name: string; grant: GrantState; active_person: boolean;
  pending: Pending | null; needs_model_access: { object: string; owner_name: string }[];
};
export type DepartedMember = { member_id: string; principal_id: string; name: string; roles: TeamRole[]; joined_at: string; left_at: string; removed_by_name: string; handover_pending: boolean; pending: Pending | null };
export type TeamCandidate = { principal_id: string; name: string; grant: GrantState };
export type TeamView = {
  project: { id: string; name: string; owner_id: string; owner_name: string; visibility: string };
  revision: number; can_manage: boolean; membership_controls_visibility: boolean;
  catalog: { revision: number; default: boolean; roles: CatalogRole[] };
  members: TeamMember[]; departed: DepartedMember[]; vacant_roles: string[]; roles_without_lead: string[];
  candidates?: TeamCandidate[];
};
export type RoleChoice = { key: string; lead: boolean };
export type MemberChange = { action: "add" | "set_roles" | "remove" | "complete"; principal_id: string; roles?: RoleChoice[] };
export type TeamRequest = { expected_revision: number; request_key: string; changes: MemberChange[] };

export function teamPath(productId: string, projectId: string) {
  return `v1/products/${productId}/projects/${projectId}/team`;
}
export function teamStorageKey(principalId: string, projectId: string) {
  return `pdos:project-team:${principalId}:${projectId}:pending:v1`;
}

/** A grant the category no longer gives cannot be restored by the team. */
export function needsGrant(grant: GrantState) { return grant === "missing" || grant === "expired"; }
/** Unhanded responsibility in words; empty when nothing is left to hand over. */
export function pendingText(pending: Pending | null) {
  if (!pending) return "";
  return ([["tasks", "任务"], ["commitments", "承诺"], ["external_waits", "外部等待"]] as const)
    .filter(([key]) => pending[key] > 0).map(([key, label]) => `${label} ${pending[key]}`).join("、");
}
export function grantLabel(grant: GrantState) {
  return grant === "write" ? "可办理" : grant === "read" ? "只读授权" : "需要品类授权";
}

export function roleName(view: TeamView, key: string) {
  return view.catalog.roles.find(role => role.key === key)?.name
    ?? view.members.flatMap(member => member.roles).find(role => role.key === key)?.name
    ?? key;
}

/** Roles a member may choose: active ones, plus inactive ones the member already holds (P60-4). */
export function selectableRoles(view: TeamView, held: RoleChoice[]) {
  const kept = new Set(held.map(role => role.key));
  return view.catalog.roles.filter(role => role.active || kept.has(role.key));
}

/**
 * One request for the edited member. Taking a role's lead moves it: whoever held
 * that lead keeps the role without it, in the same change set, so a role never
 * has two leads and the owner confirms once.
 */
export function roleChanges(view: TeamView, principalId: string, roles: RoleChoice[], action: "add" | "set_roles" = "set_roles"): MemberChange[] {
  const leads = new Set(roles.filter(role => role.lead).map(role => role.key));
  const moved = view.members
    .filter(member => member.principal_id !== principalId && member.roles.some(role => role.lead && leads.has(role.key)))
    .map(member => ({
      action: "set_roles" as const, principal_id: member.principal_id,
      roles: member.roles.map(role => ({ key: role.key, lead: role.lead && !leads.has(role.key) })),
    }));
  return [{ action, principal_id: principalId, roles }, ...moved];
}

export function leadHolder(view: TeamView, principalId: string, key: string) {
  return view.members.find(member => member.principal_id !== principalId && member.roles.some(role => role.key === key && role.lead));
}

export function teamRequest(view: TeamView, changes: MemberChange[], requestKey: string): TeamRequest {
  return { expected_revision: view.revision, request_key: requestKey, changes };
}

export function formatJoined(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "日期未知" : date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}
