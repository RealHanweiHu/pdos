"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { requestFindings } from "@/components/ai/ai-api";
import type { AiFinding } from "@/components/ai/ai-types";
import { TestPlanProposalView } from "@/components/ai/test-plan-proposal";
import { Button } from "@/components/ui/button";
import { ProjectTestSources, type TestPlanSource } from "./project-test-sources";

type Props = { projectId: string; planId: string };
function storageKey(projectId: string, planId: string) { return `pdos:test-plan-run:${projectId}:${planId}`; }
function readPending(projectId: string, planId: string): string | null {
  try {
    const value = sessionStorage.getItem(storageKey(projectId, planId));
    return value && /^[0-9a-f-]{36}$/i.test(value) ? value : null;
  } catch { return null; }
}
export function ProjectTestConversation(props: Props) {
  return <TestPlanConversationSession key={`${props.projectId}:${props.planId}`} {...props} />;
}
function TestPlanConversationSession({ projectId, planId }: Props) {
  const [pendingRun, setPendingRun] = useState<string | null>(null);
  const [pollPaused, setPollPaused] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [finding, setFinding] = useState<AiFinding | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newConversation, setNewConversation] = useState(false);
  const [retryRequest, setRetryRequest] = useState<{ id: string; body: string } | null>(null);
  const [sources, setSources] = useState<TestPlanSource[]>([]);

  useEffect(() => {
    let active = true;
    // Restore browser-only state after hydration; the server and first client render agree.
    queueMicrotask(() => {
      const saved = readPending(projectId, planId);
      if (active && saved) { setPendingRun(saved); setOpen(true); }
    });
    return () => { active = false; };
  }, [projectId, planId]);
  const processing = busy || pendingRun !== null;
  function rememberRun(id: string | null) {
    setPendingRun(id);
    try {
      if (id) sessionStorage.setItem(storageKey(projectId, planId), id);
      else sessionStorage.removeItem(storageKey(projectId, planId));
    } catch { /* The active page still tracks the server operation. */ }
  }
  useEffect(() => {
    if (!pendingRun || pollPaused) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/npi/test-plans/${encodeURIComponent(planId)}/suggestion-requests/${encodeURIComponent(pendingRun!)}`, { cache: "no-store" });
        const result = await response.json();
        if (!active) return;
        if (!response.ok) {
          if (response.status === 403 || response.status === 404) rememberRun(null);
          throw new Error("暂时无法查询任务状态，请重试。");
        }
        if (["queued", "running"].includes(result.status)) {
          timer = setTimeout(() => void poll(), 2000); return;
        }
        if (["succeeded", "waiting_input"].includes(result.status) && result.finding_id) {
          const saved = await load(result.finding_id);
          if (!active) return;
          if (!saved) throw new Error("建议已保存，可前往 AI Review 查看。");
          rememberRun(null); setMessage(""); setNewConversation(false); setRetryRequest(null);
        } else if (result.status === "cancelled") {
          rememberRun(null);
          setError("任务已取消，已保存建议仍可查看。");
        } else {
          rememberRun(null);
          throw new Error("AI 暂不可用，本次未改变测试计划。已保存建议仍可查看和编辑。");
        }
      } catch (cause) {
        if (active) { setError(cause instanceof Error ? cause.message : "查询失败。"); setPollPaused(true); }
      }
    }
    timer = setTimeout(() => void poll(), 0);
    return () => { active = false; clearTimeout(timer); };
    // A run is scoped to this keyed project/plan session. load only writes local state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingRun, pollPaused, pollRevision, projectId, planId]);

  async function cancelPending() {
    if (!pendingRun) return;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/ai/runs/${encodeURIComponent(pendingRun)}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error("暂时无法取消，请重试。");
      setPollPaused(false); setPollRevision((n) => n + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "取消失败。"); }
    finally { setBusy(false); }
  }

  async function load(id?: string) {
    const items = (await requestFindings({ projectId })).filter((item) => item.finding_type === "test_plan_change" && item.proposed_payload.base_plan_id === planId);
    const latest = id ? items.find((item) => item.id === id) : items[0];
    setFinding(latest ?? null);
    setSources((latest?.proposed_payload.source_snapshots as TestPlanSource[] | undefined) ?? []);
    return latest;
  }
  async function start() {
    setOpen(true); setBusy(true); setError(null);
    try { await load(); } catch { setError("暂时无法读取已保存建议，请重试。"); }
    finally { setBusy(false); }
  }
  async function send() {
    if (!message.trim()) return;
    setBusy(true); setError(null);
    const previous = !newConversation && finding && ["pending_review", "accepted"].includes(finding.status) ? finding.id : null;
    const body = JSON.stringify({ message: message.trim(), previous_finding_id: previous, sources: sources.map(({kind, id, digest}) => ({kind, id, digest})) });
    const request = retryRequest?.body === body ? retryRequest : { id: crypto.randomUUID(), body };
    setRetryRequest(request);
    try {
      const response = await fetch(`/api/projects/${projectId}/npi/test-plans/${planId}/suggestions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...JSON.parse(body), request_id: request.id }),
      });
      const result = await response.json();
      if (!response.ok) { setRetryRequest(null); throw new Error(result.detail?.message ?? "生成失败，请重试。"); }
      if (response.status === 202 && typeof result.run_id === "string") {
        rememberRun(result.run_id); setPollPaused(false); setRetryRequest(null); return;
      }
      if (result.status !== "created" || !result.finding_id) {
        setRetryRequest(null);
        throw new Error("AI 暂不可用，本次未改变测试计划。已保存建议仍可查看和编辑。");
      }
      const saved = await load(result.finding_id);
      if (!saved) throw new Error("建议已保存，暂时无法读取；可前往 AI Review 查看。");
      setMessage(""); setNewConversation(false); setRetryRequest(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "请求失败。"); }
    finally { setBusy(false); }
  }
  if (!open) return <Button className="my-2" variant="outline" onClick={() => void start()}>用 AI 调整测试项</Button>;
  return <section aria-label="测试项对话" className="my-3 space-y-3 border-t py-3">
    <div className="flex items-center justify-between"><h3 className="font-medium">与 AI 调整测试项</h3><Button variant="ghost" disabled={processing} onClick={() => setOpen(false)}>收起</Button></div>
    <p className="text-xs text-muted-foreground">本轮使用当前模板、你输入的要求与选中的项目依据。方法和判据需要你审阅确认。</p>
    {finding ? <div>
      <TestPlanProposalView payload={finding.accepted_payload ?? finding.proposed_payload} />
      <Link className="inline-flex min-h-11 items-center text-sm font-medium text-primary" href={`/ai-review?finding=${finding.id}`}>前往 AI Review 审阅与应用</Link>
      <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={newConversation} onChange={(e) => { setNewConversation(e.target.checked); setRetryRequest(null); }} />重新开始，不沿用本轮对话</label>
    </div> : null}
    <ProjectTestSources projectId={projectId} planId={planId} selected={sources} disabled={processing} onChange={(values) => { setSources(values); setRetryRequest(null); }} />
    <label className="grid gap-2 text-sm">描述新增功能、客户要求或补充条件
      <textarea className="min-h-24 rounded-lg border bg-background p-3" maxLength={4000} value={message} disabled={processing} onChange={(e) => setMessage(e.target.value)} placeholder="例如：这个新品类增加了应急启动功能，请先列出需要补充哪些条件，再建议测试项。" />
    </label>
    {pendingRun ? <div className="flex flex-wrap items-center gap-2 text-sm" role="status">
      <span>{pollPaused ? "任务状态待查询" : "建议正在后台处理，可稍后回来查看。"}</span>
      {pollPaused ? <Button variant="outline" onClick={() => { setError(null); setPollPaused(false); setPollRevision((n) => n + 1); }}>重新查询状态</Button> : null}
      <Button variant="outline" disabled={busy} onClick={() => void cancelPending()}>取消任务</Button>
    </div> : null}
    {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
    <div className="flex gap-2"><Button disabled={processing || !message.trim()} onClick={() => void send()}>{busy ? "正在处理…" : "生成调整建议"}</Button><Button variant="outline" disabled={processing} onClick={() => void start()}>刷新已保存建议</Button></div>
  </section>;
}
