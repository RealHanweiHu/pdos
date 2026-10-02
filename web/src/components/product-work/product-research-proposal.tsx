"use client";

import { useEffect, useId, useRef, useState } from "react";
import { productWorkHref } from "./product-work-navigation";
import { Button } from "@/components/ui/button";
import { ProductRequestError, request } from "./product-work-api";

type Plan = { question: string; user_groups: string[]; regions: string[]; time_scope: string; method: string; expected_decision: string; stop_conditions: string[] };
type Finding = { id: string; run_id: string; status: string; proposed_digest: string; accepted_digest: string | null; proposed_payload: { assessment: { research_plan: Plan } }; accepted_payload: { proposal: Plan } | null; review_comment: string | null; applied_entity_id: string | null };
type Read = { finding: Finding | null; sources_current: boolean; owner_user_id: string; product_line_id: string | null };
const fields: { key: keyof Plan; label: string; list?: boolean }[] = [
  { key: "question", label: "研究问题" }, { key: "user_groups", label: "用户群体", list: true },
  { key: "regions", label: "地域范围", list: true }, { key: "time_scope", label: "时间范围" },
  { key: "method", label: "研究方法" }, { key: "expected_decision", label: "预期支持的决策" },
  { key: "stop_conditions", label: "停止条件", list: true },
];
type Form = Record<keyof Plan, string>;
function toForm(plan: Plan): Form {
  return Object.fromEntries(fields.map(({ key }) => [key, Array.isArray(plan[key]) ? plan[key].join("\n") : plan[key]])) as Form;
}
function toPlan(form: Form): Plan {
  return Object.fromEntries(fields.map(({ key, list }) => [key, list ? form[key].split("\n").map(v => v.trim()).filter(Boolean) : form[key].trim()])) as Plan;
}

export function ProductResearchProposal({ base, runId, disabled, autoLoad = false, onPendingChange, onFailure, onAccessDenied }: { base: string; runId: string; disabled: boolean; autoLoad?: boolean; onPendingChange?: (value: boolean) => void; onFailure?: (message: string) => void; onAccessDenied?: (message: string) => void }) {
  const [record, setRecord] = useState<Read | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const autoRead = useRef(false);
  const live = useRef(true);
  const prefix = useId();
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => { if (autoLoad && !autoRead.current) { autoRead.current = true; void load(); } });
  async function load() {
    setBusy(true); setError(""); setRecord(null); setForm(null); setComment(""); setEditing(false);
    try {
      const value = await request<Read>(`${base}/research-ai-finding`, "POST", { run_id: runId });
      if (!live.current) return;
      setRecord(value);
      if (value.finding) { setForm(toForm(value.finding.accepted_payload?.proposal ?? value.finding.proposed_payload.assessment.research_plan)); setComment(value.finding.review_comment ?? ""); }
    } catch (failure) {
      if (live.current && failure instanceof ProductRequestError && [401, 403].includes(failure.status)) onAccessDenied?.(failure.message);
      if (live.current) onFailure?.(failure instanceof Error ? failure.message : "读取或办理未确认，请刷新分析和候选状态后继续"); if (live.current) setError(failure instanceof Error ? failure.message : "候选暂不可读"); }
    finally { if (live.current) setBusy(false); }
  }
  async function mutate(decision: "accepted" | "rejected" | "apply") {
    const finding = record?.finding;
    if (!finding || !form) return;
    setBusy(true); setError(""); onPendingChange?.(true);
    try {
      const value = await request<{ finding: Finding }>(`${base}/research-ai-${decision === "apply" ? "apply" : "review"}`, "POST", decision === "apply" ? {
        run_id: runId, finding_id: finding.id, accepted_digest: finding.accepted_digest,
      } : { run_id: runId, finding_id: finding.id, expected_digest: finding.proposed_digest, decision, comment: comment.trim(), proposal: decision === "accepted" ? toPlan(form) : null });
      if (live.current) { setRecord({ ...record!, finding: value.finding }); setForm(toForm(value.finding.accepted_payload?.proposal ?? value.finding.proposed_payload.assessment.research_plan)); }
    } catch (failure) {
      if (live.current && failure instanceof ProductRequestError && [401, 403].includes(failure.status)) onAccessDenied?.(failure.message);
      if (live.current) onFailure?.(failure instanceof Error ? failure.message : "读取或办理未确认，请刷新分析和候选状态后继续");
      if (live.current) { setRecord(null); setForm(null); setComment(""); setError(`${failure instanceof Error ? failure.message : "办理结果未确认"}。请重新读取候选状态后继续。`); }
    } finally { if (live.current) setBusy(false); onPendingChange?.(false); }
  }
  const finding = record?.finding;
  const pending = finding?.status === "pending_review";
  const editable = pending && !disabled && record?.sources_current;
  return <section aria-label="研究计划候选" className="space-y-3 rounded-md border p-3">
    <h4 className="font-medium">研究计划候选</h4>
    <p className="text-muted-foreground">先核对计划并接受，再单独应用为研究草稿。负责人固定为你，产品线沿用原分析范围；研究开始与结论仍需另行办理。</p>
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>读取 / 刷新研究候选</Button>
    {busy && <p role="status">正在核对或办理…</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {record && !finding && <p>本次没有可办理的研究候选。可查看分析建议与缺项；候选质量收窄时也不会生成办理入口。</p>}
    {finding && form && <>
      <p>{({ pending_review: "待核对", accepted: "已接受，尚未创建任务", rejected: "已拒绝", applied: "已应用为研究草稿" } as Record<string, string>)[finding.status]}</p>
      {!record?.sources_current && <p className="text-primary">原资料已变化，候选仅供追溯；请重新分析后接受或应用。</p>}
      <details><summary className="cursor-pointer">查看 AI 原始计划</summary>{fields.map(({ key, label }) => <p key={key} className="mt-2 whitespace-pre-wrap"><span className="font-medium">{label}：</span>{toForm(finding.proposed_payload.assessment.research_plan)[key]}</p>)}</details>
      {editing ? fields.map(({ key, label, list }) => <div key={key} className="space-y-1"><label htmlFor={`${prefix}-${key}`}>{label}{list ? "（每行一项）" : ""}</label><textarea className="w-full rounded-md border bg-background p-2 text-sm disabled:opacity-60" id={`${prefix}-${key}`} value={form[key]} disabled={busy || !editable} maxLength={list ? 61500 : 2048} onChange={event => setForm({ ...form, [key]: event.target.value })}/></div>) : <dl className="grid gap-x-4 gap-y-3 rounded-md bg-muted/40 p-4 sm:grid-cols-[7rem_minmax(0,1fr)]">{fields.map(({ key, label }) => <div key={key} className="contents"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="whitespace-pre-wrap break-words text-sm leading-6">{form[key] || "待补充"}</dd></div>)}</dl>}
      {editable && <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(!editing)}>{editing ? "完成修订，查看草案" : "修订这份计划"}</Button>}
      <label className="block" htmlFor={`${prefix}-comment`}>办理说明</label><textarea className="w-full rounded-md border bg-background p-2 text-sm disabled:opacity-60" id={`${prefix}-comment`} value={comment} disabled={busy || !pending || disabled} maxLength={2048} onChange={event => setComment(event.target.value)}/>
      {pending && <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || !editable || !comment.trim() || fields.some(({ key }) => !form[key].trim())} onClick={() => void mutate("accepted")}>接受核对后的计划</Button><Button size="sm" variant="outline" disabled={busy || disabled || !comment.trim()} onClick={() => void mutate("rejected")}>拒绝此候选</Button></div>}
      {finding.status === "accepted" && <Button size="sm" disabled={busy || disabled || !record?.sources_current} onClick={() => void mutate("apply")}>独立应用：创建研究草稿</Button>}
      {finding.status === "applied" && <a className="inline-flex min-h-11 items-center text-primary underline" href={productWorkHref(base.split("/").at(-1) ?? "", "research", record?.product_line_id ?? "", `research-${finding.applied_entity_id}`)}>打开研究任务</a>}
    </>}
  </section>;
}
