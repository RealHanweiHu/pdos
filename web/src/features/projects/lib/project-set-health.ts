/**
 * Project-set progress is only a grouping of member projects' rule health (P17/P61).
 * A set has no business state of its own; a member whose health is missing or not
 * “正常” counts as needing attention, so an unread health never looks healthy.
 */
export type MemberHealth = { state: string; label: string; reason: string } | null | undefined;
export type SetMember = { project: { governance?: { health: { state: string; label: string; reason: string }; current_stage: { name: string } | null; completed: boolean } } };
export type SetLane = "attention" | "normal" | "empty";

export const setLaneNames: Record<SetLane, string> = { attention: "需关注", normal: "进展正常", empty: "暂无可见项目" };
export const setLaneOrder: SetLane[] = ["attention", "normal", "empty"];

export function memberNeedsAttention(member: SetMember): boolean {
  return member.project.governance?.health.state !== "normal";
}

export function setLane(members: SetMember[]): SetLane {
  if (!members.length) return "empty";
  return members.some(memberNeedsAttention) ? "attention" : "normal";
}

/** Text for the list’s progress column; counts are whole projects, never a ratio. */
export function setProgress(members: SetMember[]): string {
  if (!members.length) return "暂无可见项目";
  const attention = members.filter(memberNeedsAttention).length;
  return attention ? `${attention} 个需关注` : "全部正常";
}

export function memberStage(member: SetMember): string {
  const governance = member.project.governance;
  if (!governance) return "阶段未读取";
  return governance.current_stage?.name ?? (governance.completed ? "阶段已完成" : "未采用阶段模板");
}

export function memberHealth(member: SetMember): { label: string; reason: string; tone: "success" | "warning" | "danger" | "neutral" } {
  const health = member.project.governance?.health;
  if (!health) return { label: "未读取", reason: "健康度暂不可读", tone: "neutral" };
  const tone = health.state === "normal" ? "success" : health.state === "blocked" ? "danger" : health.state === "unknown" ? "neutral" : "warning";
  return { label: health.label, reason: health.reason, tone };
}
