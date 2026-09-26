"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";

type Request = { request_id: string; expected_digest: string; owner_user_id: string; reason: string; transfer_task: boolean };
async function read(url: string): Promise<Row> {
  const response = await fetch(url, { cache: "no-store" }), body = await responseBody(response);
  if (!response.ok || !isRecord(body) || !isRecord(body.decision) || typeof body.digest !== "string" || !Array.isArray(body.members) || !Array.isArray(body.history)) throw new Error(isRecord(body) && isRecord(body.detail) ? text(body.detail.message) : "决策责任记录暂不可用");
  return body;
}
export function DecisionResponsibilityLanding({ projectId }: { projectId: string }) {
  const id = useSearchParams().get("decision_owner_id");
  if (!id || !/^[0-9a-f-]{36}$/.test(id)) return null;
  return <div className="rounded-md border p-3"><h3 className="mb-2 font-medium">本次移交的决策跟进</h3><DecisionResponsibility key={`${projectId}:${id}`} projectId={projectId} decisionId={id} initiallyOpen/></div>;
}
export function DecisionResponsibility({ projectId, decisionId, initiallyOpen = false, disabled = false, onLock, onChanged }: { projectId: string; decisionId: string; initiallyOpen?: boolean; disabled?: boolean; onLock?: (value: boolean) => void; onChanged?: () => Promise<void> }) {
  const base = `/api/projects/${projectId}/decisions/${decisionId}/responsibility`;
  const [opened, setOpened] = useState(false), [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [owner, setOwner] = useState(""), [reason, setReason] = useState(""), [transfer, setTransfer] = useState(false), [receipt, setReceipt] = useState("");
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null);
  useEffect(() => { if (!initiallyOpen) return; let active = true; void read(base).then(v => { if (active) { setData(v); setOpened(true); } }, e => { if (active) setError(e instanceof Error ? e.message : "读取失败"); }); return () => { active = false; }; }, [base, initiallyOpen]);
  async function load(before?: number) { const v = await read(`${base}${before ? `?before_id=${before}` : ""}`); setData(old => before && old ? { ...old, history: [...rows(old.history), ...rows(v.history).filter(h => !rows(old.history).some(r => r.id === h.id))], next_before_id: v.next_before_id } : v); }
  async function refresh(before?: number) { setBusy(true); setError(""); try { await load(before); setOpened(true); } catch(e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }
  function clear() { setPreview(null); setOwner(""); setReason(""); setTransfer(false); onLock?.(false); }
  async function save(body: Request) {
    setPending(body); setBusy(true); setError(""); onLock?.(true);
    try {
      const response = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), v = await responseBody(response);
      if (!response.ok) { if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); } throw new Error(isRecord(v) && isRecord(v.detail) ? text(v.detail.message) : "结果待确认，请按原请求重试"); }
      if (!isRecord(v) || v.request_id !== body.request_id || typeof v.audit_id !== "number") throw new Error("回执不完整，请按原请求重试");
      setReceipt(`跟进责任已调整 · 回执 ${v.audit_id} · 原请求 ${body.request_id}`); setPending(null); clear(); await load(); await onChanged?.();
    } catch(e) { setError(e instanceof Error ? e.message : "调整失败"); } finally { setBusy(false); }
  }
  const decision = obj(data?.decision), task = obj(data?.task), people = obj(data?.people), locked = disabled || busy || !!preview || !!pending;
  const person = (id: unknown) => text(people[text(id)]) || "未指定 / 历史成员";
  return <section className="space-y-2 text-sm" aria-label="决策跟进责任"><Button type="button" size="sm" variant="outline" disabled={disabled || busy || !!pending} onClick={() => { if (opened) { setOpened(false); clear(); } else void refresh(); }}>{opened ? "收起责任办理" : "跟进负责人调整与历史"}</Button>{error && <p role="alert" className="text-destructive">{error}</p>}{receipt && <p role="status" className="break-all">{receipt}</p>}
    {opened && data && <div className="space-y-3 rounded-md border p-3"><p className="font-medium">{text(decision.title)}</p><p className="whitespace-pre-wrap">原批准结论：{text(decision.outcome)}</p><p>批准人：{person(decision.approver_user_id)} · 跟进负责人：{person(decision.owner_user_id)}</p><p className="whitespace-pre-wrap">目标动作：{text(decision.follow_up_note)}</p>
      {typeof task.id === "string" && <div className="rounded-md border p-2"><p>关联任务：{text(task.title)} · {person(task.assignee_user_id)} · {text(task.status)}{task.due_date ? ` · ${text(task.due_date)}` : ""}</p><Link className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${task.id}`}>打开原执行任务与接手资料</Link>{data.task_transferable !== true && <p className="text-xs text-muted-foreground">本任务的责任需在原专业或正式计划流程办理。</p>}</div>}
      {data.effective_follow_up_state !== "pending" && <p>当前决定无需跟进或已有有效执行凭据，保留原责任。</p>}
      <p className="text-xs text-muted-foreground">本次只调整跟进责任；原批准结论、签名与来源保留，跟进完成仍需有效的实际执行凭据。</p>
      <Button type="button" size="sm" variant="ghost" disabled={locked || !!owner || !!reason || transfer} onClick={() => void refresh()}>刷新原决定与执行任务</Button>
      {data.can_reassign === true && <fieldset disabled={locked} className="space-y-2"><label className="block">新跟进负责人<select className="mt-1 w-full rounded-md border bg-background p-2" value={owner} onChange={e => { setOwner(e.target.value); onLock?.(!!e.target.value || !!reason || transfer); }}><option value="">选择有效项目成员</option>{rows(data.members).filter(m => m.id !== decision.owner_user_id).map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.name)}</option>)}</select></label><label className="block">具名调整原因<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={2048} value={reason} onChange={e => { setReason(e.target.value); onLock?.(!!owner || !!e.target.value || transfer); }}/></label>{data.task_transferable === true && <label className="flex gap-2"><input type="checkbox" checked={transfer} onChange={e => { setTransfer(e.target.checked); onLock?.(!!owner || !!reason || e.target.checked); }}/>同时将关联普通任务交给此人，保留任务状态、期限及证据</label>}<Button type="button" size="sm" disabled={!owner || !reason.trim()} onClick={() => { setPreview({ request_id: crypto.randomUUID(), expected_digest: text(data.digest), owner_user_id: owner, reason: reason.trim(), transfer_task: transfer }); onLock?.(true); }}>预览移交</Button><Button type="button" size="sm" variant="ghost" onClick={clear}>清除输入</Button></fieldset>}
      {preview && !pending && <div className="space-y-2 rounded-md border p-2"><p>跟进负责人：{person(decision.owner_user_id)} → {text(rows(data.members).find(m => m.id === preview.owner_user_id)?.name)}</p><p>{preview.transfer_task ? `同时移交任务：${text(task.title)}。两项同时生效，任一步失败均保留原责任。` : "关联任务继续由原任务负责人办理。"}</p><p className="whitespace-pre-wrap">{preview.reason}</p><Button type="button" size="sm" disabled={busy || disabled} onClick={() => void save(preview)}>确认责任移交</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div>}
      {pending && <div><p className="break-all">原请求 {pending.request_id} 结果待确认。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void save(pending)}>按原请求重试</Button></div>}
      <details><summary className="cursor-pointer">历次责任移交</summary>{rows(data.history).map(h => { const c = obj(h.context), names = obj(c.people), before = obj(h.before_snapshot), after = obj(h.after_snapshot), original = obj(before.decision), next = obj(after.decision); return <article key={text(h.id)} className="mt-2 rounded-md border p-2"><p>{text(names[text(original.owner_user_id)]) || "未指定 / 历史成员"} → {text(names[text(next.owner_user_id)])}</p><p className="whitespace-pre-wrap">{text(c.reason)}</p><p>{c.transfer_task === true ? `同步移交任务：${text(obj(before.task).title)}` : "未同步转移任务责任"}</p><p className="text-xs text-muted-foreground">{text(h.created_at)} · 办理人 {text(names[text(h.actor_user_id)])}</p></article>; })}{!rows(data.history).length && <p>暂无责任调整记录。</p>}{typeof data.next_before_id === "number" && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void refresh(data.next_before_id as number)}>加载更早记录</Button>}</details>
    </div>}
  </section>;
}
