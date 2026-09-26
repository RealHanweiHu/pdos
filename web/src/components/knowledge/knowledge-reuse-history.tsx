"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const row = (value: unknown): Row => isRecord(value) ? value : {};
const text = (value: unknown) => value == null ? "" : String(value);
const states: Record<string, string> = { pending: "等待准备", running: "正在处理", ready: "推荐已准备", empty: "未找到匹配", stale: "原输入或权限已变化", failed: "后续处理失败", uncertain: "未取得完整调用回执" };
type Request = { request_id: string; expected_digest: string; reason: string };
class RequestError extends Error { constructor(message: string, public status: number) { super(message); } }
export function KnowledgeReuseHistory({ projectId, job, onResumed }: { projectId: string; job: Row; onResumed: () => void }) {
  const [entries, setEntries] = useState<Row[] | null>(null), [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [reason, setReason] = useState(""), [pending, setPending] = useState<Request | null>(null), [receipt, setReceipt] = useState<Row | null>(null);
  const base = `/api/projects/${encodeURIComponent(projectId)}/knowledge-prepared/${encodeURIComponent(text(job.id))}`;
  async function request(url: string, body?: Request): Promise<Row> {
    const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    const value = await responseBody(response);
    if (!response.ok) throw new RequestError(text(row(row(value).detail).message) || "未取得办理回执，请回查原请求", response.status);
    if (!isRecord(value)) throw new Error("准备记录不完整，请重新读取");
    return value;
  }
  async function load(before?: number) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const value = await request(`${base}/history${before ? `?before_id=${before}` : ""}`);
      if (!Array.isArray(value.items) || !value.items.every(isRecord) || !(value.next_before_id === null || typeof value.next_before_id === "number")) throw new Error("历史分页格式不完整");
      setEntries(old => before ? [...(old ?? []), ...value.items as Row[]] : value.items as Row[]); setNext(value.next_before_id);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function resume(body: Request, lookup = false) {
    setPending(body); setBusy(true); setError("");
    try {
      const value = await request(`${base}/resume${lookup ? `?request_id=${body.request_id}` : ""}`, lookup ? undefined : body);
      if (value.request_id !== body.request_id || !isRecord(value.receipt)) throw new Error("恢复回执不完整，请保留原请求回查");
      setReceipt(value); setPending(null); onResumed(); setEntries(null);
    } catch (e) {
      if (!lookup && e instanceof RequestError && [400, 401, 403, 409, 422].includes(e.status)) { setPending(null); onResumed(); }
      setError(e instanceof Error ? e.message : "恢复结果暂不确定");
    } finally { setBusy(false); }
  }
  const origin = row(job.origin), basis = row(job.basis);
  return <details className="rounded-lg border p-3 text-xs" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !entries && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">触发来源、准备记录与失败恢复</summary>
    <div className="mt-3 space-y-3">
      <p>原业务办理人：{text(origin.actor_name) || "系统"} · {text(origin.timestamp) || text(job.created_at)}</p>
      <p>当前：{states[text(job.state)] ?? text(job.state)}；{basis.has_embedding_receipt === true ? "成功检索回执已保留" : "尚无完整检索回执"}</p>
      {job.can_resume === true && !pending ? <form className="space-y-2" onSubmit={e => { e.preventDefault(); void resume({ request_id: crypto.randomUUID(), expected_digest: text(job.resume_digest), reason: reason.trim() }); }}>
        <p>继续使用已保存的成功回执完成推荐整理，不重新调用模型。原失败记录保留。</p>
        <label className="block">恢复说明<textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={reason} onChange={e => setReason(e.target.value)} required maxLength={4000} disabled={busy}/></label>
        <Button type="submit" size="sm" disabled={busy || !reason.trim() || !/^[a-f0-9]{64}$/.test(text(job.resume_digest))}>复用成功回执，继续准备</Button>
      </form> : null}
      {pending ? <div className="space-y-2"><p className="break-all">待核对请求：{pending.request_id}。请先回查或按原内容重试。</p><div className="flex flex-wrap gap-2"><Button type="button" size="sm" disabled={busy} variant="outline" onClick={() => void resume(pending, true)}>回查原请求</Button><Button type="button" size="sm" disabled={busy} variant="outline" onClick={() => void resume(pending)}>按原请求重试</Button></div></div> : null}
      {receipt ? <p role="status">恢复请求已留档，等待继续处理。{job.enabled === false ? "自动准备尚未启用。" : "可刷新准备状态查看后续结果。"}</p> : null}
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void load()}>刷新准备记录</Button>
      {entries?.length === 0 ? <p>当前没有后续处理记录；原业务触发信息保留在上方。</p> : null}
      <ol className="space-y-2">{entries?.map(entry => { const after = row(entry.after_snapshot); return <li className="rounded-md border p-2" key={text(entry.id)}><p>{text(entry.timestamp)} · {text(entry.actor_name) || "系统"} · {states[text(after.state)] ?? text(after.state)}</p><p>{after.has_embedding_receipt === true ? "已保留成功检索回执" : "没有完整检索回执"} · 推荐 {text(after.result_count)} 条</p>{entry.action === "knowledge.reuse.resume" ? <p>具名恢复说明：{text(row(entry.context).reason)}</p> : null}</li>; })}</ol>
      {next !== null ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(next)}>更早的准备记录</Button> : null}
    </div>
  </details>;
}
