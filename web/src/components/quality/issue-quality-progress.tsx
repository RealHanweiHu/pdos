"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "./fmea-sources";
import { EvidenceValue, qualityRequest } from "./quality-operation-evidence";

const stages: Record<string, string> = { open: "NCR 已建立", containment: "遏制中", root_cause: "根因调查", action: "措施执行", verification: "有效性验证", closed: "NCR 已关闭" };

export function IssueQualityProgress(props: { projectId: string; ncrId: string }) {
  return <Progress key={`${props.projectId}:${props.ncrId}`} {...props}/>;
}

function Progress({ projectId, ncrId }: { projectId: string; ncrId: string }) {
  const [data, setData] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const active = useRef(true), loading = useRef(false), attempted = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);

  async function load() {
    if (loading.current) return;
    loading.current = true; attempted.current = true;
    setBusy(true); setError(""); setData(null);
    try {
      const value = await qualityRequest(projectId, ncrId, "/workspace");
      if (obj(value.ncr).id !== ncrId || !Array.isArray(value.root_causes) || !Array.isArray(value.actions) || !Array.isArray(value.reviews) || !value.record_evidence || typeof value.record_evidence !== "object" || Array.isArray(value.record_evidence)) {
        throw new Error("质量进展返回不完整，请重新读取原 NCR。");
      }
      if (active.current) setData(value);
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : "质量进展读取失败，请重试。");
    } finally {
      loading.current = false;
      if (active.current) setBusy(false);
    }
  }

  const ncr = obj(data?.ncr), people = obj(data?.people), evidence = obj(data?.record_evidence);
  const name = (id: unknown) => text(people[text(id)]) || "具名人员当前不可用";
  return <details className="rounded-md border p-3 text-sm" onToggle={e => {
    if (e.target === e.currentTarget && e.currentTarget.open && !attempted.current) void load();
  }}>
    <summary className="cursor-pointer font-medium">回查整改、复测与独立验证证据</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">措施完成、验证有效、NCR 关闭和问题关闭分别办理。以下证据为读取时的原记录；提交当时的证据快照可在原 NCR 的持久办理回执中查看。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新质量证据</Button>
      {busy && <p role="status">正在读取原 NCR 进展…</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {data && <>
        <p>{text(ncr.code)} · {stages[text(ncr.status)] ?? text(ncr.status)} · 读取时间 {text(data.server_time)}</p>
        {ncr.containment_action != null && <p className="whitespace-pre-wrap">已登记遏制：{text(ncr.containment_action)}</p>}
        <details className="rounded-md border p-2"><summary className="cursor-pointer">根因调查与独立审核（{rows(data.root_causes).length}）</summary>
          {!rows(data.root_causes).length && <p>尚无根因调查记录。</p>}
          {rows(data.root_causes).map(root => <article key={text(root.id)} className="mt-2 space-y-2 border-t pt-2">
            <p>v{text(root.version)} · {root.status === "approved" ? "已独立批准" : root.status === "superseded" ? "已被修订替代" : "待独立审核"} · 调查人 {name(root.analyst_user_id)}</p>
            <p className="whitespace-pre-wrap">调查过程：{text(root.analysis)}</p><p className="whitespace-pre-wrap">根因判断：{text(root.root_cause)}</p>
            {root.approved_by_user_id != null && <p>批准人：{name(root.approved_by_user_id)} · {text(root.approved_at)}</p>}
            <RecordEvidence items={rows(evidence[text(root.id)])}/>
          </article>)}
        </details>
        <details className="rounded-md border p-2"><summary className="cursor-pointer">纠正、预防与补充措施（{rows(data.actions).length}）</summary>
          {!rows(data.actions).length && <p>尚无整改措施。</p>}
          {rows(data.actions).map(action => <article key={text(action.id)} className="mt-2 space-y-2 border-t pt-2">
            <p>{action.action_type === "preventive" ? "预防措施" : "纠正措施"} · {({ planned: "待执行", in_progress: "执行中", completed: "措施已完成" } as Record<string, string>)[text(action.status)] ?? text(action.status)} · {name(action.owner_user_id)}</p>
            {Array.isArray(data.followup_action_ids) && data.followup_action_ids.includes(action.id) && <p className="text-primary">最近一次无效复核后新增的补充措施</p>}
            <p className="whitespace-pre-wrap">{text(action.description)}</p><p>目标日期：{text(action.due_date)}{action.completed_at != null && ` · 实际完成：${text(action.completed_at)}`}</p>
            {action.completion_summary != null && <p className="whitespace-pre-wrap">完成说明：{text(action.completion_summary)}</p>}
            <RecordEvidence items={rows(evidence[text(action.id)])}/>
          </article>)}
          {ncr.preventive_not_applicable_reason != null && <p className="mt-2 whitespace-pre-wrap">预防措施不适用：{text(ncr.preventive_not_applicable_reason)} · 批准人 {name(ncr.preventive_disposition_approved_by_user_id)}</p>}
        </details>
        {ncr.observation_due_at != null && <div><p>当前观察结束：{text(ncr.observation_due_at)}</p><p className="whitespace-pre-wrap">当前验证判据：{text(ncr.effectiveness_criteria)}</p></div>}
        <details className="rounded-md border p-2"><summary className="cursor-pointer">独立有效性验证历史（{rows(data.reviews).length}）</summary>
          {!rows(data.reviews).length && <p>尚无独立有效性结论。</p>}
          {rows(data.reviews).map(review => <article key={text(review.id)} className="mt-2 space-y-2 border-t pt-2">
            <p>第 {text(review.review_number)} 次 · {review.result === "effective" ? "验证有效" : "验证无效，需补充措施"} · 验证人 {name(review.reviewer_user_id)} · {text(review.reviewed_at)}</p>
            <p>原观察结束：{text(review.observation_due_at)}</p><p className="whitespace-pre-wrap">原验证判据：{text(review.criteria)}</p><p className="whitespace-pre-wrap">实际结果：{text(review.actual_result)}</p>
            <RecordEvidence items={rows(evidence[text(review.id)])}/>
          </article>)}
        </details>
      </>}
    </div>
  </details>;
}

function RecordEvidence({ items }: { items: Row[] }) {
  return <details className="text-xs"><summary className="cursor-pointer">所用证据当前记录（{items.length}）</summary>
    {!items.length && <p>此记录未附证据引用。</p>}
    {items.map(ref => <div className="my-2 rounded-md border p-2" key={`${ref.kind}:${ref.reference}`}>
      {ref.available === true ? <EvidenceValue value={obj(ref.value)}/> : <p className="text-destructive">原证据当前不可用：{text(ref.kind)} · {text(ref.reference)}</p>}
    </div>)}
  </details>;
}
