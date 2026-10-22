"use client";

import { useEffect, useId, useRef, useState } from "react";
import { CalendarBlank, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { candidateProblem, checkNames, checkStatusNames, readinessNames, reservationNames, resourceKindNames, sourceText, validityCoverage, windowText, type ObservedTime, type ResourceCandidate, type ResourceReadinessProps, type ResourceRef } from "./contracts";

function resourceText(ref: ResourceRef) { return `${resourceKindNames[ref.kind]} ${ref.id} · v${ref.revision}`; }

function RealEvent({ label, event }: { label: string; event: ObservedTime | null }) {
  return <div className="min-w-0 rounded-lg border border-border p-3"><dt className="text-sm font-medium">{label}</dt><dd className="mt-1 break-words text-sm">{event ? `${event.occurredAt} · ${event.originalTimezone}` : "尚未发生或缺少真实事件证据"}</dd>{event && <dd className="mt-1 break-words text-xs text-muted-foreground">{sourceText(event.source)}</dd>}</div>;
}

export function ResourceReadiness({ view, context, candidates, action, onPrepare, actionReview }: ResourceReadinessProps) {
  const titleId = useId();
  const [preparing, setPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState("");
  const locked = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function prepare(candidate: ResourceCandidate) {
    if (locked.current || !onPrepare || candidateProblem(candidate, context, action, true)) return;
    locked.current = true; setPreparing(true); setPrepareError("");
    try { await onPrepare(candidate, context.key); }
    catch (error) { if (alive.current) setPrepareError(error instanceof Error ? error.message : "预览准备失败，请在主线核对；尚未取得预约回执。"); }
    finally { locked.current = false; if (alive.current) setPreparing(false); }
  }

  return <section className="min-w-0 space-y-5" aria-labelledby={titleId} aria-busy={preparing || action.busy}>
    <header className="space-y-2"><h2 id={titleId} className="text-lg font-semibold">{view.title}</h2><p className="text-sm font-medium">资源准备度：{readinessNames[view.status]}</p><p className="break-words text-sm text-muted-foreground">本轮执行区间 {windowText(view.window)}</p><p className="break-words text-xs text-muted-foreground">服务器核对时点 {view.asOf} · {view.id}</p></header>
    {(!context.portReady || !context.current) && <p role="status" className="flex gap-2 rounded-lg border border-border p-3 text-sm"><WarningCircle aria-hidden className="mt-0.5 shrink-0" /><span>{context.unavailableReason || "待主线接入或重新核对当前资源事实。"} 当前资源检查不构成执行授权或正式占用。</span></p>}
    <p className="text-sm text-muted-foreground">资格须覆盖完整执行区间；开测前仍需重核授权撤销、维护、证据撤回与资源版本。容量已核对不等于资格有效，也不等于正式预约。</p>
    <dl className="grid gap-3 sm:grid-cols-2"><RealEvent label="实物正式接收" event={view.physicalReceived} /><RealEvent label="Actual 实际开测" event={view.actualStarted} /></dl>
    <div className="space-y-3" aria-label="固定资源与资格范围">
      {!view.resources.length && <p className="rounded-lg border border-border p-3 text-sm">尚无固定资源范围 · UNKNOWN</p>}
      {view.resources.map(resource => <article key={`${resource.ref.kind}:${resource.ref.id}:${resource.ref.revision}`} className="min-w-0 rounded-lg border border-border p-4">
        <h3 className="break-words font-medium">{resource.label} · {readinessNames[resource.status]}</h3><p className="mt-1 break-words text-sm text-muted-foreground">{resourceText(resource.ref)} · {resource.units} 单位 · 用途：{resource.purpose}</p>
        {!resource.checks.length && <p className="mt-3 text-sm">资格证据尚未接入 · UNKNOWN</p>}
        <ul className="mt-3 space-y-3">{resource.checks.map((check, index) => {
          const coverage = validityCoverage(check.validity, view.window);
          return <li key={`${check.code}:${index}`} className="border-t border-border pt-3 text-sm"><p className="font-medium">{checkNames[check.kind]}：{checkStatusNames[check.status]}</p><p className="mt-1 whitespace-pre-wrap break-words">{check.detail}</p><p className="mt-1 break-words text-muted-foreground">适用用途：{check.purpose}</p>{check.validity && <><p className="mt-1 break-words">有效期 [{check.validity.validFrom ?? "未知"}, {check.validity.validUntil ?? "未知"})</p><p className={coverage === "not_covered" ? "mt-1 text-destructive" : "mt-1 text-muted-foreground"}>{coverage === "covered" ? "有效期覆盖完整执行区间；仍以服务器现行核对为准。" : coverage === "not_covered" ? "有效期未覆盖完整执行区间，需处理阻塞。" : "有效期或执行区间不明 · UNKNOWN"}</p></>}<p className="mt-1 break-words text-xs text-muted-foreground">{sourceText(check.source)}</p></li>;
        })}</ul>
        {resource.conditions.length > 0 && <div className="mt-3 rounded-lg border border-primary p-3 text-sm"><h4 className="font-medium">本用途限定条件</h4><ul className="mt-2 space-y-2">{resource.conditions.map(condition => <li key={condition.id}><p className="break-words">{condition.description}</p><p className="break-words text-muted-foreground">仅限 {condition.allowedPurpose} · 到期 {condition.expiresAt}</p><p className="break-words text-xs text-muted-foreground">{sourceText(condition.source)}</p></li>)}</ul></div>}
        <div className="mt-3 border-t border-border pt-3 text-sm"><h4 className="flex items-center gap-2 font-medium"><CalendarBlank aria-hidden />日历与容量</h4><p className="mt-1 break-words">{resource.calendar ? `${resource.calendar.id} · v${resource.calendar.revision} · ${resource.calendar.status === "current" ? "当前日历" : resource.calendar.status === "stale" ? "日历已过期" : "日历不明"}` : "日历版本未知"}</p><p className="mt-1">容量：{resource.capacity.status === "checked" ? "已核对（尚未占用）" : resource.capacity.status === "conflicted" ? "存在冲突" : "未知"}</p><p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">{resource.capacity.detail}</p>{resource.capacity.conflicts.length > 0 && <ul className="mt-2 space-y-2" aria-label="容量冲突">{resource.capacity.conflicts.map((conflict, index) => <li key={`${conflict.reservationId}:${index}`} className="break-words text-destructive">{conflict.reservationId} · {conflict.units} 单位 · {windowText(conflict.window)} · {conflict.detail}</li>)}</ul>}</div>
      </article>)}
    </div>
    <section className="space-y-3" aria-label="预约及释放取消历史"><h3 className="font-semibold">时段与正式预约记录</h3><p className="text-sm text-muted-foreground">暂定时段只用于准备。正式预约须资源与实际样件在同一事务内一起提交；接收和实际开测分别记录。</p>{!view.reservations.length && <p className="text-sm">尚无预约记录；资源检查通过不会自动占用。</p>}{view.reservations.map(reservation => <article key={`${reservation.id}:${reservation.revision}`} className="min-w-0 rounded-lg border border-border p-3 text-sm"><h4 className="break-words font-medium">{reservationNames[reservation.status]} · {reservation.id} · v{reservation.revision}</h4><p className="mt-1 break-words">{windowText(reservation.window)} · 用途：{reservation.purpose}</p><ul className="mt-2 space-y-1">{reservation.resources.map(resource => <li className="break-words" key={`${resource.ref.kind}:${resource.ref.id}`}>{resourceText(resource.ref)} · {resource.units} 单位</li>)}</ul><ol className="mt-3 space-y-2 border-t border-border pt-3" aria-label="保留的预约事件">{reservation.events.map((event, index) => <li key={`${event.kind}:${index}`}><p className="break-words">{reservationNames[event.kind]} · {event.at} · {event.actorLabel}</p><p className="whitespace-pre-wrap break-words">{event.reason}</p><p className="break-words text-xs text-muted-foreground">{sourceText(event.source)}</p></li>)}</ol></article>)}</section>
    <section className="space-y-3" aria-label="资源办理候选"><h3 className="font-semibold">资源办理候选</h3>{!candidates.length && <p className="text-sm">尚无服务器固定候选。</p>}{candidates.map(candidate => {
      const problem = candidateProblem(candidate, context, action, !!onPrepare);
      return <article key={candidate.id} className="min-w-0 rounded-lg border border-border p-3 text-sm"><h4 className="font-medium">{candidate.title} · {candidate.policy.tier === "T2" ? "具名决定" : "一次确认"}</h4><p className="mt-1 whitespace-pre-wrap break-words">{candidate.summary}</p><p className="mt-1 break-words text-muted-foreground">{windowText(candidate.window)}</p><p className="mt-1 break-words text-muted-foreground">{candidate.resources.map(resourceText).join("；")}</p>{problem && <p className="mt-2 break-words text-muted-foreground">{problem}</p>}<Button type="button" variant="outline" className="mt-3" disabled={preparing || !!problem} onClick={() => void prepare(candidate)}>交主线核对候选</Button></article>;
    })}<p className="text-sm text-muted-foreground">人员资格签发、校准接受、独立预约/释放/取消操作仍待政策注册与主线接线。治具具名验收沿 npi.fixture.accept；此处不授予真实资格。</p></section>
    {(prepareError || action.error) && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">{prepareError || action.error}</p>}
    {action.outcomeUnknown && <p role="alert" className="text-sm text-destructive">原动作结果未知，先由主线核对原回执；当前不能再次准备。</p>}
    {actionReview}
  </section>;
}
