"use client";

import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { baseProblems, fixedContextKey, sourceText, staleProblems, type Callbacks, type ManufacturingIntent, type PilotPackage, type ServerContext, type SharedAction, type ToolTrialPackage } from "./contracts";
import { controlClass, FixedList, FixedReading, MissingReading, ParameterReading, PreparationFrame, ResourceReading, SharedSlots } from "./display";

type CommonProps = { context: ServerContext; action: SharedAction; callbacks: Callbacks };
export type ToolTrialWorkbenchProps = CommonProps & { fixed: ToolTrialPackage; initialRound?: number; initialPurpose?: string };
export type PilotRunWorkbenchProps = CommonProps & { fixed: PilotPackage; initialPurpose?: string };

function usePreview(callbacks: Callbacks, action: SharedAction) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const lock = useRef(false);
  return { busy: busy || action.busy || action.unresolved, error, prepare: async (intent: ManufacturingIntent, contextKey: string) => {
    if (lock.current || action.busy || action.unresolved || !callbacks.onPreview) return;
    lock.current = true; setBusy(true); setError("");
    try { await callbacks.onPreview(intent, contextKey); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "预览未完成，输入已保留。"); }
    finally { lock.current = false; setBusy(false); }
  } };
}
export function ToolTrialWorkbench(props: ToolTrialWorkbenchProps) { return <ToolTrialForm key={fixedContextKey(props.context, props.fixed)} {...props} />; }
function ToolTrialForm({ context, fixed, action, callbacks, initialRound = 0, initialPurpose = "" }: ToolTrialWorkbenchProps) {
  const id = useId();
  const [purpose, setPurpose] = useState(initialPurpose), [round, setRound] = useState(String(initialRound));
  const preview = usePreview(callbacks, action);
  const problems = [...baseProblems(context, "npi.tooltrial.create"), ...staleProblems([fixed.build, fixed.tooling, ...fixed.materials, ...fixed.originalIssues, ...fixed.corrections, ...fixed.namedAcceptances])];
  if (!purpose.trim()) problems.push("填写本轮试模目的。");
  if (!/^\d+$/.test(round) || !Number.isSafeInteger(Number(round))) problems.push("试模轮次须为非负整数。");
  if (!fixed.quality.requestCreate) problems.push("完整品质请求尚待父办理区提供。");
  if (fixed.quality.requestCreate && (fixed.quality.requestCreate.build_id !== fixed.build.id || fixed.quality.requestCreate.expected_build_revision !== fixed.build.revision)) problems.push("品质请求与固定 Build 不一致。");
  if (!fixed.cavities.length || new Set(fixed.cavities).size !== fixed.cavities.length) problems.push("模穴范围尚未固定或重复。");
  if (!callbacks.onPreview) problems.push("共同预览入口待接入。");
  if (fixed.source.status !== "current") problems.push("创建来源已失效，须先重核。");
  return <PreparationFrame title="试模准备" context={context}>
    <dl className="grid min-w-0 gap-4 sm:grid-cols-2"><FixedReading label="固定 Build" reference={fixed.build} /><FixedReading label="固定工装版本" reference={fixed.tooling} /></dl><p className="break-words text-xs opacity-70">创建固定来源：{sourceText(fixed.source)}</p>
    <p className="text-sm">模穴：{fixed.cavities.join("、") || "未知"}。试模轮次使用 trial_round，与写入方式分开记录。</p>
    <FixedList label="固定物料批次" references={fixed.materials} /><ParameterReading parameters={fixed.parameters} /><ResourceReading resources={fixed.resources} />
    <div className="space-y-3 border-t border-border pt-4"><FixedList label="原始问题引用" references={fixed.originalIssues} /><FixedList label="整改来源" references={fixed.corrections} /><FixedList label="具名验收来源（引用已有决定）" references={fixed.namedAcceptances} /></div>
    <section className="space-y-3 border-t border-border pt-4" aria-label="品质前置准备"><h3 className="font-medium">品质前置请求意图</h3><dl><FixedReading label="已有品质请求" reference={fixed.quality.request} /></dl><FixedList label="固定验证方法" references={fixed.quality.methods} /><div><h4 className="text-sm font-medium">图纸 / 特征 / 判据固定资料</h4>{fixed.quality.documents.length ? <ul className="mt-1 space-y-1 text-xs opacity-70">{fixed.quality.documents.map((source, index) => <li className="break-words" key={index}>{sourceText(source)}</li>)}</ul> : <p className="text-sm opacity-70">资料未知，待资料所有者补齐。</p>}</div><p className="text-sm">预期样件：{fixed.quality.expectedSampleQuantity ?? "未知"}；模穴：{fixed.quality.cavities.join("、") || "未知"}；预期时点：{fixed.quality.expectedAt || "未知"}；返回形式：{fixed.quality.returnFormat || "未知"}。</p><p className="text-sm opacity-70">品质请求由验证模块在共同事务中建立或关联。提前策划不等于实际交样、正式接收或资源预约。</p><MissingReading items={[...context.missing, ...fixed.quality.missing]} /></section>
    <form className="space-y-4 border-t border-border pt-4" onSubmit={event => { event.preventDefault(); if (!problems.length) void preview.prepare({ operation: "npi.tooltrial.create", purpose: purpose.trim(), trialRound: Number(round), fixed, qualityRequestIntent: { kind: "prepare", preparation: fixed.quality } }, fixedContextKey(context, fixed)); }}>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2"><label className="text-sm" htmlFor={`${id}-purpose`}>本轮目的<input id={`${id}-purpose`} className={controlClass} value={purpose} maxLength={2000} disabled={preview.busy} onChange={event => setPurpose(event.target.value)} /></label><label className="text-sm" htmlFor={`${id}-round`}>试模轮次（trial_round）<input id={`${id}-round`} className={controlClass} inputMode="numeric" value={round} disabled={preview.busy} onChange={event => setRound(event.target.value)} /></label></div>
      {problems.length > 0 && <p role="status" className="text-sm opacity-70">{problems.join(" ")}</p>}{preview.error && <p role="alert" className="text-sm text-destructive">{preview.error}</p>}
      <Button type="submit" disabled={preview.busy || problems.length > 0}>预览试模候选</Button>
    </form><SharedSlots action={action} />
  </PreparationFrame>;
}
export function PilotRunWorkbench(props: PilotRunWorkbenchProps) { return <PilotRunForm key={fixedContextKey(props.context, props.fixed)} {...props} />; }
function PilotRunForm({ context, fixed, action, callbacks, initialPurpose = "" }: PilotRunWorkbenchProps) {
  const id = useId();
  const [purpose, setPurpose] = useState(initialPurpose);
  const preview = usePreview(callbacks, action);
  const problems = [...baseProblems(context, "npi.pilot.create"), ...staleProblems([fixed.build, fixed.lot, fixed.actualConfiguration, fixed.engineeringConfiguration, fixed.process, fixed.manufacturingBaseline, fixed.line, ...fixed.personnel, ...fixed.materials, ...fixed.fixtures, ...fixed.equipment, ...fixed.instructions, fixed.controlPlan, fixed.risk, fixed.reservation, fixed.firstArticle])];
  if (!purpose.trim()) problems.push("填写本轮试产目的。");
  if (!callbacks.onPreview) problems.push("共同预览入口待接入。");
  if (fixed.source.status !== "current") problems.push("创建来源已失效，须先重核。");
  return <PreparationFrame title="试产准备" context={context}>
    <dl className="grid min-w-0 gap-4 sm:grid-cols-2"><FixedReading label="既有 Build" reference={fixed.build} /><FixedReading label="实际 BuildLot" reference={fixed.lot} /><FixedReading label="实际型号配置" reference={fixed.actualConfiguration} /><FixedReading label="工程配置" reference={fixed.engineeringConfiguration} /><FixedReading label="真实工艺版本" reference={fixed.process} /><FixedReading label="正式制造基线" reference={fixed.manufacturingBaseline} /><FixedReading label="线体" reference={fixed.line} /><FixedReading label="首件确认来源" reference={fixed.firstArticle} /><FixedReading label="控制计划" reference={fixed.controlPlan} /><FixedReading label="过程风险" reference={fixed.risk} /><FixedReading label="资源预约固定引用" reference={fixed.reservation} /></dl>
    {(!fixed.manufacturingBaseline || fixed.process.status !== "released") && <p role="status" className="rounded-lg border border-border p-3 text-sm">正式制造基线未齐。当前工艺{fixed.process.status === "draft" ? "仅为草稿" : fixed.process.status === "withdrawn" ? "已撤回" : "已发布但不替代制造基线"}；可准备候选、记录明确观察，尚不可宣称正式可开工或已批准试产。</p>}
    <p className="text-sm opacity-70">试产是既有 Build 的制造扩展；批次数量沿实物账使用，不新增库存或重建样件账。</p>
    <FixedList label="具名人员固定引用" references={fixed.personnel} /><FixedList label="实际物料批次" references={fixed.materials} /><FixedList label="固定治具" references={fixed.fixtures} /><FixedList label="固定设备" references={fixed.equipment} /><FixedList label="作业指引固定版本" references={fixed.instructions} /><p className="break-words text-xs opacity-70">创建来源：{sourceText(fixed.source)}；固定单位：{fixed.unit}。</p><ParameterReading parameters={fixed.parameters} /><ResourceReading resources={fixed.resources} /><MissingReading items={[...context.missing, ...fixed.missing]} />
    <form className="space-y-4 border-t border-border pt-4" onSubmit={event => { event.preventDefault(); if (!problems.length) void preview.prepare({ operation: "npi.pilot.create", purpose: purpose.trim(), fixed }, fixedContextKey(context, fixed)); }}>
      <label className="block text-sm" htmlFor={`${id}-purpose`}>试产目的<input id={`${id}-purpose`} className={controlClass} value={purpose} maxLength={2000} disabled={preview.busy} onChange={event => setPurpose(event.target.value)} /></label>
      {problems.length > 0 && <p role="status" className="text-sm opacity-70">{problems.join(" ")}</p>}{preview.error && <p role="alert" className="text-sm text-destructive">{preview.error}</p>}
      <Button type="submit" disabled={preview.busy || problems.length > 0}>预览试产候选</Button>
    </form><SharedSlots action={action} />
  </PreparationFrame>;
}
