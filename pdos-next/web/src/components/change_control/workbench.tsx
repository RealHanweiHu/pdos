"use client";
import { useId } from "react";
import { ClipboardText } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { OPERATIONS, TIERS, refText, sourceText, unresolved, type Draft, type Operation, type WorkbenchProps } from "./contracts";
import { editorIntent } from "./editor";
import { ChangeControlReading, ChangeEffectivityReading } from "./reading";

export const ACTION_LABELS: Record<Operation, string> = {
  "change.request.create": "提出变更请求", "change.request.revise": "固定新根与来源修订请求", "change.impact.compute": "计算固定双线影响", "change.order.prepare": "准备变更令与生效范围",
  "change.order.approve": "按专业具名批准", "change.implementation.record": "记录实际实施", "change.effectivity.record": "记录实际生效回执",
  "change.verification.record": "具名独立有效性决定", "change.close": "具名关闭", "change.recheck": "记录待重核原因",
};
const fieldClass = "mt-1 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50";
/** Parent client workspace owns fetching, preview expiry, one confirmation and unknown recovery. */
export function ChangeControlWorkbench({ request, context, draft, action, onDraftChange, onPrepare, sharedReview }: WorkbenchProps) {
  const id = useId();
  const prepared = editorIntent(draft, request, context);
  const locked = action.busy || unresolved(action);
  const aiCandidate = context.actor?.kind === "ai" && TIERS[draft.operation] === "T2";
  function set<K extends keyof Draft>(key: K, value: Draft[K]) { if (!locked) onDraftChange({ ...draft, [key]: value }); }
  function textField(key: "title" | "text" | "approvalExpiresAt", label: string, placeholder?: string) {
    return <label className="block min-w-0 text-sm" htmlFor={`${id}-${key}`}>{label}{key === "text" ? <textarea id={`${id}-${key}`} className={fieldClass} rows={3} value={draft[key]} disabled={locked} onChange={event => set(key, event.target.value)} /> : <input id={`${id}-${key}`} className={fieldClass} value={draft[key]} placeholder={placeholder} disabled={locked} onChange={event => set(key, event.target.value)} />}</label>;
  }
  function select(key: "inputBundleKey" | "planKey" | "discipline" | "intentId" | "receiptKey" | "verificationKey" | "implementationKey", label: string, options: readonly { key: string; label: string }[]) {
    return <label className="block min-w-0 text-sm" htmlFor={`${id}-${key}`}>{label}<select id={`${id}-${key}`} className={fieldClass} value={draft[key]} disabled={locked} onChange={event => set(key, event.target.value)}><option value="">请选择当前固定范围</option>{options.map(value => <option key={value.key} value={value.key}>{value.label}</option>)}</select></label>;
  }
  function references(key: "referenceKeys" | "evidenceKeys" | "rootKeys", label: string, values: typeof context.referenceOptions) {
    return <fieldset className="min-w-0 space-y-2 rounded-lg border border-border p-3" disabled={locked}><legend className="px-1 text-sm">{label}</legend>{values.length ? values.map(value => <label key={value.key} className="flex min-w-0 items-start gap-2 text-sm"><input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary" checked={draft[key].includes(value.key)} onChange={event => set(key, event.target.checked ? [...draft[key], value.key] : draft[key].filter(item => item !== value.key))} /><span className="min-w-0 break-words">{value.label}<span className="mt-1 block text-xs opacity-70">{refText(value.ref)} · {sourceText(value.source)}</span></span></label>) : <p className="text-sm opacity-70">UNKNOWN · 当前可见固定引用待接入。</p>}</fieldset>;
  }
  const selectedPlan = context.planCandidates.find(value => value.key === draft.planKey);
  return <div className="min-w-0 space-y-6">
    {request ? <ChangeControlReading request={request} /> : <header><h2 className="text-lg font-semibold">工程与制造双线变更</h2><p className="mt-1 text-sm opacity-70">引用精确问题、CAPA 与测试结果，形成独立变更请求。</p></header>}
    <section aria-label="变更办理候选" aria-busy={action.busy} className="min-w-0 rounded-lg border border-border bg-[var(--surface)] p-4">
      <h3 className="flex items-center gap-2 font-medium"><ClipboardText aria-hidden />办理下一步</h3>
      {!context.portReady && <p role="status" className="mt-3 text-sm">待接入：{context.unavailableReason || "对象、来源、权限及共同命令端口尚未齐备。"}</p>}
      <p className="mt-3 break-words text-sm opacity-70">当前身份：{context.actor ? `${context.actor.label}（${context.actor.id}）` : "待服务器绑定"}。T2 由具名人决定，AI 只能准备候选。</p>
      <form className="mt-4 space-y-4" onSubmit={event => { event.preventDefault(); if (!locked && prepared.intent && onPrepare) void onPrepare(prepared.intent, context.key); }}>
        <label className="block text-sm" htmlFor={`${id}-operation`}>办理动作<select id={`${id}-operation`} className={fieldClass} value={draft.operation} disabled={locked} onChange={event => set("operation", event.target.value as Operation)}>{OPERATIONS.filter(value => request || value === "change.request.create").map(value => <option key={value} value={value}>{ACTION_LABELS[value]} · {TIERS[value]}{!context.capabilities[value]?.registered ? " · 待接线" : ""}</option>)}</select></label>
        {["change.request.create", "change.request.revise"].includes(draft.operation) && <>{textField("title", "变更请求标题")}{references("rootKeys", "被改变的规格 / 零件 / 接口等根对象", context.rootOptions)}{references("referenceKeys", "固定 Issue / CAPA / TestRun 等引用（不修改来源对象）", context.referenceOptions)}</>}
        {draft.operation === "change.impact.compute" && <>{select("inputBundleKey", "固定输入版、来源范围与受众", context.inputBundles.map(value => ({ key: value.key, label: `${value.label} · ${value.current ? "当前" : "待重核"} · ${value.sourceScope} · ${value.audience.join("、") || "受众 UNKNOWN"}` })))}<p className="text-sm opacity-70">仅沿有出处的显式边计算；缺边与不完整版本保持 UNKNOWN，AI 推测单独列出。</p></>}
        {draft.operation === "change.order.prepare" && select("planKey", "本次固定影响版对应的生效计划候选", context.planCandidates.map(value => ({ key: value.key, label: `${value.label} · ${refText(value.assessment)} · ${value.current ? "当前" : "待重核"}` })))}
        {draft.operation === "change.order.approve" && <>{select("discipline", "本次专业批准范围", request?.order?.requiredDisciplines.map(value => ({ key: value, label: value })) || [])}{textField("approvalExpiresAt", "本次专业批准到期时点（含偏移或 Z）", "2026-10-09T09:00:00-07:00")}<p className="text-sm opacity-70">本次只记录所选专业决定；审批不创建新配置、Build、Run 或外部生效。</p></>}
        {draft.operation === "change.implementation.record" && <>{select("implementationKey", "所有者核验的实际实施事实", context.implementationCandidates.map(value => ({ key: value.key, label: `${value.label} · ${value.fact.outcome} · ${value.serverVerified ? "已核验" : "待核验"}` })))}<p className="text-sm opacity-70">实际发生、接收时点、结果和证据由实施所有者提供；本次只引用固定事实，失败与未知不会变为生效。</p></>}
        {draft.operation === "change.effectivity.record" && <>{select("receiptKey", "服务器核验的实际接收 / 生效回执", context.receiptCandidates.map(value => ({ key: value.key, label: `${value.label} · ${value.receipt.outcome} · ${value.serverVerified ? "来源已核验" : "待核验"}` })))}<p className="text-sm opacity-70">发送成功、对方接收与实际生效分别记录；未知回执不算生效。</p></>}
        {draft.operation === "change.verification.record" && <>{select("verificationKey", "固定新 Run 与独立复核证据", context.verificationCandidates.map(value => ({ key: value.key, label: `${value.label} · ${value.independent ? "独立性已核验" : "独立性待核验"} · ${value.current ? "当前" : "待重核"}` })))}<p className="text-sm opacity-70">新配置、实际生效与全部范围覆盖须核验；提出、批准、实施和测量执行者不得自证。</p></>}
        {!["change.impact.compute", "change.effectivity.record", "change.implementation.record"].includes(draft.operation) && textField("text", TIERS[draft.operation] === "T2" ? "专业决定候选 / 具名说明" : "本次原因与实际说明")}
        {prepared.problem && <p role="status" className="text-sm opacity-70">{prepared.problem}</p>}
        {action.error && <p role="alert" className="text-sm text-destructive">{action.error}</p>}
        {unresolved(action) && <p role="alert" className="text-sm text-destructive">原动作结果未知；请在共同回执区核对，当前禁止重提新动作。</p>}
        {!onPrepare && <p role="status" className="text-sm opacity-70">共同预览入口待接入。</p>}
        {action.prepared && <p className="text-sm opacity-70">已有共同实质预览；修改输入后须由主线重新核对。</p>}
        <Button type="submit" disabled={locked || !prepared.intent || !onPrepare}>{aiCandidate ? "准备具名决定候选" : "核对本次实质范围"}</Button>
      </form>
      {draft.operation === "change.order.prepare" && selectedPlan && <div className="mt-4 border-t border-border pt-4"><ChangeEffectivityReading plan={selectedPlan.plan} /></div>}
    </section>
    <section aria-label="共同实质预览与回执">{sharedReview || <p className="text-sm opacity-70">共同一次确认与回执区待接入；本组件不执行确认。</p>}</section>
  </div>;
}
