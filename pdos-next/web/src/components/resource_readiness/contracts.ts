import type { ReactNode } from "react";

/** Read-only server projection; none of these fields grant scope or authority. */
export type ResourceRef = { id: string; revision: number; kind: "equipment" | "fixture" | "person" | "line" | "tooling" };
export type ExecutionWindow = { start: string; finish: string; originalTimezone: string };
export type EvidenceRef = { originalId: string; revision: number; locator: string; status: "current" | "withdrawn" | "stale" };
export type ReadinessStatus = "UNKNOWN" | "BLOCKED" | "READY_WITH_CONDITIONS" | "READY";
export type ResourceCheck = {
  code: string;
  kind: "acceptance" | "calibration" | "maintenance" | "person_qualification" | "applicability" | "authorization";
  status: "satisfied" | "blocked" | "unknown" | "conditioned" | "not_applicable";
  detail: string;
  source: EvidenceRef | null;
  /** Half-open validity [validFrom, validUntil); null is unknown, never infinite. */
  validity: { validFrom: string | null; validUntil: string | null } | null;
  purpose: string;
};
export type ResourceCondition = { id: string; description: string; allowedPurpose: string; expiresAt: string; source: EvidenceRef | null };
export type ResourceReading = {
  ref: ResourceRef;
  label: string;
  purpose: string;
  units: number;
  status: ReadinessStatus;
  checks: ResourceCheck[];
  conditions: ResourceCondition[];
  calendar: { id: string; revision: number; status: "current" | "unknown" | "stale" } | null;
  capacity: { status: "checked" | "unknown" | "conflicted"; detail: string; conflicts: { reservationId: string; window: ExecutionWindow; units: number; detail: string }[] };
};
export type ResourceReservation = {
  id: string;
  revision: number;
  status: "tentative" | "formal" | "released" | "cancelled";
  resources: { ref: ResourceRef; units: number }[];
  window: ExecutionWindow;
  purpose: string;
  events: { kind: "tentative" | "formal" | "released" | "cancelled"; at: string; reason: string; actorLabel: string; source: EvidenceRef | null }[];
};
export type ObservedTime = { occurredAt: string; originalTimezone: string; source: EvidenceRef };
export type ResourceReadinessView = {
  id: string;
  title: string;
  asOf: string;
  status: ReadinessStatus;
  window: ExecutionWindow;
  resources: ResourceReading[];
  reservations: ResourceReservation[];
  /** Independently sourced real events; no fallback to a planned/reserved time. */
  physicalReceived: ObservedTime | null;
  actualStarted: ObservedTime | null;
};
export type ResourceContext = {
  key: string;
  portReady: boolean;
  current: boolean;
  unavailableReason: string | null;
  actor: { label: string; kind: "human" | "ai" } | null;
};
export type ResourceCandidate = {
  id: string;
  digest: string;
  contextKey: string;
  title: string;
  summary: string;
  resources: ResourceRef[];
  window: ExecutionWindow;
  available: boolean;
  unavailableReason: string | null;
} & (
  | { kind: "verification_reservation"; policy: { registered: boolean; hostOperation: string; tier: "T1" } }
  | { kind: "fixture_acceptance"; policy: { registered: boolean; hostOperation: "npi.fixture.accept"; tier: "T2" } }
);
export type ResourceActionState = { busy: boolean; reviewPending: boolean; outcomeUnknown: boolean; error: string | null };
export type ResourceReadinessProps = {
  view: ResourceReadinessView;
  context: ResourceContext;
  candidates: ResourceCandidate[];
  action: ResourceActionState;
  /** Prepares the host's existing controlled action; cannot commit or grant qualifications. */
  onPrepare?: (candidate: ResourceCandidate, contextKey: string) => Promise<void>;
  /** Host owns preview, one confirmation, receipt and unknown-outcome reconciliation. */
  actionReview?: ReactNode;
};

export const readinessNames: Record<ReadinessStatus, string> = { UNKNOWN: "未知 · 待核对", BLOCKED: "阻塞", READY_WITH_CONDITIONS: "在限定条件下就绪", READY: "本用途资源就绪" };
export const resourceKindNames: Record<ResourceRef["kind"], string> = { equipment: "设备", fixture: "治具", person: "人员", line: "线体", tooling: "模具" };
export const checkNames: Record<ResourceCheck["kind"], string> = { acceptance: "验收", calibration: "校准", maintenance: "维护", person_qualification: "人员资格", applicability: "版本与用途适用性", authorization: "现行授权" };
export const checkStatusNames: Record<ResourceCheck["status"], string> = { satisfied: "已满足", blocked: "明确不满足", unknown: "证据不明", conditioned: "限定条件", not_applicable: "本用途不适用" };
export const reservationNames: Record<ResourceReservation["status"], string> = { tentative: "暂定时段", formal: "正式预约", released: "已释放", cancelled: "已取消" };

function timestamp(value: string): number | null {
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const result = Date.parse(value);
  return Number.isFinite(result) ? result : null;
}

export function validityCoverage(validity: ResourceCheck["validity"], window: ExecutionWindow): "covered" | "not_covered" | "unknown" {
  if (!validity?.validFrom || !validity.validUntil) return "unknown";
  const from = timestamp(validity.validFrom), until = timestamp(validity.validUntil), start = timestamp(window.start), finish = timestamp(window.finish);
  if (from === null || until === null || start === null || finish === null || from >= until || start >= finish) return "unknown";
  return from <= start && until >= finish ? "covered" : "not_covered";
}

export function sourceText(source: EvidenceRef | null): string {
  return source ? `${source.originalId} · v${source.revision} · ${source.locator} · ${source.status === "current" ? "当前证据" : source.status === "withdrawn" ? "已撤回" : "已过期"}` : "缺少证据 · UNKNOWN";
}

export function windowText(window: ExecutionWindow): string { return `[${window.start}, ${window.finish}) · ${window.originalTimezone}`; }

export function candidateProblem(candidate: ResourceCandidate, context: ResourceContext, action: ResourceActionState, callbackReady: boolean): string | null {
  if (action.outcomeUnknown) return "原动作结果未知，须先由主线核对原回执。";
  if (action.busy || action.reviewPending) return "已有办理核对，请先完成主线预览。";
  if (!context.portReady || !callbackReady) return context.unavailableReason || "待主线接入服务器端口与共同办理入口。";
  if (!context.current || candidate.contextKey !== context.key) return "资源、授权或执行范围已变化，须重新核对。";
  if (!candidate.policy.registered || !candidate.policy.hostOperation.trim()) return "待政策注册与主线接线。";
  if (candidate.kind === "fixture_acceptance" && (candidate.policy.hostOperation !== "npi.fixture.accept" || candidate.policy.tier !== "T2" || context.actor?.kind !== "human")) return "治具验收须由具名人员沿 npi.fixture.accept 办理。";
  if (candidate.kind === "verification_reservation" && candidate.policy.tier !== "T1") return "预约候选须交主线共同一次确认入口。";
  if (!candidate.id || !candidate.digest || !candidate.summary.trim() || !candidate.resources.length || candidate.resources.some(ref => !ref.id || !Number.isInteger(ref.revision) || ref.revision < 1)) return "服务器固定候选不完整。";
  const start = timestamp(candidate.window.start), finish = timestamp(candidate.window.finish);
  if (start === null || finish === null || start >= finish) return "执行区间须为含时区的有效半开区间。";
  try { if (!candidate.window.originalTimezone.trim()) throw new Error(); new Intl.DateTimeFormat("zh-CN", { timeZone: candidate.window.originalTimezone }); } catch { return "执行区间缺少有效原始 IANA 时区。"; }
  if (!candidate.available) return candidate.unavailableReason || "服务器尚未允许准备此候选。";
  return null;
}
