"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { scopeKinds, sourceLabel } from "./change-impact-scope";
import { impactAxes } from "./id-change-impact-form";
import { QuietCreationHistory } from "./change-quiet-adoption";
import { QuietAnchorValue } from "./change-quiet-sources";

const date = (v: unknown) => typeof v === "string" ? new Date(v).toLocaleString("zh-CN") : "未记录";
const values = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const ecrStatus: Record<string, string> = { request: "已提出", impact_analysis: "分析中", approval: "待审批", approved: "已批准", rejected: "已驳回", cancelled: "已取消" };
const ecnStatus: Record<string, string> = { ecn: "已开立", effectivity_decision: "待生效裁决", erp_handoff: "进入 ERP 交接", cancelled: "已取消" };
const actions: Record<string, string> = { retest: "复验", rereview: "复审", recertification: "复认证", coordination: "协同", none: "无需行动" };
const outcomes: Record<string, string> = { approved: "批准", rejected: "驳回", affected: "受影响", unaffected: "无影响（有据）", unknown: "尚未明确" };
const executionStatus: Record<string, string> = { unassigned: "待安排", no_result: "待结果", returned: "退回补齐", evidence_gaps: "证据待重核", follow_up: "待后续处理", recorded: "已记录", awaiting_confirmation: "待独立确认", verified: "当前证据支持确认", no_action: "无需执行" };

export function ChangeDecisionSummary({ projectId, ecrId }: { projectId: string; ecrId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function read() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/projects/${projectId}/changes/ecrs/${ecrId}/decision-summary`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(text(obj(obj(body).detail).message) || "变更摘要暂不可读");
      setData(obj(body));
    } catch (e) { setData(null); setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  const facts = obj(data?.facts), ecr = obj(facts.ecr), scope = obj(data?.bound_scope), snapshot = obj(scope.snapshot);
  const quiet = obj(data?.quiet), execution = obj(data?.execution);
  const person = (id: unknown) => !id ? "未记录" : text(rows(data?.people).find(p => p.id === id)?.display_name) || "原具名人员";
  function openExecution() { const target = document.getElementById(`change-execution-${ecrId}`); if (target instanceof HTMLDetailsElement) target.open = true; target?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  return <details className="my-3 space-y-3 rounded-md border p-3 text-sm" onToggle={e => { if (e.currentTarget.open && !data && !busy) void read(); }}><summary className="cursor-pointer font-medium">变更决策摘要 · 依据、未知与执行去向</summary>
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read()}>刷新摘要</Button>
    {busy && <p role="status">正在核对原变更、冻结记录与执行结果…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    {data && !busy && <div className="space-y-4 text-xs">
      <p className="text-muted-foreground">读取于 {date(data.read_at)}。以下汇总已保存的业务记录；未记录的专业分析不能据此判为无影响。</p>
      <section className="space-y-2"><p className="font-medium">已记录事实</p><p>{text(ecr.code)} · {text(ecr.title)} · {ecrStatus[text(ecr.status)] ?? "状态待核对"}</p>
        <p>申请：{person(ecr.requested_by_user_id)} · {date(ecr.created_at)}；最近提交分析：{person(ecr.analyzed_by_user_id)} · {date(ecr.analyzed_at)}</p>
        {rows(facts.decisions).filter(d => d.id === ecr.approval_decision_id).map(d => <div key={text(d.id)}><p>ECR 实际裁决：{outcomes[text(d.outcome)] ?? text(d.outcome)} · {person(d.decided_by_user_id)} · {date(d.decided_at)}</p><p>{text(d.rationale) || "未填写补充裁决理由"}</p></div>)}
        {!ecr.approval_decision_id && <p>尚无原 ECR 的正式裁决。</p>}
        {facts.supplier_notices != null && <p>已关联 {text(obj(facts.supplier_notices).source_count)} 条通告 · {obj(facts.supplier_notices).ready===true ? "当前通告依据就绪" : "通告依据待核对"} · {obj(facts.supplier_notices).matches_submitted===true ? "与已提交分析一致" : "需纳入或重新分析"}</p>}
        {ecr.source_finding_id != null && <a className="text-primary underline" href={`/ai-review?finding=${ecr.source_finding_id}`}>查看原建议和人工处理记录</a>}
      </section>
      {data.discussion_comparisons != null && <section className="space-y-2"><p className="font-medium">多专业讨论的人工对照</p><p>以下为最近 20 条具名历史记录；当前讨论与来源是否仍一致，请进入原讨论核对。人工建议须继续经过本变更的分析、批准及下方 ECN 生效流程。</p>{rows(data.discussion_comparisons).map(r => { const review = obj(r.body); return <div className="rounded-md border p-2" key={text(r.id)}><p>{text(r.question)} · {review.outcome === "validated" ? "当时核对通过" : "当时退回"} · {text(r.author_name)} · {date(r.created_at)}</p><p>人工结论：{text(review.manual_conclusion)}</p><p>对照：{text(review.comparison)}</p>{rows(review.alternatives).map((a, i) => <p key={i}>备选 {i + 1} · {text(a.title)}：{text(a.tradeoff)}</p>)}<p>建议：{text(review.recommendation)}</p></div>; })}{!rows(data.discussion_comparisons).length && <p>尚无具名人工对照记录。</p>}<Button type="button" size="sm" variant="outline" onClick={() => window.dispatchEvent(new CustomEvent("pdos-open-change-discussion", { detail: { ecrId } }))}>打开原讨论与核对入口</Button></section>}
      <section className="space-y-2"><p className="font-medium">待明确与当前变化</p>
        {values(data.unresolved).map((v, i) => <p key={i}>{v}</p>)}
        {rows(data.unknown_items).map(i => <p key={text(i.key)}>{scopeKinds[text(i.kind)]} · {sourceLabel(obj(i.snapshot))}：{text(i.basis)}；待办：{text(i.next_action)}</p>)}
        {rows(data.unknown_assessments).map(i => <p key={`${i.source}:${i.axis}`}>{i.source === "id_design" ? "ID 来源分析" : i.source === "supplier_notices" ? "厂商通告分析" : "专业来源分析"} · {impactAxes[text(i.axis)] ?? text(i.axis)}：{text(i.basis)}；{text(i.next_action)}</p>)}
        {rows(execution.source_changes).map((i, index) => <p key={index}>{scopeKinds[text(i.kind)]} · {sourceLabel(obj(i.before))}：{i.blocking ? "原执行依据已变化，须重核" : "执行进展已更新"}</p>)}
        {!values(data.unresolved).length && !rows(data.unknown_items).length && !rows(data.unknown_assessments).length && !rows(execution.source_changes).length && <p>本次读取未发现上述记录中的未决项；不代表所有专业资料已齐全。</p>}
      </section>
      <section className="space-y-2"><p className="font-medium">分析意见与处理建议{data.analysis_status === "approved" ? "（已随原 ECR 批准）" : "（尚未获批）"}</p><p className="whitespace-pre-wrap">{text(data.analysis_summary) || "尚无保存的分析意见"}</p>
        {data.bound_scope != null && <><p>绑定范围 v{String(scope.revision_number)} · 覆盖：{text(snapshot.coverage)}</p><p>明确排除 / 待补：{text(snapshot.exclusions)}</p></>}
        {rows(data.assessments).map(i => <p key={`${i.source}:${i.axis}`}>{i.source === "id_design" ? "ID 来源分析" : i.source === "supplier_notices" ? "厂商通告分析" : "专业来源分析"} · {impactAxes[text(i.axis)] ?? text(i.axis)} · {outcomes[text(i.conclusion)]}：{text(i.basis)}；{text(i.next_action)}</p>)}
        {rows(snapshot.items).map(i => <p key={text(i.key)}>{scopeKinds[text(i.kind)]} · {sourceLabel(obj(i.snapshot))} · {outcomes[text(i.conclusion)]}：{actions[text(i.action)]}，{text(i.next_action)}</p>)}
      </section>
      <section className="space-y-2"><p className="font-medium">冻结依据与升级审批</p><QuietCreationHistory data={{ ...quiet, people: rows(data.people).map(p => ({ id: p.id, name: p.display_name })) }}/>
        {rows(quiet.required).map(r => { const w = obj(r.window); const receipt = rows(quiet.requests).find(v => v.policy_id === r.policy_id && v.window_key === w.key && v.current === true); return <div className="rounded-md border p-2" key={`${r.policy_id}:${w.key}`}><p>政策 v{String(r.policy_version)} · {text(w.key).toUpperCase()} · {date(w.starts_at)} 至 {date(w.ends_at)}</p><p>{text(w.planning_basis)}</p><p>本版例外：{receipt ? receipt.status === "approved" ? "具名升级审批通过" : receipt.status === "rejected" ? "已退回" : "待逐环审批" : "尚未登记"}</p>{receipt && <><p>{text(obj(receipt.body).reason)}；{text(obj(receipt.body).risk_and_controls)}</p>{rows(receipt.votes).map(v => <p key={text(v.id)}>第 {String(v.step)} 环 · {person(v.created_by_user_id)} · {outcomes[text(v.outcome)]} · {date(v.created_at)}：{text(obj(v.body).note)}</p>)}</>}<p className="text-muted-foreground">以下是读取时的来源核对，历史裁决以原记录为准：</p><QuietAnchorValue source={r.source}/></div>; })}
      </section>
      <section className="space-y-2"><p className="font-medium">ECN 与实际执行回链</p>
        {!rows(facts.ecns).length && <p>尚无关联 ECN；批准 ECR 不等于已经开立 ECN 或完成生效。</p>}
        {rows(facts.ecns).map(n => { const decision = rows(facts.decisions).find(d => d.id === n.effectivity_decision_id); return <div key={text(n.id)} className="rounded-md border p-2"><a className="text-primary underline" href={`#ecn-${n.id}`}>{text(n.code)} · {text(n.title)}</a><p>{ecnStatus[text(n.status)] ?? "状态待核对"} · 开立人 {person(n.created_by_user_id)} · {date(n.created_at)}</p>{decision ? <p>实际生效裁决：{outcomes[text(decision.outcome)] ?? text(decision.outcome)} · {person(decision.decided_by_user_id)} · {date(decision.decided_at)}；{text(decision.rationale)}</p> : <p>尚无生效裁决。</p>}</div>; })}
        <p>获批范围要求执行 {String(execution.required_count ?? 0)} 项。{Object.entries(obj(execution.counts)).map(([k, v]) => `${executionStatus[k] ?? k} ${v}`).join("；")}</p>
        <p>{execution.all_required_verified === true ? "当前已纳入的必需范围均有独立确认；ECN 生效及 ERP 交接仍按各自实际记录办理。" : "当前尚不能确认全部必需范围均已执行并独立确认。"}</p>
        <Button type="button" size="sm" variant="outline" onClick={openExecution}>打开原执行任务、证据与确认</Button>
      </section>
    </div>}
  </details>;
}
