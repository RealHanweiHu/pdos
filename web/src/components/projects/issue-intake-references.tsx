"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
export type ReferenceReviewDraft = { reference: Row; result: "unaffected" | "handled" | "follow_up"; explanation: string };
const reviewResults: Record<string, string> = { unaffected: "核对后无须处理", handled: "已沿原业务处理", follow_up: "仍需后续处理" };
function sameReference(left: Row, right: Row): boolean { return left.kind === right.kind && left.id === right.id && left.path_id === right.path_id; }
function referenceKey(value: Row): string { return `${text(value.kind)}:${text(value.id)}:${text(value.path_id)}`; }
type Cursor = { before_id: string; before_issue_id: string; before_path_id: string };
const labels: Record<string, string> = { historical_source: "历史决策原文来源（不代表本次批准）", historical_issue_links: "历史来源到本问题的具名关联依据", metrics: "测试指标", conditions: "测试条件", equipment: "测试设备", environment: "测试环境", started_at: "开始时间", evidence_refs: "原业务证据引用", follow_up_note: "后续处理说明", mitigation_plan: "风险应对措施", contingency_plan: "应急安排", ncr_updated_at: "NCR最近修改", ncr_nonconformity: "不符合项", ncr_containment_action: "NCR遏制措施", ncr_effectiveness_criteria: "NCR有效性判据", test_case_updated_at: "测试项最近修改", test_criteria: "测试项判据", test_method: "测试项方法", ecr_status: "变更当前状态", ecr_updated_at: "变更最近修改", follow_up_task_status: "后续任务状态", follow_up_task_updated_at: "后续任务最近修改", follow_up_task_evidence: "后续任务完成依据", status: "当前状态", draft_state: "登记状态", description: "说明", expected_output: "交付要求", completion_evidence_ref: "任务完成依据", due_date: "截止日期", target_date: "目标日期", completed_at: "完成时间", updated_at: "最近修改", created_at: "登记时间", outcome: "裁决结果", rationale: "裁决依据", consequence: "后续影响", follow_up_state: "执行跟进", acceptance_criteria: "测试判据", method: "测试方法", result_notes: "测试结果", executed_at: "实际测试时间", run_number: "测试次数", ncr_status: "NCR当前状态", reason: "关联或版本依据", action_type: "措施类型", completion_summary: "措施完成说明", version: "FMEA版本", revision_number: "变更范围版本", failure_mode: "失效模式", retraction_reason: "解除关联依据", retracted_at: "解除时间" };
const statuses: Record<string, string> = { todo: "待办", in_progress: "办理中", done: "任务完成", blocked: "阻塞", skipped: "已跳过", open: "开放", analysis: "分析中", action: "处理中", verification: "验证中", closed: "已关闭", draft: "草稿", confirmed: "已确认", verified: "已审核", archived: "已归档", passed: "通过", failed: "未通过", not_run: "未执行", planned: "已计划", pending: "待执行", completed: "已完成", none: "无后续安排", corrective: "纠正措施", preventive: "预防措施", mitigating: "处理中", watching: "持续观察" };
function obj(value: unknown): Row { if (!isRecord(value)) throw new Error("业务引用资料不完整"); return value; }
function rows(value: unknown): Row[] { if (!Array.isArray(value)) throw new Error("业务引用清单不完整"); return value.map(obj); }
function text(value: unknown): string { return value == null ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function cursor(value: unknown): Cursor | null { if (!isRecord(value)) return null; if (typeof value.before_id !== "string" || typeof value.before_issue_id !== "string" || typeof value.before_path_id !== "string") throw new Error("引用分页位置不完整"); return { before_id: value.before_id, before_issue_id: value.before_issue_id, before_path_id: value.before_path_id }; }
export function IssueIntakeReferences({ projectId, sourceId, issueId, reviews = [], onReviewsChange, disabled = false }: { projectId: string; sourceId: string; issueId?: string; reviews?: ReferenceReviewDraft[]; onReviewsChange?: (value: ReferenceReviewDraft[]) => void; disabled?: boolean }) {
  function choose(reference: Row, checked: boolean) {
    if (!onReviewsChange || disabled) return;
    onReviewsChange(checked ? [...reviews, { reference, result: "follow_up", explanation: "" }] : reviews.filter(review => !sameReference(review.reference, reference)));
  }
  function change(reference: Row, patch: Partial<ReferenceReviewDraft>) {
    if (!disabled) onReviewsChange?.(reviews.map(review => sameReference(review.reference, reference) ? { ...review, ...patch } : review));
  }
  const [data, setData] = useState<Row | null>(null), [items, setItems] = useState<Row[]>([]), [next, setNext] = useState<Cursor | null>(null);
  const [kind, setKind] = useState("task"), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [sourceChanged, setSourceChanged] = useState(false);
  async function load(selected = kind, more?: Cursor) {
    setBusy(true); setError(null);
    try {
      const query = new URLSearchParams({ kind: selected }); if (issueId) query.set("issue_id", issueId);
      if (more) for (const [key, value] of Object.entries(more)) query.set(key, value);
      const response = await fetch(`/api/projects/${projectId}/issue-intake-sources/${sourceId}/references?${query}`, { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "业务引用暂不可读，请稍后重试");
      const result = obj(value), incoming = rows(result.items), nextCursor = cursor(result.next);
      setSourceChanged(old => !!more && (old || !!data && JSON.stringify(data.current_source) !== JSON.stringify(result.current_source)));
      setItems(old => more ? [...old, ...incoming.filter(item => !old.some(existing => existing.id === item.id && existing.issue_id === item.issue_id && existing.path_id === item.path_id))] : incoming);
      setData(result); setKind(selected); setNext(nextCursor);
    } catch (e) { setError(e instanceof Error ? e.message : "业务引用读取失败"); } finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">核对相关问题的后续业务引用</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">{issueId ? "查看本任务对应问题的后续记录。" : "查看本来源最初及历次关联问题的后续记录。"}实际引用不等于已经确定受影响；请进入原业务核对并办理。</p>
      <div className="flex flex-wrap items-center gap-2">{data && <label>业务类型<select className="ml-2 rounded-md border bg-background p-2" value={kind} disabled={busy || disabled} onChange={e => void load(e.target.value)}>{rows(data.kinds).map(item => <option key={text(item.kind)} value={text(item.kind)}>{text(item.label)}</option>)}</select></label>}<Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => void load()}>刷新本类引用</Button></div>
      {data && <><p>{text(data.coverage)}</p><p className="text-muted-foreground">{text(data.remaining)}</p><p>来源当前纠错版本 {text(obj(data.current_source).revision)} · 最近读取 {text(data.read_at)}</p></>}
      {sourceChanged && <p className="text-destructive">翻页期间来源又有纠错，请刷新本类引用后重新核对。业务变化也可能改变其他已读页面。</p>}
      {data && !items.length && <p>本类当前未查到明确引用；其他业务类型需分别核对。</p>}
      {items.map(item => { const facts = obj(item.facts), chosen = reviews.find(review => sameReference(review.reference, item)); return <article key={`${text(item.id)}:${text(item.issue_id)}:${text(item.path_id)}`} className="space-y-2 rounded-md border p-3">
        {onReviewsChange && <label className="flex gap-2"><input type="checkbox" checked={!!chosen} disabled={busy || disabled || !chosen && reviews.length >= 50} onChange={e => choose(item, e.target.checked)}/>纳入本次办理结果</label>}
        <p className="font-medium">{text(item.title)}</p>
        {chosen && chosen.reference.digest !== item.digest && <div className="space-y-2"><p className="text-destructive">已选版本与当前读取值不同。请比较变化后重新核对。</p><Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => change(item, { reference: item })}>改用当前记录版本</Button></div>}<p>关联问题：<a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(item.issue_id)}`}>{text(item.issue_title)}</a></p>
        {facts.via_title != null && <p>经过：{text(facts.via_title)}</p>}
        {facts.retraction_id != null && <p className="text-muted-foreground">该问题与NCR的关联已解除，历史路径保留；NCR及措施本身仍按当前业务状态展示。</p>}
        {typeof facts.is_latest_version === "boolean" && <p>{facts.is_latest_version ? "此对象最新修订版本" : "历史修订版本，曾引用本问题"}{typeof facts.was_published === "boolean" ? facts.was_published ? " · 曾发布" : " · 尚无发布记录" : ""}</p>}
        {typeof item.href === "string" && (item.href.startsWith("/projects?") || item.href.startsWith("/knowledge")) && <a className="text-primary underline" href={item.href}>进入原业务页面核对</a>}
        {typeof facts.follow_up_task_id === "string" && <a className="ml-3 text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${facts.follow_up_task_id}`}>查看裁决后续任务</a>}
        {typeof facts.evidence_document_id === "string" && <a className="ml-3 text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${facts.evidence_document_id}`}>查看当次测试证据</a>}
        <details><summary className="cursor-pointer">当前事实与原关系依据</summary><dl className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(labels).filter(([key]) => facts[key] != null).map(([key, label]) => <div key={key}><dt className="text-muted-foreground">{label}</dt><dd className="max-h-48 overflow-auto whitespace-pre-wrap break-words">{["status", "draft_state", "follow_up_state", "action_type"].includes(key) ? statuses[text(facts[key])] ?? text(facts[key]) : text(facts[key])}</dd></div>)}</dl><p className="mt-2 break-all text-muted-foreground">原记录：{text(item.id)} · 本次事实摘要：{text(item.digest)}</p></details>
      </article>; })}
      {onReviewsChange && reviews.length > 0 && <section className="space-y-3 rounded-md border p-3"><p className="font-medium">本次已选 {reviews.length} 项业务引用（最多50项）</p><p>切换类型或刷新保留已选版本。逐项说明实际办理情况；未纳入的记录和范围仍须另行核对。</p>
        {reviews.map(review => <div key={referenceKey(review.reference)} className="space-y-2 border-t pt-2"><p className="font-medium">{text(review.reference.title)}</p><label className="block">逐项核对结果<select className="ml-2 rounded-md border bg-background p-2" value={review.result} disabled={disabled} onChange={e => change(review.reference, { result: e.target.value as ReferenceReviewDraft["result"] })}>{Object.entries(reviewResults).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label className="block">处理依据、实际结果或后续要求<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={4000} disabled={disabled} value={review.explanation} onChange={e => change(review.reference, { explanation: e.target.value })}/></label><ReferenceFacts value={obj(review.reference.facts)}/><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => choose(review.reference, false)}>移除此项核对</Button></div>)}
      </section>}
      {next && <Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => void load(kind, next)}>继续读取本类引用</Button>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}


function ReferenceFacts({ value }: { value: Row }) {
  return <details><summary className="cursor-pointer">查看所选记录版本的实际值</summary><dl className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(labels).filter(([key]) => value[key] != null).map(([key, label]) => <div key={key}><dt className="text-muted-foreground">{label}</dt><dd className="max-h-48 overflow-auto whitespace-pre-wrap break-words">{["status", "draft_state", "follow_up_state", "action_type"].includes(key) ? statuses[text(value[key])] ?? text(value[key]) : text(value[key])}</dd></div>)}</dl></details>;
}

export function ReferenceReviewHistory({ items }: { items: Row[] }) {
  if (!items.length) return null;
  return <section className="space-y-2"><p className="font-medium">本次逐项核对的业务记录</p><p className="text-muted-foreground">仅展示当前有权读取的业务引用。这里保存具名核对结论，业务对象的验证和关闭仍以原流程为准。</p>{items.map(item => {
    const original = obj(item.snapshot), current = isRecord(item.current) ? item.current : null;
    const before = obj(original.facts), after = current ? obj(current.facts) : null;
    const changed = after ? Object.keys({ ...before, ...after }).filter(key => key !== "issue_title" && JSON.stringify(before[key]) !== JSON.stringify(after[key])) : [];
    return <article key={referenceKey(item)} className="space-y-2 rounded-md border p-2"><p className="font-medium">{text(original.title)} · {reviewResults[text(item.result)] ?? text(item.result)}</p><p className="whitespace-pre-wrap">{text(item.explanation)}</p>{typeof original.href === "string" && (original.href.startsWith("/projects?") || original.href.startsWith("/knowledge")) && <a className="text-primary underline" href={original.href}>进入原业务页面</a>}
      {item.changed === true && <p className="text-destructive">{current ? "原业务值或关系已有变化，请重新核对本次结论。" : "此引用路径当前已不存在或不可读；原核对版本保留。"}</p>}
      <ReferenceFacts value={before}/>{changed.length > 0 && <details><summary className="cursor-pointer">与当前值的变化（{changed.length}项）</summary><div className="overflow-x-auto"><table className="mt-2 w-full text-left"><thead><tr><th>字段</th><th>登记时</th><th>当前值</th></tr></thead><tbody>{changed.map(key => <tr key={key} className="border-t"><td className="p-2 align-top">{labels[key] ?? ({ is_latest_version: "是否最新版本", was_published: "是否曾发布", retraction_id: "解除记录", path_id: "引用路径", via_title: "关联对象名称" } as Record<string, string>)[key] ?? key}</td><td className="max-w-72 whitespace-pre-wrap break-words p-2 align-top">{text(before[key])}</td><td className="max-w-72 whitespace-pre-wrap break-words p-2 align-top">{text(after?.[key])}</td></tr>)}</tbody></table></div></details>}
    </article>;
  })}</section>;
}
