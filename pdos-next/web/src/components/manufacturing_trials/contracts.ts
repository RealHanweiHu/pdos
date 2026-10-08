import type { ReactNode } from "react";
import type { VerificationRequestCreate } from "./domain-payload";

/** Projections only. The server independently resolves identity, scope, versions and authority. */
export type SourceRef = { originalId: string; revision: number; kind: "artifact" | "domain" | "command"; locator: string; status: "current" | "stale" | "withdrawn"; synthetic: boolean };
export type RefKind = "build" | "build_lot" | "actual_configuration" | "engineering_configuration" | "process_revision" | "manufacturing_baseline" | "tooling" | "fixture" | "equipment" | "line" | "person" | "material_lot" | "verification_method" | "quality_request" | "issue" | "corrective_action" | "named_acceptance" | "first_article" | "pilot_run" | "observation" | "sample" | "work_instruction" | "control_plan" | "risk" | "reservation" | "qualification" | "criterion";
export type FixedRef<K extends RefKind = RefKind> = { kind: K; id: string; revision: number; label: string; source: SourceRef | null; current: boolean };
export type Parameter = { key: string; value: string | null; unit: string | null; source: SourceRef | null };
export type MissingItem = { kind: "document" | "sample" | "method" | "resource" | "baseline" | "authorization" | "integration"; label: string; blocking: boolean; recovery: string };
export type ResourceUse = { resource: FixedRef<"tooling" | "fixture" | "equipment" | "line" | "person">; readinessRef: { id: string; revision: number } | null; state: "ready" | "unknown" | "blocked" | "withdrawn" };
export type QualityPreparation = { request: FixedRef<"quality_request"> | null; requestCreate: VerificationRequestCreate | null; methods: FixedRef<"verification_method">[]; documents: SourceRef[]; expectedSampleQuantity: number | null; cavities: string[]; expectedAt: string | null; returnFormat: string; missing: MissingItem[] };
export type ServerContext = { version: string; portReady: boolean; unavailableReason?: string; capabilities: { toolTrialCreate: boolean; pilotCreate: boolean; resultRecord: boolean }; missing: MissingItem[]; namedOwners: { toolingAcceptance: string | null; manufacturingRelease: string | null } };
/** Parent-owned common T1 preview, one confirmation and receipt. Never execute from this package. */
export type SharedAction = { busy: boolean; unresolved: boolean; previewSlot?: ReactNode; receiptSlot?: ReactNode };
export type Callbacks = { onPreview?: (intent: ManufacturingIntent, contextKey: string) => Promise<void> };
export type ToolTrialPackage = { build: FixedRef<"build">; source: SourceRef; tooling: FixedRef<"tooling">; materials: FixedRef<"material_lot">[]; cavities: string[]; resources: ResourceUse[]; quality: QualityPreparation; originalIssues: FixedRef<"issue">[]; corrections: FixedRef<"corrective_action">[]; namedAcceptances: FixedRef<"named_acceptance">[]; parameters: Parameter[] };
export type PilotPackage = { build: FixedRef<"build">; lot: FixedRef<"build_lot">; actualConfiguration: FixedRef<"actual_configuration">; engineeringConfiguration: FixedRef<"engineering_configuration">; unit: string; source: SourceRef; process: FixedRef<"process_revision"> & { status: "draft" | "released" | "withdrawn" }; manufacturingBaseline: FixedRef<"manufacturing_baseline"> | null; line: FixedRef<"line"> | null; personnel: FixedRef<"person">[]; materials: FixedRef<"material_lot">[]; fixtures: FixedRef<"fixture">[]; equipment: FixedRef<"equipment">[]; instructions: FixedRef<"work_instruction">[]; controlPlan: FixedRef<"control_plan"> | null; risk: FixedRef<"risk"> | null; reservation: FixedRef<"reservation"> | null; resources: ResourceUse[]; parameters: Parameter[]; firstArticle: FixedRef<"first_article"> | null; missing: MissingItem[] };
export type ToolTrialIntent = { operation: "npi.tooltrial.create"; purpose: string; trialRound: number; fixed: ToolTrialPackage; qualityRequestIntent: { kind: "prepare"; preparation: QualityPreparation } };
export type PilotIntent = { operation: "npi.pilot.create"; purpose: string; fixed: PilotPackage };
export type UnitOutcome = "good" | "scrap" | "rework_pending" | "undecided" | "unprocessed";
export type UnitInput = { sample: FixedRef<"sample">; firstPass: "pass" | "fail" | "unknown" | "unprocessed"; outcome: UnitOutcome; reworkAttempts: number; source: SourceRef | null };
export type Counts = { input: number | null; output: number | null; firstPassGood: number | null; firstFailed: number | null; firstUnknown: number | null; finalGood: number | null; reworkedGood: number | null; scrap: number | null; reworkPending: number | null; undetermined: number | null; unprocessed: number | null; reworkAttempts: number | null };
export type ObservationScope = { key: string; pilot: FixedRef<"pilot_run">; build: FixedRef<"build">; lot: FixedRef<"build_lot">; actualConfiguration: FixedRef<"actual_configuration">; engineeringConfiguration: FixedRef<"engineering_configuration">; process: FixedRef<"process_revision">; manufacturingBaseline: FixedRef<"manufacturing_baseline"> | null; line: FixedRef<"line"> | null; unit: string; population: string; window: { start: string; end: string }; criterion: FixedRef<"criterion">; denominator: number | null; minimumSample: number; provenance: "real" | "synthetic"; allocation: { mode: "batch" } | { mode: "unit"; samples: FixedRef<"sample">[] } };
export type ExceptionFact = { key: string; description: string; source: SourceRef; issue: FixedRef<"issue"> | null; dispositionSource: SourceRef | null };
export type ResultIntent = { operation: "npi.pilot.result.record"; scope: ObservationScope; previous: FixedRef<"observation"> | null; occurredAt: string; originalTimezone: string; source: SourceRef; counts: Counts | null; units: UnitInput[]; exceptions: ExceptionFact[]; correctionReason: string | null };
export type ManufacturingIntent = ToolTrialIntent | PilotIntent | ResultIntent;
export type YieldProjection = { scope: ObservationScope; observation: FixedRef<"observation">; receivedAt: string; occurredAt: string; originalTimezone: string; source: SourceRef; previous: FixedRef<"observation"> | null; counts: Counts; firstPassRate: string | null; finalGoodRate: string | null; rateUnit: "fraction"; status: "complete" | "partial" | "conflicted" | "no_results"; warnings: string[]; sampleSufficient: boolean | null; anomalies: string; disposition: string };

export function sourceKey(source: SourceRef): string { return JSON.stringify([source.originalId, source.revision, source.kind, source.locator, source.synthetic]); }
export function sourceText(source: SourceRef | null): string { return source ? `${source.originalId} · v${source.revision} · ${source.locator} · ${source.synthetic ? "合成" : "现实"} · ${source.status === "current" ? "当前" : source.status === "withdrawn" ? "已撤回" : "需重核"}` : "来源未知"; }
export function refText(ref: FixedRef | null): string { return ref ? `${ref.label} · v${ref.revision}${ref.current ? "" : " · 需重核"}` : "未知 / 待接入"; }
export function fixedContextKey(context: ServerContext, fixed: unknown): string { return JSON.stringify({ context, fixed }); }
export function baseProblems(context: ServerContext, operation: ManufacturingIntent["operation"]): string[] {
  const capability = operation === "npi.tooltrial.create" ? context.capabilities.toolTrialCreate : operation === "npi.pilot.create" ? context.capabilities.pilotCreate : context.capabilities.resultRecord;
  return [!context.portReady ? context.unavailableReason || "服务端事实与共同办理端口待接入。" : "", !capability ? "当前权限或动作注册尚不可办理。" : ""].filter(Boolean);
}
export function staleProblems(refs: (FixedRef | null)[]): string[] {
  return refs.filter((ref): ref is FixedRef => !!ref).filter(ref => !ref.id.trim() || !Number.isSafeInteger(ref.revision) || ref.revision < 1 || !ref.current || !ref.source || ref.source.status !== "current").map(ref => `${ref.label}的固定版本或来源需重核。`);
}
export function resultProblems(scope: ObservationScope, counts: Counts | null, units: UnitInput[], occurredAt: string, timezone: string, source: SourceRef | null, previous: FixedRef<"observation"> | null, correctionReason: string, missingExplanation: string): string[] {
  const problems = staleProblems([scope.pilot, scope.build, scope.lot, scope.actualConfiguration, scope.engineeringConfiguration, scope.process, scope.manufacturingBaseline, scope.line, scope.criterion, previous]);
  if (!scope.unit.trim() || !scope.population.trim() || !scope.criterion.current || scope.criterion.source?.status !== "current") problems.push("统计单位、范围或判据尚未固定。");
  if (!Number.isSafeInteger(scope.minimumSample) || scope.minimumSample < 1) problems.push("最低样本必须是服务器固定的正整数。");
  const start = Date.parse(scope.window.start), end = Date.parse(scope.window.end), at = Date.parse(occurredAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || !Number.isFinite(at) || !/(Z|[+-]\d{2}:\d{2})$/i.test(occurredAt)) problems.push("发生时间或固定统计窗口无效。");
  if (Number.isFinite(at) && (at < start || at > end)) problems.push("观察发生时间不在固定统计窗口内。");
  try { new Intl.DateTimeFormat("zh-CN", { timeZone: timezone }); if (!timezone.trim()) problems.push("原始 IANA 时区待填写。"); } catch { problems.push("原始 IANA 时区无效。"); }
  if (!source || source.status !== "current" || !source.originalId.trim() || !source.locator.trim() || !Number.isInteger(source.revision) || source.revision < 1 || source.synthetic !== (scope.provenance === "synthetic")) problems.push("须选择当前来源，合成与现实口径不得混合。");
  if (previous && !correctionReason.trim()) problems.push("修正续版须说明修正原因，原观察保持不可变。");
  if (scope.denominator !== null && (!Number.isSafeInteger(scope.denominator) || scope.denominator < 0)) problems.push("固定分母无效。");
  if (scope.allocation.mode === "batch") {
    if (!counts || units.length) problems.push("严谨批次计数与逐件口径互斥。");
    if (counts) {
      const values = Object.values(counts);
      if (values.some(value => value !== null && (!Number.isSafeInteger(value) || value < 0))) problems.push("计数须为非负安全整数，未知不得填零。");
      if (counts.input !== scope.denominator) problems.push("投入计数须等于固定分母，返工次数不增加投入。");
      const finals = [counts.finalGood, counts.scrap, counts.reworkPending, counts.undetermined, counts.unprocessed];
      if (scope.denominator !== null && finals.every((value): value is number => value !== null) && finals.reduce((sum, value) => sum + value, 0) !== scope.denominator) problems.push("最终合格、报废、返工中、未判定与未加工须互斥，合计等于固定投入。");
      if (scope.denominator !== null && finals.reduce<number>((sum, value) => sum + (value ?? 0), 0) > scope.denominator) problems.push("已知终态计数超过固定投入。");
      if (counts.firstPassGood !== null && ((scope.denominator !== null && counts.firstPassGood > scope.denominator) || (counts.finalGood !== null && counts.firstPassGood > counts.finalGood))) problems.push("首次通过不得超过投入或最终合格。");
      const firsts = [counts.firstPassGood, counts.firstFailed, counts.firstUnknown, counts.unprocessed];
      if (scope.denominator !== null && (firsts.reduce<number>((sum, value) => sum + (value ?? 0), 0) > scope.denominator || (firsts.every((value): value is number => value !== null) && firsts.reduce((sum, value) => sum + value, 0) !== scope.denominator))) problems.push("首遍通过、失败、未知和未加工须覆盖固定投入且互斥。");
      if (counts.output !== null && counts.unprocessed !== null && scope.denominator !== null && counts.output + counts.unprocessed !== scope.denominator) problems.push("产出加未加工须等于固定投入。");
      for (const states of [firsts.slice(0, 3), finals.slice(0, 4)]) if (counts.output !== null && (states.reduce<number>((sum, value) => sum + (value ?? 0), 0) > counts.output || (states.every((value): value is number => value !== null) && states.reduce((sum, value) => sum + value, 0) !== counts.output))) problems.push("加工首遍与终态须分别覆盖实际产出。");
      if (counts.finalGood !== null && (counts.firstPassGood ?? 0) + (counts.reworkedGood ?? 0) > counts.finalGood) problems.push("首次通过加返工合格不得超过最终合格。");
      if (counts.reworkedGood !== null && ((counts.firstFailed !== null && counts.firstUnknown !== null && counts.reworkedGood > counts.firstFailed + counts.firstUnknown) || (counts.reworkAttempts !== null && counts.reworkAttempts < counts.reworkedGood))) problems.push("返工合格数与首遍结果或累计返工次数矛盾。");
      if (scope.denominator !== null && Object.entries(counts).some(([key, value]) => key !== "reworkAttempts" && value !== null && value > (scope.denominator ?? Number.MAX_SAFE_INTEGER))) problems.push("已知计数超过固定投入。");
      if (values.some(value => value === null) && !missingExplanation.trim()) problems.push("局部未知计数须说明缺项与待核对范围。");
    }
  } else {
    const samples = scope.allocation.samples;
    problems.push(...staleProblems(samples));
    if (counts || units.length !== samples.length || new Set(units.map(unit => unit.sample.id)).size !== units.length || units.some(unit => !samples.some(sample => JSON.stringify(sample) === JSON.stringify(unit.sample)))) problems.push("逐件观察须精确覆盖固定样件，禁止与批次计数混算。");
    if (scope.denominator !== samples.length) problems.push("逐件固定分母须等于本范围实际样件数。");
    if (units.some(unit => !Number.isSafeInteger(unit.reworkAttempts) || unit.reworkAttempts < 0 || (unit.firstPass === "pass" && (unit.outcome !== "good" || unit.reworkAttempts !== 0)) || (unit.firstPass === "unprocessed") !== (unit.outcome === "unprocessed") || (unit.outcome === "unprocessed" && unit.reworkAttempts !== 0) || (unit.firstPass === "fail" && unit.outcome === "good" && unit.reworkAttempts === 0))) problems.push("逐件首次通过、互斥终态或返工次数矛盾。");
    if (units.some(unit => !unit.source || unit.source.status !== "current" || unit.source.synthetic !== (scope.provenance === "synthetic"))) problems.push("每件观察须有当前固定来源，现实与合成分列。");
    if (units.some(unit => unit.firstPass === "unknown") && !missingExplanation.trim()) problems.push("首次结果未知须说明缺项。");
  }
  return Array.from(new Set(problems));
}
