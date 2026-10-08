"use client";

import { flushSync } from "react-dom";
import { ArrowUpIcon, PaperclipIcon, PlusIcon, SparkleIcon, StopIcon } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { PreprojectDialogue, type PreprojectAssessment } from "./preproject-dialogue";
import { PreprojectHistory } from "./preproject-history";
import { XiaopaiProcess, type ReplyProcess } from "./xiaopai-process";
import type { PreprojectLaunch } from "./xiaopai-launcher";
import { Button } from "@/components/ui/button";
import { XiaopaiAnswer } from "./xiaopai-answer";

export type SessionScope = { scope_kind: "personal" | "market_space" | "product_line" | "project"; project_id?: string; market_space_id?: string; product_line_id?: string };
type Session = SessionScope & { id: string; visibility: "private" | "project"; context_version: number; archived_at: string | null; title?: string; updated_at?: string };
type Message = { preproject_goal?: "category" | "proposal" | null; id: string; body: string; sequence: number; request_id: string };
type Detail = { conversation: Session; items: Message[]; next_before?: number | null; next_before_sequence?: number | null };
type Reply = { process?: ReplyProcess; preproject?: PreprojectAssessment; status: "answered" | "unavailable" | "running"; answer: string | null; error_code?: string | null; citations?: { reference_id: string; label: string; href: string }[]; research?: { candidate_count?: number; observations: { tool: string; target: string; status: string; shown_count?: number; provider_key?: string; providers_tried?: string[] }[] } };
type Job = { preprojectGoal?: PreprojectLaunch["goal"]; createId: string; requestId: string; body: string; cid?: string; mid?: string; version?: number };
export type SessionActivity = "running" | "attention" | null;
type Props = { visible?:boolean; preprojectGoal?: PreprojectLaunch["goal"]; scope: SessionScope; identityKey: string; initialConversationId?: string; initialToolsOpen?: boolean; disabled?: boolean; onConversationReady: (id: string) => void; onPendingChange: (value: boolean) => void; onActivityChange?: (value: SessionActivity) => void; onReplyReady?: (status: Reply["status"]) => void; onAuthorityLost: (message: string) => void; renderTools: (id: string) => ReactNode };

class SessionError extends Error { constructor(message: string, readonly status = 0) { super(message); } }
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...(body !== undefined ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const value = await response.json().catch(() => { throw new SessionError("会话回执暂不可用，请查询原消息后继续", response.status); });
  if (!response.ok) throw new SessionError(value.detail?.message ?? "会话暂不可用，请查询原消息后继续", response.status);
  return value;
}

export async function consumeReplyStream(response: Response, receive: (event: Record<string, unknown>) => void) {
  if (!response.ok) { const value = await response.json().catch(() => null); throw new SessionError(value?.detail?.message ?? "回复暂不可用，请查询原请求", response.status); }
  if (!response.headers.get("content-type")?.startsWith("text/event-stream") || !response.body) throw new SessionError("未收到回复流，请查询原请求");
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", finished = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
        const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as Record<string, unknown>;
        receive(event);
        if (event.type === "done") finished = true;
      }
      if (done) break;
    }
    if (!finished) throw new SessionError("回复连接中断，已保存的消息可以继续查询");
  } finally { reader.releaseLock(); }
}

function unavailable(reply: Reply) {
  if (reply.error_code === "APPLICATION_RESEARCH_BUDGET_REQUIRED") return "自动研究尚未启用：本地运行计量与预算配置未完成。消息已保存，可以继续讨论需求。";
  if (reply.error_code === "BUDGET_TENANT_CALL_BUSY") return "当前回复名额已占满，有正在处理或等待用量核对的请求。你的消息已保存，需要先完成或核对已有请求。";
  if (reply.error_code === "BUDGET_LINEAGE_CALL_BUSY") return "这次研究还有未完成或待核对用量的调用，暂时无法继续。你的消息已保存，请先核对原请求。";
  if (reply.error_code === "PREPROJECT_OUTPUT_INVALID") return "候选的来源或内容校验未通过，未保存品类或提案。可以继续对话重新起草。";
  if (reply.error_code === "REPLY_CANCELLED") return "已停止这次回复。可以继续发消息。";
  if (reply.error_code === "REPLY_SOURCE_CHANGED") return "相关资料或权限已变化，请重新核对后继续提问。";
  if (reply.error_code === "PROVIDER_OUTPUT_TRUNCATED") return "模型回复达到长度上限，未能完整返回。消息已保留，可以继续发消息。";
  if (reply.error_code?.startsWith("PROVIDER_") || reply.error_code === "STRUCTURED_OUTPUT_INVALID") return "模型回复未能完整接收或正确处理。消息已保留，可以继续发消息。";
  if (reply.error_code?.includes("MODEL") || reply.error_code?.includes("QUALIFICATION")) return "模型当前不可用，暂时无法生成回复。你的消息已保留，请在模型设置核对配置与资格。";
  return "这次回复未完成，消息已保留。可以查看原请求状态，或继续说明你的问题。";
}
function sameScope(session: Session, scope: SessionScope) { return session.scope_kind === scope.scope_kind && (session.project_id ?? "") === (scope.project_id ?? "") && (session.market_space_id ?? "") === (scope.market_space_id ?? "") && (session.product_line_id ?? "") === (scope.product_line_id ?? ""); }

function ResearchActivity({ research }: { research: Reply["research"] }) {
  if (!research?.observations.length) return null;
  const read = research.observations.filter(item => item.tool === "read" && ["completed", "partial"].includes(item.status)).length;
  const searches = research.observations.filter(item => item.tool === "search");
  const candidates = research.candidate_count ?? searches.reduce((sum, item) => sum + (item.shown_count ?? 0), 0);
  return <details className="mb-3 text-xs text-muted-foreground"><summary className="cursor-pointer">已检索资料 · 搜索 {searches.length} 次 · 线索 {candidates} 条 · 读取 {read} 份</summary><ul className="mt-2 space-y-2">{research.observations.map((item, index) => <li key={index} className="break-words">{item.tool === "search" ? "搜索" : "读取"}：{item.target}{item.provider_key ? ` · ${item.provider_key === "local-index" ? "本地索引" : item.provider_key === "tavily" ? "Tavily" : item.provider_key === "firecrawl" ? "Firecrawl" : "SearXNG"}` : ""}{item.providers_tried && item.providers_tried.length > 1 ? `（已尝试 ${item.providers_tried.join(" → ")}）` : ""} · {item.status === "no_results" ? "没有命中" : item.status === "unavailable" ? "暂不可用" : item.status === "partial" ? "部分完成" : "已完成"}{item.tool === "search" && item.shown_count !== undefined ? ` · ${item.shown_count} 条线索` : ""}</li>)}</ul></details>;
}

export function XiaopaiSession({ visible=true, preprojectGoal, scope, identityKey, initialConversationId, initialToolsOpen = false, disabled, onConversationReady, onPendingChange, onActivityChange, onReplyReady, onAuthorityLost, renderTools }: Props) {
  const scopeKey = JSON.stringify(scope), storageKey = `pdos-pai-session:${identityKey}:${scopeKey}`;
  const draftKey = `${storageKey}:draft:${preprojectGoal ?? "chat"}`;
  const [sessions, setSessions] = useState<Session[]>([]), [detail, setDetail] = useState<Detail | null>(null), [replies, setReplies] = useState<Record<string, Reply>>({});
  const [draft, setDraft] = useState(""), [optimistic, setOptimistic] = useState(""), [text, setText] = useState(""), [status, setStatus] = useState(""), [error, setError] = useState("");
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [toolsOpen, setToolsOpen] = useState(initialToolsOpen), [denied, setDenied] = useState(false), [stopping, setStopping] = useState(false);
  const [jobView, setJobView] = useState<Job | null>(null);
  const [runReady, setRunReady] = useState(false);
  const [process, setProcess] = useState<ReplyProcess | null>(null);
  const [applying,setApplying] = useState(false);
  const [livePreprojectMessage,setLivePreprojectMessage] = useState<string | null>(null);
  const job = useRef<Job | null>(null), cid = useRef(initialConversationId), version = useRef(1), active = useRef(true), running = useRef(false);
  const callbacks = useRef({ visible, onConversationReady, onPendingChange, onActivityChange, onReplyReady, onAuthorityLost });
  const scroll = useRef<HTMLDivElement>(null), follow = useRef(true), input = useRef<HTMLTextAreaElement>(null);
  const toolsCreation = useRef<string | null>(null);
  useEffect(() => { callbacks.current = { visible, onConversationReady, onPendingChange, onActivityChange, onReplyReady, onAuthorityLost }; }, [visible, onConversationReady, onPendingChange, onActivityChange, onReplyReady, onAuthorityLost]);
  useEffect(() => { if (!loading) callbacks.current.onActivityChange?.(busy ? "running" : unknown ? "attention" : null); }, [busy, unknown, loading]);
  function remember(value: Job | null) { job.current = value; setJobView(value ? { ...value } : null); try { if (value) sessionStorage.setItem(storageKey, JSON.stringify(value)); else sessionStorage.removeItem(storageKey); } catch { /* The server retains the original message and reply. */ } }
  const fail = useCallback((failure: unknown) => {
    if (!active.current) return;
    const message = failure instanceof Error ? failure.message : "会话暂不可用";
    if (failure instanceof SessionError && [401, 403].includes(failure.status)) {
      setDetail(null); setReplies({}); setProcess(null); setText(""); setOptimistic(""); setDraft(""); setSessions([]); setDenied(true); setUnknown(false); job.current = null; setJobView(null); try { sessionStorage.removeItem(storageKey); sessionStorage.removeItem(draftKey); } catch {} callbacks.current.onPendingChange(false); callbacks.current.onAuthorityLost(message);
    }
    setError(message);
  }, [storageKey, draftKey]);
  const load = useCallback(async (id?: string, before?: number) => {
    const entries = await request<{ items: Session[] }>(`/api/conversations?${new URLSearchParams(JSON.parse(scopeKey))}`);
    if (!active.current) return;
    const available = entries.items.filter(item => sameScope(item, JSON.parse(scopeKey))); setSessions(available);
    const chosen = id ?? cid.current ?? (preprojectGoal ? undefined : available.find(item => !item.archived_at)?.id);
    if (!chosen) { setDetail(null); return; }
    const value = await request<Detail>(`/api/conversations/${chosen}${before ? `?before_sequence=${before}` : ""}`);
    if (!active.current) return;
    if (!sameScope(value.conversation, JSON.parse(scopeKey))) throw new SessionError("对话不属于当前工作范围", 403);
    cid.current = chosen; version.current = value.conversation.context_version;
    setDetail(old => before && old ? { ...value, items: [...value.items, ...old.items].filter((item, index, all) => all.findIndex(other => other.id === item.id) === index) } : value);
    callbacks.current.onConversationReady(chosen);
    const loaded = await Promise.all(value.items.map(async message => ({ id: message.id, value: await request<{ reply: Reply | null }>(`/api/conversations/${chosen}/messages/${message.id}/reply`) })));
    if (active.current) setReplies(old => ({ ...old, ...Object.fromEntries(loaded.filter(item => item.value.reply).map(item => [item.id, item.value.reply!])) }));
    return value;
  }, [scopeKey, preprojectGoal]);
  useEffect(() => {
    active.current = true;
    void Promise.resolve().then(() => {
      if (!active.current) return;
      try { setDraft(sessionStorage.getItem(draftKey) ?? ""); const saved = sessionStorage.getItem(storageKey); if (saved) { job.current = JSON.parse(saved); setJobView(job.current); setUnknown(true); callbacks.current.onPendingChange(!job.current?.mid); } } catch { /* Storage is optional. */ }
      return load(job.current?.cid ?? cid.current);
    }).catch(fail).finally(() => { if (active.current) setLoading(false); });
    return () => { active.current = false; callbacks.current.onPendingChange(false); };
  }, [load, fail, storageKey, draftKey]);
  useEffect(() => { if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [detail, text, optimistic, status, process]);
  function release() { remember(null); setUnknown(false); setOptimistic(""); setText(""); setStatus(""); setProcess(null); callbacks.current.onPendingChange(false); }
  async function execute(original: Job) {
    if (running.current || denied || disabled) return;
    running.current = true; setBusy(true); setRunReady(false); setProcess(null); setUnknown(false); setError(""); setStatus("正在发送…"); setOptimistic(original.body); follow.current = true; remember(original); callbacks.current.onPendingChange(true);
    try {
      if (!original.cid) {
        const created = await request<Session>("/api/conversations", { ...scope, visibility: "private", request_id: original.createId });
        if (!active.current) return;
        if (!sameScope(created, scope)) throw new SessionError("对话范围不符", 403);
        setSessions(old => [created, ...old.filter(item => item.id !== created.id)]);
        original.cid = created.id; original.version = created.context_version; cid.current = created.id; version.current = created.context_version; callbacks.current.onConversationReady(created.id); remember(original);
      }
      if (!original.mid) {
        const message = await request<Message>(`/api/conversations/${original.cid}/messages`, { request_id: original.requestId, expected_context_version: original.version ?? version.current, action: "note", reply_only: true, ...(original.preprojectGoal ? {preproject_goal: original.preprojectGoal} : {}), body: original.body });
        if (!active.current) return;
        original.mid = message.id; remember(original); setDraft(old => {if(old.trim() !== original.body)return old;try{sessionStorage.removeItem(draftKey);}catch{}return "";}); callbacks.current.onPendingChange(false);
        setDetail(old => old ? { ...old, items: old.items.some(item => item.id === message.id) ? old.items : [...old.items, message] } : { conversation: { ...scope, id: original.cid!, context_version: original.version ?? 1, visibility: "private", archived_at: null }, items: [message] });
        setOptimistic("");
      }
      let result: Reply | undefined;
      const response = await fetch(`/api/conversations/${original.cid}/messages/${original.mid}/reply`, { method: "POST", cache: "no-store" });
      await consumeReplyStream(response, event => {
        if (!active.current) return;
        if (event.type === "status") { if (event.process) setProcess(event.process as ReplyProcess); setStatus(String(event.message)); if (typeof event.run_id === "string") setRunReady(true); }
        if (event.type === "text") setText(String(event.text ?? ""));
        if (event.type === "error") { setText(""); throw new SessionError(String(event.message), Number(event.status)); }
        if (event.type === "result") { result = event.reply as Reply; setText(""); if (result) {setReplies(old => ({ ...old, [original.mid!]: result! }));if(result.preproject)setLivePreprojectMessage(original.mid!);} }
      });
      if (!active.current) return;
      if (!result || result.status === "running") { setUnknown(true); setStatus("原回复正在运行，可继续查询"); return; }
      callbacks.current.onReplyReady?.(result.status);
      release(); if (callbacks.current.visible) input.current?.focus();
    } catch (failure) { fail(failure); setText(""); if (active.current && !(failure instanceof SessionError && [401, 403].includes(failure.status))) { setUnknown(true); callbacks.current.onPendingChange(!job.current?.mid); } }
    finally { running.current = false; if (active.current) { setBusy(false); setStopping(false); } }
  }
  const recovering = useRef(false);
  async function queryOriginal() {
    const original = job.current; if (!original || busy || recovering.current) return;
    recovering.current = true;
    setLoading(true); setError("");
    try {
      const value = await load(original.cid);
      if (!active.current) return;
      const message = value?.items.find(item => item.id === original.mid || item.request_id === original.requestId);
      if (message) { original.cid = value!.conversation.id; original.mid = message.id; remember(original); const saved = await request<{ reply: Reply | null }>(`/api/conversations/${original.cid}/messages/${original.mid}/reply`); if (saved.reply && saved.reply.status !== "running") { setReplies(old => ({ ...old, [message.id]: saved.reply! })); setDraft(old => old.trim() === original.body ? "" : old); callbacks.current.onReplyReady?.(saved.reply.status); release(); } else setStatus(saved.reply ? "原回复仍在生成，可以稍后再次查询" : "消息已保存，可以继续此条回复"); }
    } catch (failure) { fail(failure); } finally { recovering.current = false; if (active.current) setLoading(false); }
  }
  const pollOriginal = useRef(queryOriginal);
  useEffect(() => { pollOriginal.current = queryOriginal; });
  useEffect(() => {
    if (!unknown || busy || denied || !jobView?.mid) return;
    // Recovery reads the durable result; it never dispatches another model call.
    const timer = window.setInterval(() => { void pollOriginal.current(); }, 5000);
    return () => window.clearInterval(timer);
  }, [unknown, busy, denied, jobView?.mid]);
  async function stop() {
    const original = job.current; if (!original?.cid || !original.mid || !runReady || stopping) return;
    setStopping(true);
    try { await request(`/api/conversations/${original.cid}/messages/${original.mid}/reply/cancel`, {}); setStatus("正在停止回复…"); } catch (failure) { setStopping(false); fail(failure); }
  }
  async function openTools() {
    if (busy || unknown || loading || denied) return;
    if (detail?.conversation.id) { setToolsOpen(value => !value); return; }
    setLoading(true);
    toolsCreation.current ??= crypto.randomUUID();
    try {
      const created = await request<Session>("/api/conversations", { ...scope, visibility: "private", request_id: toolsCreation.current });
      if (!active.current) return;
      if (!sameScope(created, scope)) throw new SessionError("对话范围不符", 403);
      setSessions(old => [created, ...old.filter(item => item.id !== created.id)]);
      cid.current = created.id; version.current = created.context_version; toolsCreation.current = null;
      setDetail({ conversation: created, items: [] }); callbacks.current.onConversationReady(created.id); setToolsOpen(true);
    } catch (failure) { fail(failure); } finally { if (active.current) setLoading(false); }
  }
  const activeGoal = preprojectGoal ?? detail?.items.at(-1)?.preproject_goal ?? undefined;
  const locked = disabled || loading || busy || unknown || applying || denied || !!detail?.conversation.archived_at;
  return <section aria-label="小Pai会话" className="flex min-h-0 flex-1 flex-col">
    <div className="flex shrink-0 items-center justify-between gap-2 px-5 py-2">
      <p className="text-xs text-muted-foreground">{detail?.conversation.visibility === "project" ? "项目成员可见" : "私人会话 · 仅你可见"}</p>
      <div className="flex items-center gap-1">
        {activeGoal === "proposal" && scope.market_space_id && <PreprojectHistory categoryId={scope.market_space_id} disabled={locked} onDenied={(message,status)=>fail(new SessionError(message,status))}/>}
        {sessions.length > 0 && <select aria-label="历史会话" className="max-w-32 rounded-md bg-transparent p-1 text-xs" disabled={busy || unknown || loading} value={detail?.conversation.id ?? ""} onChange={event => { setReplies({}); setToolsOpen(false); setLoading(true); void load(event.target.value).catch(fail).finally(() => setLoading(false)); }}><option value="" disabled>历史会话</option>{sessions.map(item => <option key={item.id} value={item.id}>{item.title || "历史会话"}{item.updated_at ? ` · ${new Date(item.updated_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}{item.archived_at ? " · 已归档" : ""}</option>)}</select>}
        <Button variant="ghost" size="sm" aria-label="新建小Pai会话" disabled={busy || unknown || loading} onClick={() => { cid.current = undefined; callbacks.current.onConversationReady(""); setDetail(null); setReplies({}); setDraft(""); setError(""); setToolsOpen(false); input.current?.focus(); }}><PlusIcon aria-hidden="true"/>新会话</Button>
      </div>
    </div>
    <div ref={scroll} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5" onScroll={event => { const element = event.currentTarget; follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; }}>
      {loading && <p role="status" className="text-sm text-muted-foreground">正在读取会话…</p>}
      {!loading && !detail?.items.length && !optimistic && !denied && <div className="flex h-full min-h-48 flex-col items-center justify-center text-center"><SparkleIcon className="mb-4 size-9 text-primary" weight="fill" aria-hidden="true"/><h2 className="text-xl font-medium">{activeGoal === "category" ? "一起建立一个品类" : activeGoal === "proposal" ? "先聊聊这次产品需求" : "有什么想一起处理？"}</h2><p className="mt-3 max-w-xs text-sm leading-6 text-muted-foreground">{activeGoal === "category" ? "告诉我想研究什么产品、给谁用。我会追问关键模糊点，再搜索并整理品类资料。" : activeGoal === "proposal" ? "客户需求、新品想法或派生迭代都可以。先说目标，我会继承当前品类资料并起草提案。" : <>直接说出问题或目标。<br/>可以接着上文聊，也可以直接让我搜索资料。</>}</p></div>}
      {(detail?.next_before ?? detail?.next_before_sequence) && <Button variant="ghost" size="sm" disabled={locked} onClick={() => void load(cid.current, detail?.next_before ?? detail?.next_before_sequence ?? undefined).catch(fail)}>更早的消息</Button>}
      <div role="log" aria-label="会话消息" aria-live="polite" className="space-y-8">
        {detail?.items.map(message => <div key={message.id} className="space-y-4"><article aria-label="你的消息" className="ml-8 rounded-lg bg-muted/70 px-4 py-3"><p className="whitespace-pre-wrap break-words text-sm leading-6">{message.body}</p></article>{replies[message.id] && <article aria-label="小Pai回复" className="flex gap-3"><SparkleIcon aria-hidden="true" weight="fill" className="mt-1 size-5 shrink-0 text-primary"/><div className="min-w-0 flex-1"><XiaopaiProcess process={replies[message.id].process}/><ResearchActivity research={replies[message.id].research}/>{replies[message.id].answer ? <XiaopaiAnswer answer={replies[message.id].answer!} researchDraft={replies[message.id].research?.observations.some(item => item.tool === "read" && ["completed", "partial"].includes(item.status))}/> : <p className="whitespace-pre-wrap break-words text-sm leading-7">{replies[message.id].status === "running" ? "回复正在生成，可查询原请求继续查看。" : unavailable(replies[message.id])}</p>}{visible && replies[message.id].preproject && message.id === detail.items.at(-1)?.id && <PreprojectDialogue key={message.id} autoOpen={livePreprojectMessage===message.id} assessment={replies[message.id].preproject!} citations={replies[message.id].citations} disabled={locked} onAnswer={body=>void execute({createId:crypto.randomUUID(),requestId:crypto.randomUUID(),cid:cid.current,version:version.current,body,preprojectGoal:replies[message.id].preproject!.goal})} onConfirm={async()=>{setApplying(true);callbacks.current.onPendingChange(true);try{const applied = await request<{href:string}>(`/api/conversations/${detail.conversation.id}/messages/${message.id}/preproject/confirm`, {candidate_digest:replies[message.id].preproject!.candidate_digest,confirmed:true,confirmed_shared:replies[message.id].preproject!.goal === "category"});flushSync(()=>{setApplying(false);callbacks.current.onPendingChange(false);});window.location.assign(applied.href);}catch(failure){if(failure instanceof SessionError && [401,403].includes(failure.status))fail(failure);throw failure;}finally{setApplying(false);callbacks.current.onPendingChange(false);}}}/>}{replies[message.id].citations?.length ? <details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer">参考资料 · {replies[message.id].citations!.length}</summary><div className="mt-2 space-y-2">{replies[message.id].citations!.map(ref => <a key={ref.reference_id} className="block text-primary underline" href={ref.href}>{ref.label}</a>)}</div></details> : null}</div></article>}</div>)}
        {optimistic && <article aria-label="正在发送的消息" className="ml-8 rounded-lg bg-muted/70 px-4 py-3"><p className="whitespace-pre-wrap break-words text-sm leading-6">{optimistic}</p></article>}
        {(busy || unknown) && <article aria-label="小Pai正在回复" aria-busy={busy} className="flex gap-3"><SparkleIcon aria-hidden="true" className="mt-1 size-5 shrink-0 text-primary motion-safe:animate-pulse"/><div className="min-w-0 flex-1">{process && <XiaopaiProcess process={process} live={busy}/>}{!process && <p role="status" className="text-xs text-muted-foreground">{text ? "正在回复…" : status || "正在连接…"}</p>}{text && <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7">{text}</p>}</div></article>}
      </div>
      {error && <p role="alert" className="mt-4 text-sm text-destructive">{error}</p>}
      {unknown && <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || loading} onClick={() => void queryOriginal()}>查询原回复</Button><Button size="sm" variant="ghost" disabled={busy || loading} onClick={() => job.current && void execute(job.current)}>继续原请求</Button></div>}
    </div>
    {toolsOpen && detail?.conversation.id && <div className="max-h-[45vh] shrink-0 overflow-y-auto border-t px-5 py-3"><div className="mb-3 flex items-center justify-between"><p className="text-xs font-medium">会话资料与专业办理</p><Button size="sm" variant="ghost" onClick={() => { setToolsOpen(false); void load(cid.current).catch(fail); }}>返回对话</Button></div>{renderTools(detail!.conversation.id)}</div>}
    {!toolsOpen && <form className="shrink-0 border-t bg-background px-4 pb-4 pt-3" onSubmit={event => { event.preventDefault(); if (!locked && draft.trim()) void execute({ createId: crypto.randomUUID(), requestId: crypto.randomUUID(), cid: cid.current, version: version.current, body: draft.trim(), preprojectGoal: activeGoal }); }}>
      <div className="rounded-lg border bg-card p-3 shadow-sm focus-within:ring-2 focus-within:ring-ring/25">
        <textarea ref={input} aria-label="给小Pai的消息" value={draft} maxLength={2000} disabled={denied || disabled || !!detail?.conversation.archived_at} onChange={event => {setDraft(event.target.value);try{sessionStorage.setItem(draftKey,event.target.value);}catch{}}} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!locked && draft.trim()) event.currentTarget.form?.requestSubmit(); } }} placeholder={activeGoal === "category" ? "例如：研究欧美市场的桨板充气泵，给水上运动爱好者用…" : activeGoal === "proposal" ? "例如：客户想要更轻的充气泵，续航至少30分钟…" : "给小Pai发消息…"} className="max-h-40 min-h-20 w-full resize-none bg-transparent text-sm leading-6 outline-none"/>
        <div className="flex items-center justify-between gap-2"><Button type="button" size="sm" variant="ghost" disabled={busy || unknown || loading || denied} onClick={() => void openTools()}><PaperclipIcon aria-hidden="true"/>资料与办理</Button>{busy ? <Button type="button" size="icon" variant="outline" aria-label="停止小Pai回复" disabled={!jobView?.mid || !runReady || stopping} onClick={() => void stop()}><StopIcon weight="fill" aria-hidden="true"/></Button> : <Button type="submit" size="icon" aria-label="发送给小Pai" disabled={locked || !draft.trim()}><ArrowUpIcon weight="bold" aria-hidden="true"/></Button>}</div>
      </div>
      <p className="mt-2 text-center text-[10px] text-muted-foreground">Enter 发送 · Shift + Enter 换行</p>
    </form>}
  </section>;
}
