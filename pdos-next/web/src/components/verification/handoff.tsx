"use client";

import { useId, useState } from "react";
import { ArrowBendUpLeft, Handshake } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { coverageGaps, eventTimeProblems, fixedContextKey, handoffProblems, mergeCoverage, pairKey, sourceText, type CoveragePair, type HandoffIntent, type ReturnedItem, type SampleRef, type VerificationCallbacks, type VerificationContext, type VerificationRequest } from "./contracts";
import { blankEventTime, eventTimeFromDraft, EventTimeFields } from "./event-time";
import { useVerificationAction, VerificationActionReview } from "./preview";

const inputClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
type Props = { request: VerificationRequest; samples: SampleRef[]; context: VerificationContext; callbacks: VerificationCallbacks; nextOwners: { id: string; label: string }[] };

export function VerificationHandoff(props: Props) {
  return <HandoffPanel key={props.request.id} {...props}/>;
}

function HandoffPanel({ request, samples, context, callbacks, nextOwners }: Props) {
  const prefix = useId();
  const [actionType, setActionType] = useState<HandoffIntent["action"]>("handoff.accept");
  const [sampleIds, setSampleIds] = useState<string[]>([]);
  const [testItemIds, setTestItemIds] = useState<string[]>([]);
  const [pairs, setPairs] = useState<CoveragePair[]>([]);
  const [returnReason, setReturnReason] = useState("");
  const [nextOwnerId, setNextOwnerId] = useState("");
  const [eventTime, setEventTime] = useState(blankEventTime);
  const contextKey = fixedContextKey(context, request, samples);
  const allowed = context.portReady && (actionType === "handoff.accept" ? context.capabilities.accept : actionType === "handoff.offer" ? context.capabilities.offer : context.capabilities.returnItems);
  const action = useVerificationAction(contextKey, allowed, callbacks);
  const editable = !action.locked;
  const remainingPairs = request.offeredCoverage?.pairs.filter(pair => !request.acceptedCoverage?.pairs.some(value => pairKey(value) === pairKey(pair))) ?? [];
  const remainingScope = { sampleIds: Array.from(new Set(remainingPairs.map(pair => pair.sampleId))), testItemIds: Array.from(new Set(remainingPairs.map(pair => pair.testItemId))), pairs: remainingPairs };
  const coverage = actionType === "handoff.return" ? remainingScope : { sampleIds, testItemIds, pairs: pairs.filter(pair => sampleIds.includes(pair.sampleId) && testItemIds.includes(pair.testItemId)) };
  const kept = actionType === "handoff.return" ? { sampleIds: [], testItemIds: [], pairs: [] } : coverage;
  const cumulativeGaps = coverageGaps(request, samples, mergeCoverage(request.acceptedCoverage, kept));
  const omitted: { kind: ReturnedItem["kind"]; id: string; label: string }[] = actionType === "handoff.offer" ? [] : [
    ...request.documents.filter(doc => doc.status !== "current" || !doc.source).map(doc => ({ kind: "document" as const, id: doc.id, label: `资料：${doc.title}` })),
    ...remainingPairs.filter(pair => !kept.pairs.some(value => pairKey(value) === pairKey(pair))).map(pair => ({ kind: "coverage" as const, id: pairKey(pair), label: `对应范围：${samples.find(sample => sample.id === pair.sampleId)?.label ?? pair.sampleId} / ${request.testItems.find(item => item.id === pair.testItemId)?.title ?? pair.testItemId}` })),
  ];
  const returnedItems: ReturnedItem[] = omitted.map(item => ({ kind: item.kind, id: item.id, reason: returnReason, nextOwnerId }));
  const problems = handoffProblems(request, samples, coverage, returnedItems, actionType, returnReason, nextOwnerId);
  const stateReady = actionType === "handoff.offer" ? request.status === "draft" : ["offered", "accepted", "scheduled", "executing"].includes(request.status);

  function toggle(values: string[], id: string, update: (values: string[]) => void) { update(values.includes(id) ? values.filter(value => value !== id) : [...values, id]); }
  function prepare() {
    if (!allowed || !stateReady) { action.setError("当前请求状态、身份或接口不允许本次办理。"); return; }
    const time = eventTimeFromDraft(eventTime);
    const allProblems = [...problems, ...eventTimeProblems(time, "交接事件")];
    if (allProblems.length) { action.setError(allProblems.join(" ")); return; }
    const intent: HandoffIntent = { action: actionType, time, request: { id: request.id, revision: request.revision }, build: request.build, coverage, samples: samples.filter(sample => coverage.sampleIds.includes(sample.id)), returnedItems, partialReason: returnReason, nextOwnerId };
    void action.prepare(intent);
  }

  return <section className="min-w-0 space-y-4" aria-label="资料与实际样件交接办理" aria-busy={action.busy}>
    <header><h2 className="flex items-center gap-2 text-lg font-semibold"><Handshake aria-hidden/>办理交接范围</h2><p className="mt-1 text-sm opacity-70">接收以实际样件和适用测试项为范围；未接收项保留原因及下一责任人。</p></header>
    {!context.portReady && <p role="status" className="rounded-lg border border-border bg-muted p-3 text-sm">待主线接入：{context.unavailableReason || "实际样件、配置及授权复查接口尚未就绪。"}</p>}
    <form onSubmit={event => { event.preventDefault(); prepare(); }} className="space-y-4">
      <fieldset disabled={!editable} className="space-y-4"><legend className="sr-only">交接范围与退缺项</legend>
        <label className="block space-y-1 text-sm" htmlFor={`${prefix}-action`}><span>本次动作</span><select id={`${prefix}-action`} className={inputClass} value={actionType} onChange={event => setActionType(event.target.value as HandoffIntent["action"])}><option value="handoff.accept">接收明确范围</option><option value="handoff.return">退回缺项</option><option value="handoff.offer">提出交接</option></select></label>
        <EventTimeFields title="本次交接真实发生时间与来源" value={eventTime} onChange={setEventTime}/>
        {actionType !== "handoff.return" && <div className="grid min-w-0 gap-5 lg:grid-cols-2"><fieldset className="min-w-0 space-y-3"><legend className="mb-2 font-medium">实际样件范围</legend>{samples.length === 0 && <p className="text-sm opacity-70">尚无实际 SampleUnit。请等待实物来源与实际配置接入。</p>}{samples.map(sample => {
          const selectable = sample.buildId === request.build.id && sample.availability === "available" && !!sample.actualConfiguration.id && sample.actualConfiguration.revision > 0 && !!sample.source && (actionType !== "handoff.accept" || remainingScope.sampleIds.includes(sample.id));
          return <label key={sample.id} className="flex items-start gap-3 rounded-lg border border-border p-3 text-sm"><input className="mt-1 accent-primary" type="checkbox" checked={sampleIds.includes(sample.id)} disabled={!selectable} onChange={() => toggle(sampleIds, sample.id, setSampleIds)}/><span className="min-w-0"><span className="block break-words font-medium">{sample.label}</span><span className="mt-1 block break-words text-xs opacity-70">实际配置 {sample.actualConfiguration.id} · v{sample.actualConfiguration.revision}；模穴 {sample.cavity ?? "未记录"}；{sourceText(sample.source)}</span>{!selectable && <span className="mt-1 block text-xs">当前不可选择：可用性、固定配置、来源或本次提出范围尚未满足。</span>}</span></label>;
        })}</fieldset><fieldset className="min-w-0 space-y-3"><legend className="mb-2 font-medium">适用测试项范围</legend>{request.testItems.map(item => <label key={item.id} className="flex items-start gap-3 rounded-lg border border-border p-3 text-sm"><input className="mt-1 accent-primary" type="checkbox" checked={testItemIds.includes(item.id)} disabled={actionType === "handoff.accept" && !remainingScope.testItemIds.includes(item.id)} onChange={() => toggle(testItemIds, item.id, setTestItemIds)}/><span className="min-w-0"><span className="block break-words font-medium">{item.title}</span><span className="mt-1 block text-xs opacity-70">方法 v{item.method.revision}；需要 {item.method.sampleQuantity} 件；模穴 {item.method.cavities.join("、") || "未限定"}</span></span></label>)}</fieldset></div>}
        {actionType !== "handoff.return" && <fieldset className="space-y-2 border-t border-border pt-4"><legend className="mb-2 text-sm font-medium">逐件确认测试项对应覆盖</legend>{samples.filter(sample => sampleIds.includes(sample.id)).flatMap(sample => request.testItems.filter(item => testItemIds.includes(item.id)).map(item => {
          const pair = { sampleId: sample.id, testItemId: item.id };
          const chosen = coverage.pairs.some(value => pairKey(value) === pairKey(pair));
          const offered = actionType !== "handoff.accept" || remainingPairs.some(value => pairKey(value) === pairKey(pair));
          return <label key={pairKey(pair)} className="flex items-start gap-2 text-sm"><input className="mt-1 accent-primary" type="checkbox" checked={chosen} disabled={!offered} onChange={() => setPairs(previous => chosen ? previous.filter(value => pairKey(value) !== pairKey(pair)) : [...previous, pair])}/><span>{sample.label} / {item.title}{!offered && "（未在本次提出范围内）"}</span></label>;
        }))}</fieldset>}
        {cumulativeGaps.length > 0 && <p className="whitespace-pre-wrap text-xs opacity-70">原请求累计仍有覆盖差距，接收是否允许由服务器按明确部分范围复查：{cumulativeGaps.join(" ")}</p>}
        <section className="border-t border-border pt-4"><h3 className="flex items-center gap-2 font-medium"><ArrowBendUpLeft aria-hidden/>未接收项与缺项去向</h3>{omitted.length === 0 && (actionType !== "handoff.accept" || cumulativeGaps.length === 0) ? <p className="mt-2 text-sm opacity-70">当前所选范围没有待退缺项。</p> : <div className="mt-3 space-y-3"><ul className="list-inside list-disc space-y-1 text-sm">{omitted.map(item => <li key={`${item.kind}:${item.id}`} className="break-words">{item.label}</li>)}</ul><p className="text-xs opacity-70">本次明确退项或原请求剩余差距共用原因与下一责任人；已接收范围不重复退回。</p><div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm" htmlFor={`${prefix}-reason`}><span>本次部分接收或未接收原因</span><textarea id={`${prefix}-reason`} className={inputClass} required maxLength={2000} value={returnReason} onChange={event => setReturnReason(event.target.value)}/></label><label className="space-y-1 text-sm" htmlFor={`${prefix}-owner`}><span>剩余差距的下一责任人</span><select id={`${prefix}-owner`} className={inputClass} required value={nextOwnerId} onChange={event => setNextOwnerId(event.target.value)}><option value="">请选择当前可分派人员</option>{nextOwners.map(owner => <option key={owner.id} value={owner.id}>{owner.label}</option>)}</select></label></div></div>}</section>
      </fieldset>
      {!stateReady && <p className="text-sm opacity-70">当前请求状态尚不允许此动作；主线刷新后再办理。</p>}
      {context.portReady && !allowed && <p role="status" className="text-sm opacity-70">服务器未授予本次动作权限。</p>}
      {problems.length > 0 && <details className="text-sm"><summary className="cursor-pointer focus-visible:outline-2 focus-visible:outline-ring">当前范围待补项（{problems.length}）</summary><ul className="mt-2 list-inside list-disc space-y-1">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul></details>}
      <Button type="submit" disabled={!editable || !allowed || !stateReady}>核对{actionType === "handoff.accept" ? "接收" : actionType === "handoff.offer" ? "交接" : "退缺项"}范围</Button>
    </form>
    <VerificationActionReview action={action} ready={allowed && stateReady}/>
  </section>;
}
