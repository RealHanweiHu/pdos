"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Scope = { revision: number; enabled: boolean; principal_id: string | null };
type Data = { scope: Scope; can_manage_scope: boolean; notice: string };
type Command = { request_id: string; expected_revision: number; enabled: boolean; reason: string };
function revision(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("项目授权版本不完整，请重新核对"); return value; }
function parse(value: unknown): Data {
  if (!isRecord(value) || !isRecord(value.scope) || typeof value.scope.enabled !== "boolean" || typeof value.can_manage_scope !== "boolean" || typeof value.notice !== "string" || (value.scope.principal_id !== null && typeof value.scope.principal_id !== "string")) throw new Error("项目授权资料不完整，请重新核对");
  return { scope: { revision: revision(value.scope.revision), enabled: value.scope.enabled, principal_id: value.scope.principal_id }, can_manage_scope: value.can_manage_scope, notice: value.notice };
}
class RequestFailure extends Error { constructor(message: string, readonly status: number, readonly code: string | null) { super(message); } }
async function request(path: string, command?: Command): Promise<unknown> {
  const response = await fetch(path, { method: command ? "POST" : "GET", cache: "no-store", headers: command ? { "Content-Type": "application/json" } : undefined, body: command ? JSON.stringify(command) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new RequestFailure(isRecord(value) && typeof value.detail === "string" ? value.detail : isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "项目授权暂不可用，请核对原请求", response.status, isRecord(value) && isRecord(value.detail) && typeof value.detail.code === "string" ? value.detail.code : null);
  return value;
}
export function AiIssueScope({ projectId }: { projectId: string }) { return <ScopeControl key={projectId} projectId={projectId} />; }
function ScopeControl({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Data | null>(null), [reason, setReason] = useState(""), [pending, setPending] = useState<Command | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const active = useRef(true), locked = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const path = `/api/projects/${encodeURIComponent(projectId)}/ai-issue-applications/scope`;
  async function load() {
    if (locked.current) return; locked.current = true; setBusy(true); setError(null);
    try { const value = parse(await request(path)); if (active.current) setData(value); }
    catch (error) { if (active.current) { setError(error instanceof Error ? error.message : "项目授权读取失败"); setData(null); } }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function save(command: Command) {
    if (locked.current) return; locked.current = true; setPending(command); setBusy(true); setError(null); setNotice(null);
    try {
      const result = await request(path, command);
      if (!isRecord(result) || revision(result.revision) <= command.expected_revision || typeof result.reused !== "boolean") throw new Error("项目授权回执不完整，请沿原请求核对");
      if (active.current) { setPending(null); setReason(""); setData(null); setNotice("原授权请求已记录；下方按当前授权状态显示。范围授权不启用自动建单。"); }
      const current = parse(await request(path));
      if (active.current) setData(current);
    } catch (error) {
      if (active.current) { setError(error instanceof Error ? error.message : "尚未取得明确授权回执，请沿原请求核对"); if (error instanceof RequestFailure && error.status >= 400 && error.status < 500 && !error.code?.endsWith("_RETRY")) { setPending(null); setData(null); } }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  return <details className="min-w-0 border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !data && !busy && !pending) void load(); }}><summary className="cursor-pointer text-sm font-medium text-primary">项目问题 AI 范围授权</summary><div className="mt-3 space-y-3 text-xs"><p className="leading-5 text-muted-foreground">具名登记本项目允许使用的 AI 问题范围。范围授权不启用自动建单；模型开放、试运行就绪与实际办理仍须分别核对。</p><Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void load()}>刷新项目授权</Button>{busy && <p role="status">正在核对项目授权…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status" className="text-muted-foreground">{notice}</p>}
    {data && <><p className="font-medium">{data.scope.enabled ? "已登记项目范围授权" : "项目范围尚未授权"} · 第 {data.scope.revision} 版</p><p className="leading-5 text-muted-foreground">{data.notice}</p>{data.can_manage_scope ? <div className="space-y-2"><label className="block space-y-1"><span>项目授权原因（必填，办理时记录你的姓名）</span><textarea className="min-h-20 w-full rounded-lg border bg-background px-3 py-2" value={reason} disabled={busy || !!pending} maxLength={2000} onChange={event => setReason(event.target.value)} /></label><Button size="sm" variant="outline" disabled={busy || !!pending || !reason.trim()} onClick={() => void save({ request_id: crypto.randomUUID(), expected_revision: data.scope.revision, enabled: !data.scope.enabled, reason: reason.trim() })}>{data.scope.enabled ? "停止本项目范围授权" : "登记本项目范围授权"}</Button></div> : <p className="text-muted-foreground">当前账号仅可查看项目授权，不能更改。</p>}</>}
    {pending && !busy && <div className="space-y-2"><p className="text-primary">授权结果尚未明确，沿原请求核对，不另起一次授权。</p><Button size="sm" onClick={() => void save(pending)}>沿原请求核对项目授权</Button></div>}
  </div></details>;
}
