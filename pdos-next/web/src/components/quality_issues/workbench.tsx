"use client";
import { useId, useState } from "react";
import { ClipboardText } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { OPERATIONS, sourceText, unresolvedAction, versionText, type Callbacks, type Context, type ControlledAction, type FailureRef, type Issue, type Operation } from "./contracts";
import { EMPTY_FIELDS, editorIntent, sourceKey, type EditorFields } from "./editor";
import { FailureReading, QualityIssueReading } from "./reading";
import { QualityActionReview } from "./review";

export const ACTION_LABELS: Record<Operation, string> = {
  "quality.issue.create": "从精确失败建问题", "quality.issue.merge": "归并问题（保留原记录）", "quality.issue.triage": "记录分诊",
  "quality.issue.containment.record": "记录遏制行动", "quality.issue.root_cause.decide": "具名根因决定", "quality.issue.recheck": "记录待重核",
  "quality.issue.close": "具名关闭问题", "quality.capa.draft": "准备 CAPA 草稿", "quality.capa.actions.complete": "记录措施完成", "quality.capa.effectiveness.decide": "具名独立有效性决定",
};
const controlClass = "mt-1 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50";
export type QualityIssueWorkbenchProps = {
  issue: Issue | null; failures: FailureRef[]; mergeCandidates: Issue[];
  context: Context; action: ControlledAction; callbacks: Callbacks;
  initialOperation?: Operation;
};
/** Mount inside the main client workspace; all effects and receipts belong to its shared command framework. */
export function QualityIssueWorkbench({ issue, failures, mergeCandidates, context, action, callbacks, initialOperation }: QualityIssueWorkbenchProps) {
  const baseId = useId();
  const [operation, setOperation] = useState<Operation>(initialOperation ?? (issue ? "quality.issue.triage" : "quality.issue.create"));
  const [fields, setFields] = useState<EditorFields>(EMPTY_FIELDS);
  const [error, setError] = useState("");
  const prepared = editorIntent(operation, fields, issue, failures, mergeCandidates, context);
  const locked = action.busy || unresolvedAction(action);
  function set<K extends keyof EditorFields>(key: K, value: EditorFields[K]) { setFields(previous => ({ ...previous, [key]: value })); setError(""); }
  function textField(key: "text" | "actionText" | "method" | "acceptance", label: string) {
    return <label className="block min-w-0 text-sm" htmlFor={`${baseId}-${key}`}>{label}<textarea id={`${baseId}-${key}`} className={controlClass} rows={key === "text" ? 3 : 2} value={fields[key]} disabled={locked} onChange={event => set(key, event.target.value)} /></label>;
  }
  function input(key: "occurredAt" | "timezone" | "observationUntil", label: string, placeholder: string) {
    return <label className="block min-w-0 text-sm" htmlFor={`${baseId}-${key}`}>{label}<input id={`${baseId}-${key}`} className={controlClass} value={fields[key]} placeholder={placeholder} disabled={locked} onChange={event => set(key, event.target.value)} /></label>;
  }
  const needsSources = ["quality.issue.containment.record", "quality.issue.root_cause.decide", "quality.capa.draft", "quality.capa.actions.complete"].includes(operation);
  const needsOwner = ["quality.issue.containment.record", "quality.capa.draft", "quality.capa.actions.complete"].includes(operation);
  const needsEvent = operation === "quality.issue.containment.record" || operation === "quality.capa.actions.complete";
  const selectedMerge = operation === "quality.issue.merge" ? mergeCandidates.find(value => value.id === fields.selectedId) : null;
  const selectedFailure = operation === "quality.issue.create" ? failures.find(value => value.failureKey === fields.selectedId) : null;
  return <div className="min-w-0 space-y-6">
    {issue && <QualityIssueReading issue={issue} />}
    {!issue && <header><h2 className="text-lg font-semibold">测试失败 → 问题</h2><p className="mt-1 text-sm opacity-70">只消费服务器核验的固定 TestRun 结果；重复投递与业务失败分别去重。</p></header>}
    <section className="min-w-0 rounded-lg border border-border bg-[var(--surface)] p-4" aria-label="问题与 CAPA 办理">
      <h3 className="flex items-center gap-2 font-medium"><ClipboardText aria-hidden />办理下一步</h3>
      {!context.portReady && <p role="status" className="mt-3 rounded-lg border border-border p-3 text-sm">待接入：{context.unavailableReason || "测试、测量、来源核对或办理权限尚未齐备。"}</p>}
      {!callbacks.onPrepare && <p role="status" className="mt-3 text-sm opacity-70">办理核对入口待接入，当前不能办理。</p>}
      <p className="mt-3 break-words text-sm opacity-70">当前身份：{context.actor ? `${context.actor.label}（${context.actor.id}）· ${context.actor.kind}` : "待服务器绑定"}。AI 只准备专业决定，T2 须具名人。</p>
      <form className="mt-4 space-y-4" onSubmit={async event => {
        event.preventDefault();
        if (locked || !prepared.intent || !callbacks.onPrepare) return;
        setError("");
        try { await callbacks.onPrepare(prepared.intent, context.key); }
        catch (failure) { setError(failure instanceof Error ? failure.message : "预览失败，输入已保留。"); }
      }}>
        <label className="block text-sm" htmlFor={`${baseId}-operation`}>办理动作<select id={`${baseId}-operation`} className={controlClass} value={operation} disabled={locked} onChange={event => { setOperation(event.target.value as Operation); set("selectedId", ""); }}>{OPERATIONS.filter(value => issue || value === "quality.issue.create").map(value => <option key={value} value={value}>{ACTION_LABELS[value]}</option>)}</select></label>
        {operation === "quality.issue.create" && <label className="block text-sm" htmlFor={`${baseId}-failure`}>精确失败测量<select id={`${baseId}-failure`} className={controlClass} value={fields.selectedId} disabled={locked} onChange={event => set("selectedId", event.target.value)}><option value="">请选择经核验失败</option>{failures.map(failure => <option key={failure.failureKey} value={failure.failureKey}>{failure.testItemId} / {failure.sample.id} / {failure.measurement.id} · {failure.result}{failure.synthetic ? " · 合成" : ""}</option>)}</select></label>}
        {operation === "quality.issue.merge" && <label className="block text-sm" htmlFor={`${baseId}-merge`}>需保留的原问题<select id={`${baseId}-merge`} className={controlClass} value={fields.selectedId} disabled={locked} onChange={event => set("selectedId", event.target.value)}><option value="">选择当前可见问题（不按相似标题自动归并）</option>{mergeCandidates.filter(value => value.id !== issue?.id && !value.mergedInto).map(value => <option key={value.id} value={value.id}>{value.title} · {versionText(value)} · {value.failures.length} 条独立失败</option>)}</select></label>}
        {textField("text", operation === "quality.issue.create" ? "问题标题" : operation === "quality.capa.draft" ? "根因假设（不是专业结论）" : "本次说明 / 具名结论")}
        {needsSources && <label className="block text-sm" htmlFor={`${baseId}-source`}>固定证据及精确位置<select id={`${baseId}-source`} className={controlClass} value={fields.sourceId} disabled={locked} onChange={event => set("sourceId", event.target.value)}><option value="">请选择服务器当前可读来源</option>{context.decisionSources.map(source => <option key={sourceKey(source)} value={sourceKey(source)} disabled={source.status !== "current"}>{sourceText(source)}</option>)}</select></label>}
        {needsOwner && <label className="block text-sm" htmlFor={`${baseId}-owner`}>具名执行责任人<select id={`${baseId}-owner`} className={controlClass} value={fields.ownerId} disabled={locked} onChange={event => set("ownerId", event.target.value)}><option value="">请选择服务器提供的责任人</option>{context.accountablePeople.map(person => <option key={person.id} value={person.id}>{person.label}（{person.id}）</option>)}</select></label>}
        {needsEvent && <div className="grid min-w-0 gap-4 sm:grid-cols-2">{input("occurredAt", "真实措施发生时间（含时区）", "2026-10-02T09:00:00-07:00")}{input("timezone", "原始 IANA 时区", "America/Los_Angeles")}</div>}
        {operation === "quality.capa.draft" && <>
          <label className="block text-sm" htmlFor={`${baseId}-action-kind`}>措施性质<select id={`${baseId}-action-kind`} className={controlClass} value={fields.actionKind} disabled={locked} onChange={event => set("actionKind", event.target.value as "corrective" | "preventive")}><option value="corrective">纠正</option><option value="preventive">预防</option></select></label>
          {textField("actionText", "具体措施（草稿不声明已执行）")}<div className="grid min-w-0 gap-4 sm:grid-cols-2">{textField("method", "有效性复核方法")}{textField("acceptance", "明确接受判据")}</div>{input("observationUntil", "观察截至时间（含时区）", "2026-10-10T17:00:00-07:00")}
          <p className="break-words text-sm opacity-70">复核范围固定为本问题全部失败：{issue?.failures.map(value => value.failureKey).join("、") || "待接入"}。独立验证与高风险规则由服务器政策决定。</p>
        </>}
        {operation === "quality.capa.actions.complete" && <label className="block text-sm" htmlFor={`${baseId}-completion`}>本次实际完成措施<select id={`${baseId}-completion`} className={controlClass} value={fields.selectedId} disabled={locked} onChange={event => set("selectedId", event.target.value)}><option value="">请选择未完成措施</option>{issue?.capa?.actions.filter(value => !value.completed).map(value => <option key={value.id} value={value.id}>{value.description} · {value.id}</option>)}</select></label>}
        {operation === "quality.capa.effectiveness.decide" && <>
          <label className="block text-sm" htmlFor={`${baseId}-effectiveness`}>具名有效性决定<select id={`${baseId}-effectiveness`} className={controlClass} value={fields.effectiveness} disabled={locked} onChange={event => set("effectiveness", event.target.value as "effective" | "ineffective")}><option value="effective">有效</option><option value="ineffective">无效（保持整改）</option></select></label>
          <label className="block text-sm" htmlFor={`${baseId}-verification`}>独立复验依据（可选择多条覆盖完整失败范围）<select id={`${baseId}-verification`} className={controlClass} multiple value={fields.evidenceIds} disabled={locked} onChange={event => set("evidenceIds", Array.from(event.target.selectedOptions, option => option.value))}>{context.verificationEvidence.map(value => <option key={value.id} value={value.id} disabled={!value.current || !value.independent}>{value.label} · Run {versionText(value.run)} · {value.independent ? "独立核验" : "独立性待核验"}</option>)}</select></label>
          <p className="text-sm opacity-70">执行者不能自证独立有效。具名决定仍须服务器复核资格、政策、失败覆盖、观察期和当前配置。</p>
        </>}
        {prepared.problem && <p role="status" className="text-sm opacity-70">{prepared.problem}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={locked || !prepared.intent || !callbacks.onPrepare}>核对本次实质范围</Button>
      </form>
      {selectedFailure && <div className="mt-4"><FailureReading failure={selectedFailure} /></div>}
      {selectedMerge && <div className="mt-4 space-y-3 border-t border-border pt-4"><p className="text-sm font-medium">将保留的原问题独立失败</p>{selectedMerge.failures.map(failure => <FailureReading key={failure.failureKey} failure={failure} />)}</div>}
    </section>
    <QualityActionReview action={action} context={context} intent={prepared.intent} callbacks={callbacks} />
  </div>;
}
