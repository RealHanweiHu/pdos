"use client";

import { ProjectConversation } from "./project-conversation";

import {
  ArrowSquareOutIcon,
  ChatCircleDotsIcon,
  PauseCircleIcon,
  QuotesIcon,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import { AgentRunsCard } from "./agent-runs-card";
import { requestAiChat, requestChatOperation } from "./ai-api";
import type { AiChatResponse, AiChatOperation } from "./ai-types";

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "AI 对话暂不可用";
}

export function ProjectAiChat({ projectId }: { projectId: string }) {
  return <div className="space-y-4"><ProjectConversation key={projectId} projectId={projectId} /><details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">原单次项目问答与运行记录</summary><div className="mt-3"><ProjectChatSession key={projectId} projectId={projectId} /></div></details></div>;
}

function ProjectChatSession({ projectId }: { projectId: string }) {
  const [question, setQuestion] = useState("");
  const [response, setResponse] = useState<AiChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pendingRequest = useRef<{ projectId: string; question: string; id: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState<AiChatOperation | null>(null);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [queryPaused, setQueryPaused] = useState(false);
  const storageKey = `pdos-chat-request:${projectId}`;
  const queued = operation?.status === "queued" || operation?.status === "running";
  const active = busy || queued || resumeId !== null;

  function remember(runId: string | null) {
    try { if (runId) sessionStorage.setItem(storageKey, runId); else sessionStorage.removeItem(storageKey); }
    catch { /* State remains available from the server when browser storage is disabled. */ }
  }

  function acceptOperation(value: AiChatOperation) {
    setOperation(value);
    setResumeId(null);
    if (value.status === "queued" || value.status === "running") remember(value.run_id);
    else {
      remember(null);
      setResponse(value.result);
      pendingRequest.current = null;
    }
  }

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      try {
        const saved = sessionStorage.getItem(storageKey);
        if (saved) setResumeId(saved);
      } catch { /* Browser storage is optional. */ }
    });
    return () => { disposed = true; };
  }, [storageKey]);

  const pollingId = queued ? operation.run_id : resumeId;
  useEffect(() => {
    if (!pollingId || queryPaused) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await requestChatOperation(pollingId!);
        if (disposed) return;
        if (value.project_id !== projectId) throw new Error("请求不属于当前项目");
        acceptOperation(value);
        if (value.status === "queued" || value.status === "running") timer = setTimeout(poll, 2000);
      } catch (error) {
        if (!disposed) { setError(messageFrom(error)); setQueryPaused(true); }
      }
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
    // Changes to the run identity restart polling; each query uses the same server request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollingId, projectId, queryPaused]);

  async function cancel() {
    if (!pollingId) return;
    try { acceptOperation(await requestChatOperation(pollingId, true)); setError(null); }
    catch (error) { setError(messageFrom(error)); }
  }


  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = question.trim();
    if (!normalized || active) return;
    if (pendingRequest.current?.projectId !== projectId || pendingRequest.current.question !== normalized) {
      pendingRequest.current = { projectId, question: normalized, id: crypto.randomUUID() };
    }
    setBusy(true);
    setError(null);
    setResponse(null);
    setOperation(null);
    setQueryPaused(false);
    try {
      const value = await requestAiChat(projectId, normalized, pendingRequest.current.id);
      if ("run_id" in value) acceptOperation(value);
      else { setResponse(value); pendingRequest.current = null; }
    } catch (requestError) {
      setError(messageFrom(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <AgentRunsCard projectId={projectId} />
    <section aria-label="项目 AI 对话" className="overflow-hidden rounded-lg border bg-card lg:grid lg:min-h-[520px] lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col border-b lg:border-b-0 lg:border-r">
        <header className="border-b px-4 py-4">
          <div className="flex items-center gap-2"><ChatCircleDotsIcon aria-hidden="true" className="text-primary" /><h2 className="font-semibold">项目 AI 对话</h2></div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">只根据当前项目的服务端白名单事实回答。每个回答必须附引用，无据时明确拒答。</p>
        </header>
        <div aria-live="polite" className="flex min-h-72 flex-1 flex-col justify-center px-4 py-8 sm:px-6">
          {!response && !error && !active && operation?.status !== "cancelled" ? (
            <div className="mx-auto max-w-md text-center">
              <QuotesIcon aria-hidden="true" className="mx-auto size-8 text-muted-foreground" />
              <h3 className="mt-3 font-medium">询问项目事实</h3>
              <p className="mt-1 text-sm text-muted-foreground">例如：“当前最需要关注的风险和问题是什么？”</p>
            </div>
          ) : null}
          {busy ? <div aria-busy="true" className="space-y-3"><div className="h-4 w-4/5 animate-pulse rounded-lg bg-muted" /><div className="h-4 w-3/5 animate-pulse rounded-lg bg-muted" /><div className="h-4 w-2/3 animate-pulse rounded-lg bg-muted" /></div> : null}
          {queued || resumeId ? <div role="status" className="space-y-3 rounded-lg border bg-muted/20 p-4">
            <p className="font-medium">{operation?.status === "running" ? "正在查证项目资料" : "请求已保存，等待处理"}</p>
            <p className="text-sm text-muted-foreground">可以离开此页，返回后继续查看结果。</p>
            <Button type="button" variant="outline" onClick={() => void cancel()}>取消请求</Button>
            {queryPaused ? <Button type="button" variant="outline" onClick={() => { setError(null); setQueryPaused(false); }}>重新查询</Button> : null}
          </div> : null}
          {operation?.status === "cancelled" ? <p role="status">请求已取消，可以重新提问。</p> : null}
          {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/8 px-4 py-4" role="alert"><p className="font-medium text-destructive">请求失败</p><p className="mt-1 text-sm text-muted-foreground">{error}</p></div> : null}
          {response?.status === "answered" ? (
            <article>
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">Evidence-grounded answer</p>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-7">{response.answer}</p>
              <p className="mt-4 text-xs text-muted-foreground">回答依据见右侧引用栏。</p>
            </article>
          ) : null}
          {response?.status === "insufficient_evidence" ? (
            <div className="rounded-lg border border-pending/30 bg-pending/8 px-4 py-4" role="status">
              <p className="font-medium text-pending">知识库无此依据</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">当前项目事实不足以支持可靠回答。系统没有补写或猜测结论。</p>
            </div>
          ) : null}
          {response?.status === "unavailable" && operation?.status !== "cancelled" ? (
            <div className="rounded-lg border border-pending/30 bg-pending/8 px-4 py-4" role="status">
              <div className="flex items-center gap-2 font-medium text-pending"><PauseCircleIcon aria-hidden="true" />AI 暂停</div>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">模型或预算当前不可用。项目数据与人工工作流仍可正常使用。</p>
            </div>
          ) : null}
        </div>
        <form className="border-t p-4" onSubmit={submit}>
          <label className="sr-only" htmlFor="project-ai-question">向项目 AI 提问</label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <textarea
              className="min-h-20 min-w-0 flex-1 resize-y rounded-lg border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25"
              disabled={active}
              id="project-ai-question"
              maxLength={2000}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="输入关于当前项目的问题…"
              value={question}
            />
            <Button className="h-11 self-end px-4" disabled={active || !question.trim()} type="submit">{active ? "处理中…" : "提问"}</Button>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">不会执行业务写入；建议类输出仍须进入 AI Review 人审。</p>
        </form>
      </div>

      <aside aria-label="回答引用" className="min-w-0 bg-muted/20">
        <h3 className="border-b px-4 py-3 font-semibold">引用</h3>
        {!response || response.citations.length === 0 ? <p className="px-4 py-8 text-center text-xs text-muted-foreground">回答后在此显示可跳转的项目证据。</p> : (
          <ol className="divide-y">
            {response.citations.map((citation, index) => (
              <li className="px-4 py-3" key={citation.reference_id}>
                <div className="flex items-start gap-2"><span className="font-mono text-[10px] text-muted-foreground">[{index + 1}]</span><div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{citation.label}</p><p className="mt-1 line-clamp-3 text-[11px] leading-5 text-muted-foreground">{citation.excerpt}</p><a className="mt-2 inline-flex min-h-11 items-center gap-1 text-xs font-medium text-primary sm:min-h-0" href={citation.href}>跳转证据 <ArrowSquareOutIcon aria-hidden="true" /></a></div></div>
              </li>
            ))}
          </ol>
        )}
      </aside>
    </section>
    </>
  );
}
