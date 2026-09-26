"use client";

import { DecisionSourceBatches } from "./decision-intake-batch-progress";
import { DecisionInitializationWork } from "./decision-initialization-work";
import { EmailExtractionNotice } from "@/components/ai/email-extraction-notice";
import { useState } from "react";
import { DecisionHistoryAmendment } from "./decision-history-amendment";
import { DecisionSourceCorrection } from "./decision-source-correction";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const names: Record<string, string> = { title: "标题", outcome: "结论", context: "背景", options: "考虑过的选项", trade_offs: "权衡", rationale: "理由", consequence: "后果及后续要求", historical_date: "历史日期", historical_approver: "原文批准人", historical_owner: "原文负责人", historical_kind: "原文决策类型", historical_state: "原文办理状态", external_ref: "原决策编号", issue_ref: "原问题编号或说明" };
export type HistoricalDecisionSource = { amendment_id?: string; replaces_decision_id?: string; corrected_facts?: Record<string, string | null>; corrected_missing_fields?: string[]; historical_date?: string | null; raw_date?: string | null; raw_approver?: string | null; raw_owner?: string | null; raw_kind?: string | null; raw_state?: string | null; external_ref?: string | null; issue_ref?: string | null; missing_fields?: string[]; review_note?: string; document_id: string };
export function DecisionIntakeSource({ projectId, decisionId, history, registeredAt, originState, onChanged }: { projectId: string; decisionId: string; history: HistoricalDecisionSource; registeredAt: string; originState?: Record<string, unknown> | null; onChanged?: () => Promise<void> }) {
  return <section className="my-2 space-y-2 rounded-md border p-3 text-xs">
    {originState && originState.on_this_decision === false && <p className="text-destructive">{originState.state === "withdrawn" ? "原来源关联已撤回" : "原来源已改关联其他决策"} · 修订 {String(originState.revision)}。此处保留登记时原文与历史。</p>}
    {history.amendment_id && <section className="space-y-2 border-b pb-2"><p className="font-medium">此记录包含具名历史内容更正</p>{history.replaces_decision_id && <a className="text-primary underline" href={`/projects?project=${projectId}&tab=decisions#decision-${history.replaces_decision_id}`}>查看更正前记录</a>}<dl className="space-y-1">{Object.entries(history.corrected_facts ?? {}).map(([key, value]) => <div key={key}><dt className="inline font-medium">更正后{names[key] ?? key}：</dt><dd className="inline whitespace-pre-wrap">{value || "未提供"}</dd></div>)}</dl>{!!history.corrected_missing_fields?.length && <p>更正后仍缺：{history.corrected_missing_fields.map(key => key === "options_text" ? "选项原文" : names[key] ?? key).join("、")}</p>}</section>}
    <p className="font-medium">历史原文登记 · 历史日期：{history.historical_date || "未提供"}</p>
    <p>原文批准人：{history.raw_approver || "未提供"} · 原文负责人：{history.raw_owner || "未提供"}</p><p>原文类型：{history.raw_kind || "未提供"} · 原文办理状态：{history.raw_state || "未提供"}</p>
    <p>原决策编号：{history.external_ref || "未提供"} · 原问题编号/说明：{history.issue_ref || "未提供"}</p>
    {!!history.missing_fields?.length && <p>原文缺项：{history.missing_fields.map(key => names[key] ?? key).join("、")}</p>}
    <p className="whitespace-pre-wrap">{history.amendment_id ? "本次更正依据" : "登记核对说明"}：{history.review_note}</p><p>本次登记于 {new Date(registeredAt).toLocaleString()}。此处保留原文出处及具名更正依据，不代表本次批准或当前执行结果。</p>
    <a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${history.document_id}`}>查看项目原件</a>
    <DecisionInitializationWork projectId={projectId} decisionId={decisionId}/>
    <DecisionSourceRows projectId={projectId} decisionId={decisionId} onChanged={onChanged}/>
  </section>;
}


function show(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
export function DecisionSourceRows({ projectId, decisionId, issueId, onChanged }: { projectId: string; decisionId?: string; issueId?: string; onChanged?: () => Promise<void> }) {
  const [data, setData] = useState<Record<string, unknown>[] | null>(null), [cursor, setCursor] = useState<Record<string, unknown> | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const query = new URLSearchParams();
      if (more && cursor) for (const key of ["before_created_at", "before_id"]) query.set(key, String(cursor[key]));
      const path = decisionId ? `decisions/${decisionId}/intake-sources` : `issues/${issueId}/decision-intake-sources`;
      const response = await fetch(`/api/projects/${projectId}/${path}${query.size ? `?${query}` : ""}`, { cache: "no-store" }), body: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(body) || !Array.isArray(body.items) || !body.items.every(isRecord)) throw new Error("原文来源暂不可用，请稍后重试");
      const next = body.items; setData(old => more ? [...(old ?? []), ...next.filter(item => !old?.some(prior => prior.id === item.id))] : next); setCursor(isRecord(body.next) ? body.next : null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  return <details className="space-y-2 rounded-md border p-3 text-xs" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}><summary className="cursor-pointer font-medium">{issueId ? "历史决策来源与明确关联" : "历史文件来源与关联问题"}</summary>
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新来源</Button>
    {data?.length === 0 && <p>暂无历史决策来源关联。</p>}
    {data?.map(item => {
      const source = isRecord(item.source_snapshot) ? item.source_snapshot : {}, row = isRecord(source.row) ? source.row : {}, original = isRecord(row.original) ? row.original : {}, current = isRecord(item.current_decision) ? item.current_decision : {}, issue = isRecord(item.current_issue) ? item.current_issue : {}, before = isRecord(item.created_snapshot) ? item.created_snapshot : {}, oldIssue = isRecord(item.issue_snapshot) ? item.issue_snapshot : {};
      return <article key={String(item.id)} className="space-y-2 border-t pt-3">
        <p className={item.on_this_target === false ? "text-destructive" : "font-medium"}>{item.state === "withdrawn" ? "来源关联已撤回，保留历史" : item.on_this_target === false ? "此来源当前关联其他对象，保留历史" : "此对象的当前来源关联"} · 修订 {show(item.revision)}</p>
        {!!item.revision && <p className="whitespace-pre-wrap">最近修订依据：{show(item.reason)}<br/>影响及处理：{show(item.impact_note)}</p>}
        <p className="font-medium">{show(source.filename)} · {show(item.locator)} · {item.link_kind === "linked" ? "人工复用已有决策" : "历史决策登记"}</p>
        <p>核对人：{show(item.reviewed_by_name || item.created_by_user_id)} · {show(item.created_at)}</p>
        <p className="whitespace-pre-wrap">核对说明：{show(item.review_note)}<br/>许可依据：{show(source.permission_basis)}<br/>用途：{show(source.purpose)}</p>
        {item.link_kind === "linked" && <p className="whitespace-pre-wrap">复用依据：{show(item.reuse_reason)}</p>}
        <p>当前决策：{show(current.title)} · {show(current.decision_kind)}<br/>当前结论：{show(current.outcome)}</p>
        {!!item.current_issue_id && <p className="whitespace-pre-wrap">关联问题：{show(issue.title)} · 当前状态：{show(issue.status)}<br/>关联依据：{show(item.issue_reason)}</p>}
        {item.decision_changed === true && <p className="text-destructive">复用决策已变化，历史文件和原核对记录保留；请重新核对当前记录。</p>}
        {item.issue_changed === true && <p className="text-destructive">关联问题已变化，原关联依据需结合当前办理情况核对。</p>}
        <div className="flex flex-wrap gap-3">{[["decision_href", "打开最初决策"], ["current_decision_href", "打开当前关联决策"], ["issue_href", "打开当前关联问题"], ["document_href", "查看项目原件"]].map(([key, label]) => typeof item[key] === "string" && <a key={key} className="text-primary underline" href={String(item[key])}>{label}</a>)}</div>
        {isRecord(source.additional_documents) && Object.entries(source.additional_documents).map(([key, doc]) => isRecord(doc) && <p key={key}><a className="text-primary underline" href={String(doc.href)}>引用原件：{String(doc.filename)}</a> · {String(doc.sha256)}</p>)}
          <EmailExtractionNotice metadata={source.extraction_metadata}/>
          <details><summary className="cursor-pointer">逐字段原文及来源位置</summary><dl className="space-y-2">{Object.entries(original).map(([key, value]) => isRecord(value) && <div key={key}><dt className="font-medium">{names[key] ?? key} · {show(value.cell)}</dt><dd className="max-h-48 overflow-auto whitespace-pre-wrap break-words">{show(value.value)}</dd></div>)}</dl></details>
        <details><summary className="cursor-pointer">原关联时的记录与当前值</summary><div className="overflow-auto"><table className="w-full text-left"><thead><tr><th>对象/字段</th><th>当时记录</th><th>当前记录</th></tr></thead><tbody>{[...Object.keys(before).map(key => ({ label: `决策 · ${names[key] ?? key}`, before: before[key], current: current[key] })), ...Object.keys(oldIssue).map(key => ({ label: `问题 · ${key}`, before: oldIssue[key], current: issue[key] }))].map(item => <tr key={item.label} className="border-t"><td className="p-2 align-top">{item.label}</td><td className="max-w-80 whitespace-pre-wrap break-words p-2 align-top">{show(item.before)}</td><td className="max-w-80 whitespace-pre-wrap break-words p-2 align-top">{show(item.current)}</td></tr>)}</tbody></table></div></details>
        <DecisionSourceBatches projectId={projectId} sourceId={String(item.id)}/>
        <DecisionHistoryAmendment projectId={projectId} sourceId={String(item.id)} onChanged={async () => { await load(); await onChanged?.(); }}/>
        <DecisionSourceCorrection projectId={projectId} sourceId={String(item.id)} onChanged={async () => { await load(); await onChanged?.(); }}/>
      </article>;
    })}
    {cursor && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>读取更早来源</Button>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </details>;
}
