"use client";

import { ProjectExecutionRenewal } from "./project-execution-renewal";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { EvidenceView, PlanSnapshot, type Snapshot } from "@/components/cases/plan-reviews";
import { projectStatusLabels } from "./project-list";
import { InitialPlanApplicationPanel } from "./initial-plan-application";
import type { Project } from "./project-types";

type Policy = { id: string; version: number; approver_user_id: string; four_eyes: boolean; authority_basis: string; created_at: string };
type Execution = { plan_review_id: string; applied: boolean; id: string; round_no: number; state: string; policy_id: string; created_by_user_id: string; created_at: string; payload_digest: string; request_reason: string; outcome_reason: string | null; approval: { approved_at: string; approved_by_user_id: string } | null; snapshot: { policy_renewal?: { previous_execution_id: string; previous_round_no: number; previous_policy: Policy; original_requester_ids: string[]; actor_name: string; reason: string }; policy: Policy; blockers: string[]; origin: unknown; case_basis: unknown; case_reviews: unknown; conversion: unknown; plan_snapshot: Snapshot } };
type State = { latest_execution_id: string | null; project_status: Project["status"]; policy: Policy | null; policy_history: Policy[]; people: { id: string; display_name: string }[]; plan_reviews: { id: string; title: string; candidate_version: number; round_no: number }[]; items: Execution[]; has_more: boolean; history: { id: string; execution_request_id: string; actor_user_id: string; reason: string; created_at: string; snapshot: Execution }[]; current_user_id: string; can_configure: boolean; can_request: boolean; application_available: boolean };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const states: Record<string, string> = { pending_approval: "待执行批准", approved: "已批准，待独立应用", rejected: "已退回", withdrawn: "已撤回" };

export function ProjectExecutionPanel({ projectId, targetId }: { projectId: string; targetId?: string }) {
  const [renewedId,setRenewedId]=useState("");
  const [renewalLocked,setRenewalLocked]=useState(false);
  const [open, setOpen] = useState(!!targetId); const [data, setData] = useState<State | null>(null); const [busy, setBusy] = useState(!!targetId); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const [approver, setApprover] = useState(""); const [fourEyes, setFourEyes] = useState(""); const [authority, setAuthority] = useState(""); const [plan, setPlan] = useState(""); const [reason, setReason] = useState("");
  const [decisions, setDecisions] = useState<Record<string, string>>({}); const [read, setRead] = useState<Record<string, boolean>>({});
  const ids = useRef(new Map<string, string>()); const path = `projects/${projectId}/execution`;
  const readPath = `${path}${targetId ? `?target_id=${targetId}` : ""}`;
  useEffect(() => { if (!targetId) return; let active=true; void caseLinkRequest<State>(readPath).then(value=>{if(active)setData(value);},e=>{if(active)setError(e instanceof Error ? e.message : "原申请读取失败");}).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};},[readPath,targetId]);
  async function load() { setData(await caseLinkRequest<State>(readPath)); }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "执行申请暂不可用"); } finally { setBusy(false); } }
  async function send(endpoint: string, body: object) { setBusy(true); setError(null); setNotice(null); const key = JSON.stringify({ endpoint, body }); let id = ids.current.get(key); if (!id) { id = crypto.randomUUID(); ids.current.set(key, id); } try { await caseLinkRequest(endpoint, { ...body, request_id: id }); await load(); setRead({}); setNotice("执行记录已保存。"); } catch (failure) { setError(failure instanceof Error ? failure.message : "执行申请未完成"); } finally { setBusy(false); } }
  const person = (id: string) => data?.people.find((item) => item.id === id)?.display_name ?? `原参与人（${id.slice(0, 8)}）`;
  return <section className="space-y-3 rounded-lg border bg-card p-4">
    <div className="flex items-center justify-between gap-2"><h3 className="font-semibold">项目执行申请</h3><Button type="button" size="sm" variant="outline" disabled={busy || renewalLocked} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起" : "办理与历史"}</Button></div>
    {open && <div className="space-y-4">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      {renewedId && <a className="block text-sm text-primary underline" href={`/projects?project=${projectId}&tab=overview&approval_request_kind=execution&approval_request_id=${renewedId}`}>打开新申请，核对后独立批准与应用</a>}
      <p className="text-xs text-muted-foreground">执行申请绑定实际案例转换、已接受计划和具名批准政策。批准后独立应用任务与基线。</p>
      {targetId && data && !data.items.some(item=>item.id===targetId) && <p role="alert" className="text-sm">指定申请不可访问，请核对项目与来源。</p>}
      {data && <p className="text-sm">当前项目状态：{projectStatusLabels[data.project_status]}</p>}
      {data?.project_status === "draft" && <p className="text-sm">项目仍是草稿，请由有权成员先在<a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview`}>概览提交项目</a>，再回来刷新并批准执行。</p>}
      {data?.policy && <div className="space-y-1 rounded-md border p-3 text-xs"><p>执行政策 v{data.policy.version} · 批准人：{person(data.policy.approver_user_id)} · {data.policy.four_eyes ? "申请人与批准人分离" : "允许同一人申请并批准"}</p><p className="whitespace-pre-wrap">授权依据：{data.policy.authority_basis}</p></div>}
      {data?.can_configure && <details><summary className="cursor-pointer text-sm">配置执行批准政策</summary><form className="mt-3 space-y-2" onSubmit={(event) => { event.preventDefault(); void send(`${path}/policies`, { expected_version: data.policy?.version ?? 0, approver_user_id: approver, four_eyes: fourEyes === "yes", authority_basis: authority }); }}>
        <label className="block text-sm">具名执行批准人<select className={field} required value={approver} onChange={(event) => setApprover(event.target.value)}><option value="">选择实际项目参与人</option>{data.people.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>
        <label className="block text-sm">申请与批准分工<select className={field} required value={fourEyes} onChange={(event) => setFourEyes(event.target.value)}><option value="">明确选择本项目政策</option><option value="yes">申请人与批准人必须不同</option><option value="no">允许同一人申请并批准</option></select></label>
        <label className="block text-sm">组织授权依据<textarea className={field} required maxLength={2048} value={authority} onChange={(event) => setAuthority(event.target.value)} /></label><Button type="submit" size="sm" disabled={busy || renewalLocked || !approver || !fourEyes || !authority.trim()}>发布政策 v{(data.policy?.version ?? 0) + 1}</Button>
      </form></details>}
      {!targetId && data?.can_request && <form className="space-y-2 rounded-md border p-3" onSubmit={(event) => { event.preventDefault(); void send(`${path}/requests`, { plan_review_id: plan, reason }); }}>
        <label className="block text-sm">已接受的实际来源计划<select className={field} required value={plan} onChange={(event) => setPlan(event.target.value)}><option value="">选择计划与审阅轮次</option>{data.plan_reviews.map((item) => <option key={item.id} value={item.id}>{item.title} v{item.candidate_version} · 第 {item.round_no} 轮</option>)}</select></label>
        {!data.plan_reviews.length && <p className="text-xs">暂无与本项目实际来源链匹配的已接受计划，请先在对应案例、定义或机会中办理计划审阅。</p>}
        <label className="block text-sm">执行申请说明<textarea className={field} required maxLength={2048} value={reason} onChange={(event) => setReason(event.target.value)} /></label><Button type="submit" size="sm" disabled={busy || renewalLocked || !data.policy || !plan || !reason.trim()}>固定依据并申请执行</Button>
      </form>}
      {data?.items.filter(item => !targetId || item.id === targetId).map((item) => { const isLatest = item.id === data.latest_execution_id; const policy = item.snapshot.policy; const appointed = policy.approver_user_id === data.current_user_id; const canWithdraw = [policy.approver_user_id, item.created_by_user_id].includes(data.current_user_id) && !item.applied && ["pending_approval", "approved"].includes(item.state); const current = isLatest && data.policy?.id === item.policy_id; return <article key={item.id} className="space-y-3 rounded-md border p-3">
        <p className="text-sm font-medium">第 {item.round_no} 轮 · {item.applied ? "已批准并应用" : states[item.state]}{!current ? " · 历史依据" : ""}</p><p className="text-xs">申请人：{person(item.created_by_user_id)} · 批准人：{person(policy.approver_user_id)} · 政策 v{policy.version}</p><p className="whitespace-pre-wrap text-xs">{item.request_reason}</p>
        <PlanSnapshot value={item.snapshot.plan_snapshot} />
        {item.snapshot.policy_renewal && <p className="whitespace-pre-wrap text-xs">按新政策续提：原第 {item.snapshot.policy_renewal.previous_round_no} 轮、政策 v{item.snapshot.policy_renewal.previous_policy.version}，原批准人 {person(item.snapshot.policy_renewal.previous_policy.approver_user_id)}；办理人 {item.snapshot.policy_renewal.actor_name}；原因：{item.snapshot.policy_renewal.reason}</p>}
        {isLatest && item.state === "pending_approval" && !item.applied && data.can_request && data.policy && data.policy.id !== item.policy_id && <ProjectExecutionRenewal projectId={projectId} original={item} policy={data.policy} approverName={person(data.policy.approver_user_id)} disabled={busy} onLockChange={setRenewalLocked} onChanged={async replacementId=>{setRenewedId(replacementId);await load();setRead({});setNotice("已按当前政策续提，等待新一轮具名批准。");}}/>}
        <details><summary className="cursor-pointer text-xs">实际来源、转换及立项评审</summary><div className="space-y-3 text-xs"><EvidenceView value={{ origin: item.snapshot.origin, conversion: item.snapshot.conversion, case_basis: item.snapshot.case_basis, case_reviews: item.snapshot.case_reviews }} /></div></details>
        {!!item.snapshot.blockers.length && <ul className="list-disc pl-4 text-xs text-destructive">{item.snapshot.blockers.map((blocker, position) => <li key={position}>{blocker}</li>)}</ul>}
        {item.outcome_reason && <p className="text-xs">办理意见：{item.outcome_reason}</p>}{item.approval && <p className="text-xs">执行批准：{person(item.approval.approved_by_user_id)} · {new Date(item.approval.approved_at).toLocaleString()}</p>}
        {(canWithdraw || (appointed && current && item.state === "pending_approval")) && <>
          <label className="block text-sm">办理意见<textarea className={field} maxLength={2048} value={decisions[item.id] ?? ""} onChange={(event) => setDecisions({ ...decisions, [item.id]: event.target.value })} /></label>
          {appointed && current && item.state === "pending_approval" && <label className="flex gap-2 text-sm"><input type="checkbox" checked={read[item.id] ?? false} onChange={(event) => setRead({ ...read, [item.id]: event.target.checked })} />已阅读本轮计划及实际来源，按本项目授权办理执行批准</label>}
          <div className="flex flex-wrap gap-2">{appointed && current && item.state === "pending_approval" && <>
            <Button type="button" size="sm" disabled={busy || renewalLocked || !["proposed", "approved", "active", "on_hold"].includes(data.project_status) || !read[item.id] || !decisions[item.id]?.trim() || !!item.snapshot.blockers.length || (policy.four_eyes && [item.created_by_user_id, ...(item.snapshot.policy_renewal?.original_requester_ids ?? [])].includes(data.current_user_id))} onClick={() => void send(`${path}/requests/${item.id}`, { action: "approve", expected_digest: item.payload_digest, reason: decisions[item.id] })}>批准项目执行</Button>
            <Button type="button" size="sm" variant="outline" disabled={busy || renewalLocked || !decisions[item.id]?.trim()} onClick={() => void send(`${path}/requests/${item.id}`, { action: "reject", expected_digest: item.payload_digest, reason: decisions[item.id] })}>退回</Button>
          </>}{canWithdraw && <Button type="button" size="sm" variant="ghost" disabled={busy || renewalLocked || !decisions[item.id]?.trim()} onClick={() => void send(`${path}/requests/${item.id}`, { action: "withdraw", expected_digest: item.payload_digest, reason: decisions[item.id] })}>撤回申请</Button>}</div>
        </>}
        <details><summary className="cursor-pointer text-xs">办理记录</summary>{data.history.filter((entry) => entry.execution_request_id === item.id).map((entry) => <p key={entry.id} className="my-2 text-xs">{new Date(entry.created_at).toLocaleString()} · {person(entry.actor_user_id)} · {states[entry.snapshot.state]} · {entry.reason}</p>)}</details>
      </article>; })}
      {data?.application_available && <InitialPlanApplicationPanel projectId={projectId} requests={data.items} person={person} onApplied={load} />}
      {!targetId && data?.has_more && <p className="text-xs">显示最近 50 轮执行申请。</p>}
      {!!data?.policy_history.length && <details><summary className="cursor-pointer text-xs">执行授权历史</summary>{data.policy_history.map((policy) => <p key={policy.id} className="my-2 whitespace-pre-wrap text-xs">v{policy.version} · {person(policy.approver_user_id)} · {policy.four_eyes ? "申请与批准分离" : "允许同人申请批准"} · {policy.authority_basis}</p>)}</details>}
      <Button type="button" size="sm" variant="ghost" disabled={busy || renewalLocked} onClick={() => void refresh()}>刷新执行申请</Button>
    </div>}
  </section>;
}
