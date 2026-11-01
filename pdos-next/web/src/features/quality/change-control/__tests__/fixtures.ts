import { OPERATIONS, TIERS, type ChangeRequest, type Context, type EffectivityPlan, type Impact, type Ref, type SharedAction, type Source } from "../contracts";
/** Synthetic facts for isolated checks only; no production export or page wiring. */
export const source: Source = { id: "synthetic-report", kind: "artifact", revision: 1, position: "合成报告第 4 行", status: "current" };
export const ref = (id: string, kind = "domain"): Ref => ({ id: `synthetic-${id}`, kind, revision: 1 });
const spec = ref("spec", "spec"); const part = ref("part", "part"); const operation = ref("operation", "operation");
export const impact: Impact = {
  ...ref("impact", "impact_assessment"), digest: "synthetic-fixed-digest", current: true, expiresAt: null,
  inputs: [spec, part, operation], sourceScope: "合成工程与制造来源", audience: ["synthetic-team"],
  paths: [
    { id: "engineering-path", line: "engineering", nodes: [spec, part], edges: [{ from: spec, to: part, relationship: "规格约束", source }] },
    { id: "manufacturing-path", line: "manufacturing", nodes: [part, operation], edges: [{ from: part, to: operation, relationship: "装配工序", source }] },
  ],
  effects: [{ id: "inventory", category: "inventory_wip", text: "合成在制切换要求", refs: [part], sources: [source], coverage: "known" }],
  unknowns: [{ id: "fixture", line: "manufacturing", reason: "合成工序到治具缺边", missing: ["Tooling", "SOP", "PilotRun"] }],
  hypotheses: [{ id: "guess", text: "AI 合成治具兼容性猜测", sources: [] }],
};
export const plan: EffectivityPlan = {
  ...ref("plan", "effectivity_plan"), inventoryDisposition: null, trainingRequirement: "合成培训需签收",
  dispositions: [{ object: part, handling: "covered_by_plan", item_ids: ["A", "B"], rationale: "合成已知零件按批次切换", sources: [{ id: source.id, revision: source.revision, kind: source.kind, position: source.position }] }],
  scopes: ["A", "B"].map(id => ({ id, objects: [part], units: [`batch:synthetic-lot-${id}`], description: `合成批次 ${id}`, audience: ["synthetic-team"], lots: [`synthetic-lot-${id}`], serialRange: { start: "0001", end: "0099" }, conditions: ["首件检查完成"], sources: [source] })),
  intents: [{ id: "synthetic-intent", kind: "new_configuration", description: "合成受控新配置意图", fixedRefs: [spec], scopeIds: ["A", "B"], actualRef: null }],
};
export const request: ChangeRequest = {
  ...ref("request", "change_request"), title: "合成工程制造变更", reason: "合成失效需要受控更改", status: "implementing", requestedBy: "synthetic-author",
  references: [{ ref: ref("issue", "issue"), source }], requiresRecheck: false, recheckReasons: [], impact,
  order: {
    ...ref("order", "change_order"), status: "implementing", assessment: impact, plan,
    requiredDisciplines: ["engineering", "manufacturing"], approvals: [{ discipline: "engineering", actorId: "synthetic-engineer", actorLabel: "合成工程批准人", at: "2026-10-02T12:00:00Z", text: "仅批准工程范围", sources: [source] }],
    implementations: [{ id: "synthetic-implementation", intentId: "synthetic-intent", actorId: "synthetic-operator", actorLabel: "合成实施人", outcome: "failed", text: "合成实施故障保留", occurredAt: "2026-10-02T13:00:00Z", originalTimezone: "UTC", recordedAt: "2026-10-02T13:01:00Z", sources: [source] }],
    effectivity: [{ id: "synthetic-effectivity", factId: "synthetic-effectivity-fact", itemId: "A", stage: "effective", receiptId: "synthetic-receipt", outcome: "partial", scopeIds: ["A"], actualRefs: [], text: "仅合成 A 范围已生效", sources: [source] }],
    effectiveScopeIds: ["A"], awaitingScopeIds: ["B"], verification: [], closure: null,
    excludedReviewerIds: ["synthetic-author", "synthetic-engineer", "synthetic-operator"],
  },
};
export const context: Context = {
  key: "synthetic-context", portReady: true, unavailableReason: null, actor: { id: "synthetic-reviewer", label: "合成独立复核人", kind: "human" },
  capabilities: Object.fromEntries(OPERATIONS.map(operation => [operation, { registered: true, allowed: true, candidateAllowed: true, tier: TIERS[operation], reason: null }])),
  referenceOptions: [{ key: "issue", label: "合成固定问题", ref: ref("issue", "issue"), source }],
  rootOptions: [{ key: "part", label: "合成零件根对象", ref: part, source }],
  implementationCandidates: [{ key: "implementation", label: "合成实际实施", factId: "synthetic-implementation-fact", itemId: "A", fact: request.order!.implementations[0], serverVerified: true }],
  inputBundles: [{ snapshot: ref("graph", "graph_snapshot"), key: "bundle", label: "合成固定来源版", refs: impact.inputs, sourceScope: impact.sourceScope, audience: impact.audience, current: true }],
  planCandidates: [{ key: "plan", label: "合成生效计划", plan, commandPlan: {
    id: plan.id, expires_at: "2026-10-09T17:00:00Z", dispositions: plan.dispositions,
    items: ["A", "B"].map(id => ({ id, discipline: "engineering", selection: { objects: [part], units: [`batch:synthetic-lot-${id}`], conditions: ["首件检查完成"], sources: [{ id: source.id, revision: source.revision, kind: source.kind, position: source.position }] }, intent: { id: "synthetic-intent", kind: "new_engineering_configuration", basis: [spec], description: "合成受控新配置意图" }, verification_requirement: "合成独立新 Run" })),
  }, assessment: impact, current: true }],
  evidenceOptions: [{ key: "evidence", label: "合成实施证据", ref: source, source }],
  receiptCandidates: [{ key: "receipt", label: "合成实际生效回执", receipt: request.order!.effectivity[0], serverVerified: true }],
  verificationCandidates: [{ factId: "synthetic-verification-fact", key: "verification", label: "合成独立新 Run", refs: [ref("new-run", "test_run")], sources: [source], scopeIds: ["A", "B"], independent: true, current: true, excludedActorIds: ["synthetic-measurer"] }],
};
export const action: SharedAction = { busy: false, unknown: false, prepared: false, receipt: null, error: null };
