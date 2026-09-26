"use client";

import { KnowledgeReuseRequests } from "./knowledge-reuse-requests";
import { KnowledgeReuseHistory } from "./knowledge-reuse-history";
import { knowledgeKindLabel } from "./knowledge-kind";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { MemorySources } from "./memory-sources";
import { CorrectionForm } from "./knowledge-corrections";
import { parseMemory } from "./memory-api";
import type { MemoryRecord } from "./memory-types";

type Feedback = { action: "adopted" | "not_useful"; reason: string };
type Suggestion = { id: string; memory: MemoryRecord; similarity: number; href: string; feedback: Feedback | null };
type ContextKind = "project_kickoff" | "change_request" | "part_selection" | "task_takeover";
const contextLabels: Record<ContextKind, string> = {
  project_kickoff: "项目目标与说明", change_request: "变更标题与原因",
  part_selection: "规格与验收条件", task_takeover: "任务目标与预期输出",
};
function feedback(value: unknown): Feedback {
  if (!isRecord(value) || !["adopted", "not_useful"].includes(String(value.action)) || typeof value.reason !== "string") throw new Error("使用回执不完整，请刷新");
  return { action: value.action as Feedback["action"], reason: value.reason };
}
async function ok(response: Response) {
  if (!response.ok) {
    const value: unknown = await responseBody(response).catch(() => null);
    const message = isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "相关经验暂不可用，请稍后重试";
    throw new Error(message);
  }
  return response.status === 204 ? null : responseBody(response);
}
function suggestions(value: unknown): Suggestion[] {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("经验列表不完整");
  return value.items.map((item: unknown) => {
    if (!isRecord(item) || typeof item.push_id !== "string" || typeof item.similarity !== "number" || !Number.isFinite(item.similarity) || typeof item.href !== "string") throw new Error("经验来源不完整");
    const memory = parseMemory(item.memory);
    const href = `/knowledge?project=${memory.project_id}&memory=${memory.id}`;
    if (item.href !== href || !/^[0-9a-f-]{36}$/.test(memory.id) || !/^[0-9a-f-]{36}$/.test(memory.project_id) || memory.status !== "verified") throw new Error("经验当前尚未审核或来源不一致");
    return { id: item.push_id, memory, similarity: item.similarity, href,
      feedback: item.feedback === null ? null : feedback(item.feedback) };
  });
}
function Experience({ item, basis }: { item: Suggestion; basis: string }) {
  const [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [receipt, setReceipt] = useState(item.feedback);
  const [error, setError] = useState<string | null>(null);
  async function open() {
    setBusy(true); setError(null);
    try {
      await ok(await fetch(`/api/knowledge/pushes/${encodeURIComponent(item.id)}/engage`, { method: "POST", cache: "no-store" }));
      setOpened(true);
    } catch (error) { setError(error instanceof Error ? error.message : "经验暂不可用"); }
    finally { setBusy(false); }
  }
  async function record(action: Feedback["action"]) {
    setBusy(true); setError(null);
    try {
      const result = await ok(await fetch(`/api/knowledge/pushes/${encodeURIComponent(item.id)}/feedback`, {
        method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reason: reason.trim(), expected_content_sha256: item.memory.content_sha256 }),
      }));
      setReceipt(feedback(result));
    } catch (error) { setError(error instanceof Error ? error.message : "使用反馈未保存"); }
    finally { setBusy(false); }
  }
  return <li className="space-y-2 rounded-lg border bg-background p-3">
    <div className="flex flex-wrap items-start justify-between gap-2"><strong className="text-sm">{item.memory.title} · {knowledgeKindLabel(item.memory.knowledge_kind)}</strong><span className="text-xs text-muted-foreground">已人工审核</span></div>
    <p className="text-xs text-muted-foreground">按{basis}匹配 · 相似度 {Math.round(item.similarity * 100)}% · 内容版本 {item.memory.content_sha256.slice(0, 12)}</p>
    <p className="whitespace-pre-wrap text-sm">适用条件：{item.memory.applicability ?? "未说明，使用前请核对当前条件"}</p>
    {!opened ? <Button size="sm" variant="outline" disabled={busy} onClick={open}>展开经验与使用反馈</Button> : <>
      <p className="whitespace-pre-wrap text-sm">{item.memory.content}</p>
      <Link href={item.href} className="text-sm text-primary underline underline-offset-4">查看知识记录与原始来源</Link>
      <p className="text-xs text-muted-foreground">相似度表示内容相关性；采用前请核对原始证据版本和当前适用条件。</p>
      <MemorySources key={item.memory.id} projectId={item.memory.project_id} memoryId={item.memory.id} />
      <CorrectionForm key={`${item.memory.id}:${item.memory.content_sha256}`} memory={item.memory} />
      {!receipt && <div className="space-y-2"><label className="block text-xs">采用到哪里，或为什么不适用<textarea className="mt-1 block min-h-20 w-full rounded-md border bg-background p-2 text-sm" value={reason} maxLength={5000} onChange={event => setReason(event.target.value)} /></label>
        <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || !reason.trim()} onClick={() => record("adopted")}>记录已采用</Button><Button size="sm" variant="outline" disabled={busy || !reason.trim()} onClick={() => record("not_useful")}>本次不适用</Button></div></div>}
    </>}
    {receipt && <p role="status" className="whitespace-pre-wrap text-sm">{receipt.action === "adopted" ? "已记录本次采用" : "已记录本次不适用"}：{receipt.reason}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </li>;
}

const preparedLabels: Record<string, string> = {
  pending: "业务事件已记录，等待准备相关经验。", running: "正在准备相关经验。",
  ready: "已为这项工作准备相关经验，采用前请核对适用条件。",
  empty: "本次自动检索没有找到达到相关性要求的已审核经验，可继续办理。",
  stale: "原业务或权限已变化，原推荐已停止展示；可按当前资料重新查找。",
  failed: "本次自动检索未完成，可手动查找相关经验。",
  uncertain: "本次检索没有取得完整回执，已停止自动重试；可手动发起新的查找。",
};
function PreparedKnowledge({ projectId, contextKind, entityId, selectedJobId }: { projectId: string; contextKind: ContextKind; entityId: string; selectedJobId?: string }) {
  const [result, setResult] = useState<{ state: string; enabled: boolean; unavailable: number; job: Record<string, unknown>; items: Suggestion[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ context_kind: contextKind, context_entity_id: entityId, ...(selectedJobId ? { job_id: selectedJobId } : {}) });
    void fetch(`/api/projects/${encodeURIComponent(projectId)}/knowledge-prepared?${query}`, { cache: "no-store", signal: controller.signal })
      .then(ok).then(value => {
        if (!isRecord(value) || !isRecord(value.job) || typeof value.job.state !== "string" || typeof value.job.enabled !== "boolean") throw new Error("预备经验的状态暂不可读取");
        if (!controller.signal.aborted) { setResult({ state: value.job.state, enabled: value.job.enabled, job: value.job, unavailable: typeof value.job.unavailable_count === "number" ? value.job.unavailable_count : 0, items: suggestions(value) }); setError(null); }
      }).catch(failure => { if (!controller.signal.aborted) { setResult(null); setError(failure instanceof Error ? failure.message : "预备经验暂不可读取"); } });
    return () => controller.abort();
  }, [projectId, contextKind, entityId, selectedJobId, refresh]);
  if (!error && (!result || result.state === "not_requested")) return null;
  return <div className="space-y-2 rounded-lg border p-3" aria-label="为当前工作准备的经验">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">{selectedJobId ? "所选历史准备请求" : "这项工作可能用得上的经验"}</h3><Button type="button" size="sm" variant="ghost" onClick={() => setRefresh(value => value + 1)}>刷新准备状态</Button></div>
    {error ? <p className="text-xs text-muted-foreground">{error} 当前工作可继续办理。</p> : null}
    {result && selectedJobId ? <p className="text-xs text-muted-foreground">正在查看所选请求的当前结果。{result.job.input_matches_current === true ? "其业务输入与当前一致。" : "其业务输入已与当前不同，原处理记录保留。"}</p> : null}
    {result ? <><p className="text-xs text-muted-foreground">{result.state === "pending" && !result.enabled ? "业务触发已记录，自动准备尚未启用。可使用下方手动查找。" : preparedLabels[result.state] ?? "准备状态暂不可识别，请刷新。"}</p>
      {result.unavailable > 0 ? <p className="text-xs text-muted-foreground">部分原推荐的依据或读取权限已变化，已停止展示。</p> : null}
      {typeof result.job.id === "string" ? <KnowledgeReuseHistory key={result.job.id} projectId={projectId} job={result.job} onResumed={() => setRefresh(value => value + 1)}/> : null}
      <ul className="space-y-2">{result.items.map(item => <Experience key={`${item.id}:${item.memory.content_sha256}`} item={item} basis={contextLabels[contextKind]}/>)}</ul>
    </> : null}
    {!selectedJobId ? <KnowledgeReuseRequests projectId={projectId} contextKind={contextKind} entityId={entityId} renderJob={id => <PreparedKnowledge projectId={projectId} contextKind={contextKind} entityId={entityId} selectedJobId={id}/>}/> : null}
  </div>;
}

export function ContextKnowledge({ projectId, contextKind, entityId }: { projectId: string; contextKind: ContextKind; entityId: string }) {
  const [items, setItems] = useState<Suggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  async function load() {
    setOpen(true); setBusy(true); setError(null); setItems(null);
    try {
      const query = new URLSearchParams({ context_kind: contextKind, context_entity_id: entityId });
      const result = await ok(await fetch(`/api/projects/${encodeURIComponent(projectId)}/knowledge-push?${query}`, { cache: "no-store" }));
      setItems(suggestions(result)); setRevision(value => value + 1);
    } catch (error) { setError(error instanceof Error ? error.message : "相关经验暂不可用"); }
    finally { setBusy(false); }
  }
  return <section aria-label="相关已审核经验" className="mt-3 space-y-2">
    <PreparedKnowledge key={`${projectId}:${contextKind}:${entityId}`} projectId={projectId} contextKind={contextKind} entityId={entityId}/>
    <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={load}>{busy ? "正在查找相关经验…" : "查找相关已审核经验"}</Button>{open && <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>收起</Button>}</div>
    {open && <><p className="text-xs text-muted-foreground">仅查找当前有权访问的已审核记录，最多展示 5 条。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {items?.length === 0 && <p className="text-sm text-muted-foreground">暂未找到达到相关性要求的已审核经验。可继续办理当前工作。</p>}
      {items && <ul className="space-y-2">{items.map(item => <Experience key={`${item.id}:${revision}`} item={item} basis={contextLabels[contextKind]} />)}</ul>}
    </>}
  </section>;
}
