/** Read-only server projections. These fields describe facts, never grant authority. */
export type VersionRef = { id: string; revision: number };
export type SourceRef = VersionRef & { kind: "artifact" | "domain" | "command"; position: string; status: "current" | "stale" | "withdrawn" | "unknown" };
export type FailureRef = {
  /** Stable failure identity excludes delivery event ID and unrelated Run revisions. */
  failureKey: string;
  /** Delivery identity supplied by the authoritative result event adapter. */
  eventId: string;
  run: VersionRef;
  /** Measurement is immutable under its fixed Run revision, not a second versioned owner. */
  measurement: { id: string };
  sample: VersionRef;
  testItemId: string;
  criterion: SourceRef;
  criterionText: string;
  method: SourceRef;
  actualConfiguration: VersionRef;
  engineeringConfiguration: VersionRef;
  manufacturingConfiguration: VersionRef;
  source: SourceRef;
  /** Reader deliberately returns null if current source/ACL checks disallow the original measurement. */
  rawValue: string | null;
  unit: string | null;
  conditions: string | null;
  result: "fail" | "pass" | "indeterminate" | "invalid" | "unknown";
  runStatus: "planned" | "running" | "results_pending" | "reviewed" | "disposed";
  serverVerified: boolean;
  synthetic: boolean;
};
export type NamedConclusion = { text: string; actorId: string; actorLabel: string; decidedAt: string; sources: SourceRef[] };
export type IssueStatus = "open" | "triaged" | "actioning" | "awaiting_verification" | "closed";
export type Issue = VersionRef & {
  title: string; status: IssueStatus; audience: string[]; failures: FailureRef[];
  mergedInto: VersionRef | null;
  aliases: string[];
  retainedOriginals: (VersionRef & { title: string; failureKeys: string[] })[];
  requiresRecheck: boolean; recheckReasons: string[];
  containment: { id: string; description: string; ownerId: string; state: "planned" | "completed"; sources: SourceRef[] }[];
  hypotheses: { id: string; text: string; origin: "ai" | "human"; sources: SourceRef[] }[];
  rootCause: NamedConclusion | null;
  history: { id: string; at: string; description: string }[];
  followUps: { kind: "change_request" | "change_order" | "build" | "run"; ref: VersionRef | null; description: string }[];
  capa: Capa | null;
};
export type EffectivenessConclusion = NamedConclusion & { result: "effective" | "ineffective"; independent: boolean; verificationRuns: VersionRef[] };
export type Capa = VersionRef & {
  description: string;
  actions: { id: string; description: string; ownerId: string; completed: boolean; sources: SourceRef[] }[];
  verificationRequirement: { description: string; policy: VersionRef; highRisk: boolean; independentRequired: boolean; requiredFailureKeys: string[] };
  effectiveness: EffectivenessConclusion | null;
  effectivenessHistory: EffectivenessConclusion[];
};
export const OPERATIONS = ["quality.issue.create", "quality.issue.merge", "quality.issue.triage", "quality.issue.containment.record", "quality.issue.root_cause.decide", "quality.issue.recheck", "quality.issue.close", "quality.capa.draft", "quality.capa.actions.complete", "quality.capa.effectiveness.decide"] as const;
export type Operation = typeof OPERATIONS[number];
export const CANONICAL_OPERATIONS: readonly Operation[] = ["quality.issue.create", "quality.issue.merge", "quality.capa.draft", "quality.capa.effectiveness.decide"];
export const T2_OPERATIONS: readonly Operation[] = ["quality.issue.root_cause.decide", "quality.issue.close", "quality.capa.effectiveness.decide"];
export type Context = {
  /** Must change for permission, current source/configuration, readset or policy changes. */
  key: string; portReady: boolean; unavailableReason: string | null;
  actor: { kind: "human" | "ai"; id: string; label: string } | null;
  capabilities: Partial<Record<Operation, { allowed: boolean; registered: boolean; tier: "T0" | "T1" | "T2"; reason: string | null }>>;
  decisionSources: SourceRef[];
  independentVerificationRuns: VersionRef[];
  verificationEvidence: { id: string; run: VersionRef; label: string; current: boolean; independent: boolean }[];
  accountablePeople: { id: string; label: string }[];
  draftIds: { containmentId: string; capaId: string; actionId: string } | null;
};
type IssueTarget = { issue: VersionRef };
export type EventTime = { occurredAt: string; originalTimezone: string; source: SourceRef };
export type ContainmentInput = { id: string; text: string; executorId: string; evidence: SourceRef[]; at: EventTime };
export type QualityIntent =
  | { operation: "quality.issue.create"; failureKey: string; runId: string; measurementId: string; eventId: string; title: string }
  | (IssueTarget & { operation: "quality.issue.merge"; sourceIssues: VersionRef[]; reason: string })
  | (IssueTarget & { operation: "quality.issue.triage"; reason: string })
  | (IssueTarget & { operation: "quality.issue.containment.record"; action: ContainmentInput })
  | (IssueTarget & { operation: "quality.issue.root_cause.decide"; text: string; sources: SourceRef[] })
  | (IssueTarget & { operation: "quality.issue.recheck"; reason: string })
  | (IssueTarget & { operation: "quality.issue.close"; text: string })
  | (IssueTarget & { operation: "quality.capa.draft"; capaId: string; hypotheses: { text: string; sources: SourceRef[] }[]; actions: { id: string; kind: "corrective" | "preventive"; text: string; executorId: string }[]; requirement: { method: string; acceptance: string; observationUntil: string; requiredFailureIds: string[] } })
  | (IssueTarget & { operation: "quality.capa.actions.complete"; completions: ContainmentInput[] })
  | (IssueTarget & { operation: "quality.capa.effectiveness.decide"; result: "effective" | "ineffective"; text: string; evidenceIds: string[] });
export type PreparedAction = {
  token: string; digest: string; contextKey: string; intent: QualityIntent;
  expiresAt: string; allowed: boolean; tier: "T0" | "T1" | "T2";
  summary: string; differences: string[]; preservedFailureKeys: string[];
  missing: { blocking: boolean; description: string }[];
};
export type Receipt = { outcome: "committed" | "replayed" | "rejected" | "unknown"; receiptId: string | null; message: string };
export type ControlledAction = {
  preview: PreparedAction | null; receipt: Receipt | null; busy: boolean; unknown: boolean;
  error: string | null; nowMs: number;
};
export type Callbacks = {
  /** Host maps to its existing preview entry point; no command execution in this component. */
  onPrepare?: (intent: QualityIntent, contextKey: string) => void | Promise<void>;
  /** Shared host handlers must absorb transport failures and publish unknown/error state. */
  onConfirm?: (preview: PreparedAction) => void | Promise<void>;
  onResolve?: (preview: PreparedAction) => void | Promise<void>;
  /** Host owns committed refresh and calls this from its shared receipt handler. */
  onCommitted?: (receipt: Receipt) => void | Promise<void>;
};
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value) ?? "null";
}
export function operationProblem(operation: Operation, context: Context): string | null {
  if (!context.portReady) return context.unavailableReason || "测试结果、来源核对或办理权限尚未接入。";
  const capability = context.capabilities[operation];
  if (!capability?.registered) return "此办理入口尚未接入，当前不可办理。";
  if (!capability.allowed) return capability.reason || "服务器当前未授权此动作。";
  if (operation === "quality.issue.merge" && capability.tier !== "T1") return "归并须按 T1 实质确认，此办理入口尚待核对。";
  if (T2_OPERATIONS.includes(operation) && capability.tier !== "T2") return "具名决定分级不得降低，须提供 T2 办理入口。";
  if ((T2_OPERATIONS.includes(operation) || capability.tier === "T2") && context.actor?.kind !== "human") return "T2 决定须由服务器绑定的具名人办理，AI 只能准备候选。";
  if (!context.actor?.id.trim() || !context.actor.label.trim()) return "当前具名身份待接入。";
  return null;
}
export function failureProblem(failure: FailureRef): string | null {
  if (!failure.serverVerified) return "失败来源尚未经服务器核验。";
  if (failure.runStatus === "planned") return "计划 Run 不是真实测试失败。";
  if (failure.result !== "fail") return "未知、不确定、无效或通过结果不能建失败问题。";
  if (!failure.rawValue?.trim() || !failure.measurement.id || !failure.testItemId || !failure.source.position.trim()) return "缺精确测量、测试项或原值出处。";
  if ([failure.source, failure.method, failure.criterion].some(source => source.status !== "current")) return "来源已撤回、过期或当前性未知，须重核。";
  return null;
}
export function previewProblem(preview: PreparedAction, intent: QualityIntent | null, context: Context, nowMs: number): string | null {
  const permission = operationProblem(preview.intent.operation, context);
  if (permission) return permission;
  if (!intent || canonical(preview.intent) !== canonical(intent)) return "输入已修改，须重新生成实质预览。";
  if (preview.contextKey !== context.key) return "来源、配置、权限或政策已变化，须重新核对。";
  if (!preview.token || !preview.digest || !Number.isFinite(Date.parse(preview.expiresAt)) || !Number.isFinite(nowMs) || nowMs >= Date.parse(preview.expiresAt)) return "预览已到期或凭据不完整，须重新核对。";
  if (context.capabilities[preview.intent.operation]?.tier !== preview.tier) return "服务器动作分级已变化，须重新核对。";
  if (preview.intent.operation === "quality.issue.merge" && !preview.preservedFailureKeys.length) return "归并预览缺独立失败保留范围，须重新核对。";
  if (!preview.allowed || preview.missing.some(item => item.blocking)) return "服务器预览仍有阻塞项。";
  return null;
}
export function unresolvedAction(action: ControlledAction): boolean {
  return action.unknown || action.receipt?.outcome === "unknown" || (!!action.receipt && ["committed", "replayed"].includes(action.receipt.outcome) && !action.receipt.receiptId);
}
export function versionText(ref: VersionRef): string { return `${ref.id} · v${ref.revision}`; }
export function sourceText(source: SourceRef): string { return `${source.kind} ${versionText(source)} · ${source.position} · ${source.status}`; }
