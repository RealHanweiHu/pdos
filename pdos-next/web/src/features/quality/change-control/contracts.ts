import type { ReactNode } from "react";

/** Immutable server projections, never client authority or imported legacy approvals. */
export type Ref = { id: string; revision: number; kind: string; key?: string | null };
export type Source = Ref & { position: string; status: "current" | "stale" | "withdrawn" | "unknown" };
export type NamedDecision = { actorId: string; actorLabel: string; at: string; text: string; sources: readonly Source[] };
export type ChangeState = "draft" | "analysis" | "review" | "approved" | "implementing" | "verifying" | "closed";
export type ImpactLine = "engineering" | "manufacturing";
export type KnownPath = {
  id: string; line: ImpactLine; nodes: readonly Ref[];
  edges: readonly { from: Ref; to: Ref; relationship: string; source: Source }[];
};
export type Impact = Ref & {
  digest: string; current: boolean; expiresAt: string | null; inputs: readonly Ref[];
  sourceScope: string; audience: readonly string[]; paths: readonly KnownPath[];
  effects: readonly { id: string; category: "evidence" | "build" | "customer_sample" | "inventory_wip" | "supply" | "training"; text: string; refs: readonly Ref[]; sources: readonly Source[]; coverage: "known" | "unknown" }[];
  unknowns: readonly { id: string; line: ImpactLine | "shared"; reason: string; missing: readonly string[] }[];
  hypotheses: readonly { id: string; text: string; sources: readonly Source[] }[];
};
export type EffectivityScope = {
  id: string; objects: readonly Ref[]; units: readonly string[]; description: string; audience: readonly string[];
  lots: readonly string[]; serialRange: { start: string; end: string } | null;
  conditions: readonly string[]; sources: readonly Source[];
};
export type ControlledIntent = {
  id: string; kind: "new_configuration" | "new_build" | "new_run" | "erp_mes_effectivity";
  description: string; fixedRefs: readonly Ref[]; scopeIds: readonly string[];
  /** A requested creation/transfer never implies actual object creation or external effect. */
  actualRef: Ref | null;
};
export type Disposition = { object: Ref; handling: "covered_by_plan" | "reviewed_no_change" | "unknown"; item_ids: readonly string[]; rationale: string; sources: readonly CommandSource[] };
export type EffectivityPlan = Ref & { scopes: readonly EffectivityScope[]; intents: readonly ControlledIntent[]; dispositions: readonly Disposition[]; inventoryDisposition: string | null; trainingRequirement: string | null };
export type CommandSource = Pick<Source, "id" | "revision" | "kind" | "position">;
/** Exact server-owned candidate payload; presentation scopes never reconstruct unit tokens. */
export type CommandPlan = {
  id: string; expires_at: string | null; dispositions: readonly Disposition[];
  items: readonly {
    id: string; discipline: "engineering" | "manufacturing" | "customer" | "regulatory";
    selection: { objects: readonly Ref[]; units: readonly string[]; conditions: readonly string[]; sources: readonly CommandSource[] };
    intent: { id: string; kind: "new_engineering_configuration" | "new_manufacturing_configuration" | "new_build" | "new_test_run" | "erp_mes_effectivity"; basis: readonly Ref[]; description: string };
    verification_requirement: string;
  }[];
};
export type Implementation = {
  id: string; intentId: string; actorId: string; actorLabel: string;
  outcome: "completed" | "partial" | "failed" | "unknown"; text: string;
  occurredAt: string; originalTimezone: string; recordedAt: string; sources: readonly Source[];
};
export type EffectivityEvidence = {
  id: string; factId: string; itemId: string; stage: "sent" | "accepted" | "effective";
  receiptId: string; outcome: "effective" | "partial" | "failed" | "unknown";
  scopeIds: readonly string[]; actualRefs: readonly Ref[]; text: string; sources: readonly Source[];
};
export type IndependentVerification = NamedDecision & {
  result: "effective" | "ineffective"; independent: boolean;
  coverageScopeIds: readonly string[]; runs: readonly Ref[];
};
export type ChangeOrder = Ref & {
  status: ChangeState; assessment: Ref; plan: EffectivityPlan;
  requiredDisciplines: readonly string[];
  approvals: readonly (NamedDecision & { discipline: string })[];
  implementations: readonly Implementation[]; effectivity: readonly EffectivityEvidence[];
  verification: readonly IndependentVerification[]; closure: NamedDecision | null;
  /** Includes request authors, approvers, implementers and measurement executors, from ports. */
  excludedReviewerIds: readonly string[];
  effectiveScopeIds: readonly string[]; awaitingScopeIds: readonly string[];
};
export type ChangeRequest = Ref & {
  title: string; reason: string; status: ChangeState; requestedBy: string;
  references: readonly { ref: Ref; source: Source }[];
  requiresRecheck: boolean; recheckReasons: readonly string[];
  impact: Impact | null; order: ChangeOrder | null;
};
export const OPERATIONS = ["change.request.create", "change.request.revise", "change.impact.compute", "change.order.prepare", "change.order.approve", "change.implementation.record", "change.effectivity.record", "change.verification.record", "change.close", "change.recheck"] as const;
export type Operation = typeof OPERATIONS[number];
export const TIERS: Record<Operation, "T0" | "T1" | "T2"> = {
  "change.request.create": "T0", "change.request.revise": "T1", "change.impact.compute": "T0", "change.order.prepare": "T1",
  "change.order.approve": "T2", "change.implementation.record": "T1", "change.effectivity.record": "T1",
  "change.verification.record": "T2", "change.close": "T2", "change.recheck": "T1",
};
export type ReferenceOption = { key: string; label: string; ref: Ref; source: Source };
export type Context = {
  key: string; portReady: boolean; unavailableReason: string | null;
  actor: { id: string; label: string; kind: "human" | "ai" } | null;
  capabilities: Partial<Record<Operation, { registered: boolean; allowed: boolean; candidateAllowed: boolean; tier: "T0" | "T1" | "T2"; reason: string | null }>>;
  referenceOptions: readonly ReferenceOption[];
  rootOptions: readonly ReferenceOption[];
  inputBundles: readonly { key: string; snapshot: Ref; label: string; refs: readonly Ref[]; sourceScope: string; audience: readonly string[]; current: boolean }[];
  planCandidates: readonly { key: string; label: string; plan: EffectivityPlan; commandPlan: CommandPlan; assessment: Ref; current: boolean }[];
  evidenceOptions: readonly ReferenceOption[];
  implementationCandidates: readonly { key: string; label: string; factId: string; itemId: string; fact: Implementation; serverVerified: boolean }[];
  receiptCandidates: readonly { key: string; label: string; receipt: EffectivityEvidence; serverVerified: boolean }[];
  verificationCandidates: readonly { key: string; factId: string; label: string; refs: readonly Ref[]; sources: readonly Source[]; scopeIds: readonly string[]; independent: boolean; current: boolean; excludedActorIds: readonly string[] }[];
};
export type Draft = {
  operation: Operation; title: string; text: string; referenceKeys: readonly string[]; rootKeys: readonly string[];
  inputBundleKey: string; planKey: string; discipline: string; intentId: string;
  implementationKey: string; approvalExpiresAt: string;
  evidenceKeys: readonly string[]; receiptKey: string; verificationKey: string;
};
type Target = { request: Ref; order: Ref | null };
export type ChangeIntent =
  | { operation: "change.request.create"; title: string; reason: string; roots: readonly Ref[]; references: readonly Ref[]; sources: readonly Source[] }
  | (Target & { operation: "change.request.revise"; title: string; reason: string; roots: readonly Ref[]; references: readonly Ref[]; sources: readonly Source[] })
  | (Target & { operation: "change.impact.compute"; snapshot: Ref; fixedInputs: readonly Ref[]; sourceScope: string; audience: readonly string[] })
  | (Target & { operation: "change.order.prepare"; assessment: Ref; plan: CommandPlan; text: string })
  | (Target & { operation: "change.order.approve"; discipline: string; text: string; expiresAt: string })
  | (Target & { operation: "change.implementation.record"; itemId: string; factId: string })
  | (Target & { operation: "change.effectivity.record"; itemId: string; factId: string })
  | (Target & { operation: "change.verification.record"; factId: string; text: string })
  | (Target & { operation: "change.close" | "change.recheck"; text: string });
export type SharedAction = {
  busy: boolean; unknown: boolean; receipt: { outcome: "committed" | "replayed" | "rejected" | "unknown"; id: string | null } | null;
  /** Parent invalidates a prepared preview if this current intent or contextKey changes. */
  prepared: boolean; error: string | null;
};
export type WorkbenchProps = {
  request: ChangeRequest | null; context: Context; draft: Draft; action: SharedAction;
  onDraftChange: (draft: Draft) => void;
  /** Sole bridge to the host's existing command preview. Host absorbs failure/unknown. */
  onPrepare?: (intent: ChangeIntent, contextKey: string) => void | Promise<void>;
  /** Host owns common preview, one confirmation, receipt recovery and committed refresh. */
  sharedReview: ReactNode;
};
export function emptyDraft(operation: Operation = "change.request.create"): Draft {
  return { operation, title: "", text: "", referenceKeys: [], rootKeys: [], inputBundleKey: "", planKey: "", discipline: "", intentId: "", implementationKey: "", approvalExpiresAt: "", evidenceKeys: [], receiptKey: "", verificationKey: "" };
}
export function refText(ref: Ref): string { return `${ref.kind} ${ref.id} · v${ref.revision}`; }
export function sourceText(source: Source): string { return `${refText(source)} · ${source.position} · ${source.status}`; }
export function sameRef(a: Ref, b: Ref): boolean { return a.id === b.id && a.revision === b.revision && a.kind === b.kind && (a.key ?? null) === (b.key ?? null); }
export function unresolved(action: SharedAction): boolean {
  return action.unknown || action.receipt?.outcome === "unknown" || (!!action.receipt && ["committed", "replayed"].includes(action.receipt.outcome) && !action.receipt.id);
}
