"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Snapshot = { title: string; description: string; status: string; severity: string; updated_at: string | null; withdrawn_at: string | null };
type Review = { id: string; issue_digest: string; verdict: "accepted" | "needs_correction"; reason: string; actor_name: string; created_at: string; issue_snapshot: Snapshot };
type Data = { application_id: string | null; can_review: boolean; expected_digest: string | null; history: Review[]; next_before_id: string | null; notice: string };
type Command = { request_id: string; expected_digest: string; verdict: Review["verdict"]; reason: string };
type Props = { projectId: string; runId: string; applicationId: string; issueId: string; disabled?: boolean };
const statuses: Record<string, string> = { open: "待分析", analyzing: "分析中", solving: "解决中", verifying: "验证中", closed: "已关闭" };
const severities: Record<string, string> = { low: "低", medium: "中", high: "高", critical: "严重" };
function record(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("抽检回执不完整，请沿原请求核对"); return value; }
function text(value: unknown): string { if (typeof value !== "string") throw new Error("抽检回执不完整，请沿原请求核对"); return value; }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("抽检回执时间不完整"); return result; }
function review(value: unknown): Review {
  const row = record(value), snapshot = record(row.issue_snapshot);
  if (!["accepted", "needs_correction"].includes(String(row.verdict))) throw new Error("抽检意见不完整，请沿原请求核对");
  return { id: text(row.id), issue_digest: text(row.issue_digest), verdict: row.verdict as Review["verdict"], reason: text(row.reason), actor_name: text(row.actor_name), created_at: stamp(row.created_at), issue_snapshot: { title: text(snapshot.title), description: text(snapshot.description), status: text(snapshot.status), severity: text(snapshot.severity), updated_at: snapshot.updated_at == null ? null : stamp(snapshot.updated_at), withdrawn_at: snapshot.withdrawn_at == null ? null : stamp(snapshot.withdrawn_at) } };
}
function parse(value: unknown, applicationId: string): Data {
  const row = record(value);
  if ((row.application_id !== null && row.application_id !== applicationId) || typeof row.can_review !== "boolean" || !Array.isArray(row.history) || (row.expected_digest !== null && (typeof row.expected_digest !== "string" || !/^[0-9a-f]{64}$/i.test(row.expected_digest))) || (row.can_review && (row.application_id !== applicationId || row.expected_digest === null))) throw new Error("抽检条件与原办理记录不匹配，请刷新核对");
  return { application_id: row.application_id as string | null, can_review: row.can_review, expected_digest: row.expected_digest as string | null, history: row.history.map(review), next_before_id: row.next_before_id === null ? null : text(row.next_before_id), notice: text(row.notice) };
}
class RequestError extends Error { constructor(message: string, readonly status: number, readonly code: string | null) { super(message); } }
async function request(path: string, command?: Command): Promise<unknown> {
  const response = await fetch(path, { method: command ? "POST" : "GET", cache: "no-store", headers: command ? { "Content-Type": "application/json" } : undefined, body: command ? JSON.stringify(command) : undefined });
  const body: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new RequestError(isRecord(body) && typeof body.detail === "string" ? body.detail : isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "抽检记录暂不可用，请沿原请求核对", response.status, isRecord(body) && isRecord(body.detail) && typeof body.detail.code === "string" ? body.detail.code : null);
  return body;
}
function time(value: string) { return new Date(value).toLocaleString("zh-CN"); }
function ReviewItem({ item }: { item: Review }) {
  return <div className="space-y-1.5"><p className="font-medium">{item.verdict === "accepted" ? "认可" : "需要修正"} · {item.actor_name}</p><p className="whitespace-pre-wrap break-words leading-5">{item.reason}</p><time className="text-muted-foreground" dateTime={item.created_at}>{time(item.created_at)}</time><details className="pt-1"><summary className="cursor-pointer text-primary">查看抽检时的问题原件</summary><div className="mt-2 space-y-2 border-l-2 pl-3"><p className="break-words font-medium">{item.issue_snapshot.title}</p><p className="whitespace-pre-wrap break-words leading-5">{item.issue_snapshot.description}</p><p>当时状态：{statuses[item.issue_snapshot.status] ?? "状态待核对"} · 严重度：{severities[item.issue_snapshot.severity] ?? "未记录"}</p>{item.issue_snapshot.updated_at && <p className="text-muted-foreground">原问题更新时间：{time(item.issue_snapshot.updated_at)}</p>}{item.issue_snapshot.withdrawn_at && <p className="text-primary">原问题已撤回，保留抽检原件。</p>}</div></details></div>;
}
export function AiIssueSampleReview(props: Props) { return <SampleReview key={`${props.projectId}:${props.runId}:${props.applicationId}`} {...props} />; }
function SampleReview({ projectId, runId, applicationId, issueId, disabled = false }: Props) {
  const [data, setData] = useState<Data | null>(null), [reason, setReason] = useState(""), [pending, setPending] = useState<Command | null>(null), [receipt, setReceipt] = useState<Review | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const active = useRef(true), locked = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const base = `/api/projects/${encodeURIComponent(projectId)}/ai-issue-applications/${encodeURIComponent(runId)}/sample-review`;
  async function load(older = false) {
    if (locked.current || disabled || pending) return; locked.current = true; setBusy(true); setError(null);
    try { const value = parse(await request(`${base}${older && data?.next_before_id ? `?before_id=${encodeURIComponent(data.next_before_id)}` : ""}`), applicationId); if (active.current) setData(current => older && current ? { ...value, history: [...current.history, ...value.history.filter(item => !current.history.some(old => old.id === item.id))] } : value); }
    catch (error) { if (active.current) { setError(error instanceof Error ? error.message : "抽检记录读取失败"); if (error instanceof RequestError && [401, 403].includes(error.status)) { setData(null); setReceipt(null); } } }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function save(command: Command) {
    if (locked.current || disabled) return; locked.current = true; setBusy(true); setPending(command); setError(null);
    try {
      const body = record(await request(base, command)), value = parse(body, applicationId), acknowledgement = review(body.review_receipt);
      if (typeof body.replayed !== "boolean" || value.application_id !== applicationId || acknowledgement.verdict !== command.verdict || acknowledgement.reason !== command.reason || acknowledgement.issue_digest !== command.expected_digest) throw new Error("抽检原请求回执尚未核对完整，请沿原请求重试");
      if (active.current) { setData(value); setReceipt(acknowledgement); setPending(null); setReason(""); }
    } catch (error) {
      if (active.current) { setError(error instanceof Error ? error.message : "抽检结果尚未明确，请沿原请求核对"); if (error instanceof RequestError && error.status >= 400 && error.status < 500 && !error.code?.endsWith("_RETRY")) { setPending(null); setData(null); } }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  const blocked = disabled || busy || !!pending;
  return <details className="space-y-2 border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !data && !busy && !pending) void load(); }}><summary className="cursor-pointer font-medium text-primary">具名抽检与历史</summary><div className="space-y-3"><p className="leading-5 text-muted-foreground">此记录已被选入抽检。意见与当时的问题原件一起保留；保存抽检意见不改变问题状态。需要修正时在原问题继续办理。</p><p className="leading-5 text-muted-foreground">复用已有问题时，抽检核对复用判断，原问题创建署名保持。</p><Button size="sm" variant="outline" disabled={blocked} onClick={() => void load()}>刷新抽检条件与历史</Button>{busy && <p role="status">正在核对抽检记录…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}{data && <p className="leading-5 text-muted-foreground">{data.notice}</p>}{data?.can_review && data.expected_digest && <div className="space-y-2"><label className="block space-y-1"><span>抽检说明（必填，保存时记录你的姓名）</span><textarea className="min-h-20 w-full rounded-lg border bg-background px-3 py-2" maxLength={1000} value={reason} disabled={blocked} onChange={event => setReason(event.target.value)} /></label><div className="flex flex-wrap gap-2">{(["accepted", "needs_correction"] as const).map(verdict => <Button key={verdict} size="sm" variant={verdict === "accepted" ? "default" : "outline"} disabled={blocked || !reason.trim()} onClick={() => void save({ request_id: crypto.randomUUID(), expected_digest: data.expected_digest!, verdict, reason: reason.trim() })}>{verdict === "accepted" ? "认可抽检结果" : "记录需要修正"}</Button>)}</div></div>}{pending && !busy && <div className="space-y-2"><p className="text-primary">抽检结果尚未明确，原意见和请求已保留，核对不会另存一条。</p><Button size="sm" disabled={disabled} onClick={() => void save(pending)}>沿原请求核对抽检结果</Button></div>}{receipt && <section aria-label="本次抽检请求回执" className="space-y-2 border-t pt-3"><p className="font-medium">本次抽检请求回执</p><ReviewItem item={receipt} /></section>}{data && <><a className="inline-block text-primary underline underline-offset-2" href={`/projects?project=${encodeURIComponent(projectId)}&tab=work-items&entity_id=${encodeURIComponent(issueId)}`}>{data.history[0]?.verdict === "needs_correction" ? "前往原问题修正" : "查看原问题"}</a><section aria-label="具名抽检历史" className="space-y-2 border-t pt-3"><p className="font-medium">具名抽检历史</p>{data.history.length === 0 && <p className="text-muted-foreground">尚无具名抽检意见。</p>}<ol className="space-y-3">{data.history.map(item => <li key={item.id} className="border-l-2 pl-3"><ReviewItem item={item} /></li>)}</ol>{data.next_before_id && <Button size="sm" variant="outline" disabled={blocked} onClick={() => void load(true)}>更早的抽检意见</Button>}</section></>}</div></details>;
}
