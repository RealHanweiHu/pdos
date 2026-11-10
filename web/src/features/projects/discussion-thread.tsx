"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import {
  activeQuery, agentReplyPath, agentSharePath, anchorLabel, cardInProgress, cardNote, cardTone, commentsPath, hasAgentMention,
  insertMention, mentionablePath, mentionChoices, mentionError, messagePath, segments, threadPath,
  type AgentCard, type AgentReply, type DiscussionMessage, type DiscussionScope, type Mentionable, type ThreadView,
} from "@/lib/discussions";
import { liveDelivery, type LiveMode } from "@/lib/notifications";
import styles from "./discussion.module.css";

type Api = typeof browserApi;
export type ThreadTarget = { kind: "thread"; threadId: string } | { kind: "object"; subjectType: "work_task" | "artifact"; subjectId: string };
type Props = { api: Api; scope: DiscussionScope; target: ThreadTarget; title?: string; live?: boolean; onChanged?: () => void; onOpenRun?: (runId: string) => void };
export type SubmitOptions = { agentPrivate: boolean };

const AGENT_POLL_MS = 3000;

function errorText(failure: unknown) {
  return mentionError(failure) ?? (failure instanceof Error ? failure.message : "暂未保存，请重试。");
}

export function MessageBody({ message, people }: { message: DiscussionMessage; people: Record<string, string> }) {
  if (message.retracted) return <p className={styles.retracted}>{message.placeholder ?? "已撤回"}</p>;
  return <p className={styles.body}>{segments(message.body, people).map((part, index) => part.kind === "text" ? <span key={index}>{part.text}</span> : <span key={index} className={styles.chip} data-kind={part.mention}>@{part.label}</span>)}</p>;
}

export function Composer({ api, scope, subjectType, subjectId, placeholder, submitLabel = "发送", onSubmit, disabled, initial = "", allowAgent = true }: {
  api: Api; scope: DiscussionScope; subjectType: string; subjectId?: string; placeholder: string; submitLabel?: string;
  onSubmit: (body: string, options: SubmitOptions) => Promise<void>; disabled?: boolean; initial?: string; allowAgent?: boolean;
}) {
  const scoped = api;
  const [text, setText] = useState(initial), [caret, setCaret] = useState(initial.length), [options, setOptions] = useState<Mentionable | null>(null);
  const [selected, setSelected] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState(""), [dismissed, setDismissed] = useState(-1);
  const [agentPrivate, setAgentPrivate] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null), loading = useRef(false);
  const found = activeQuery(text, caret), query = found && found.start !== dismissed ? found : null;
  const choices = query ? mentionChoices(options, query.query).filter(choice => allowAgent || choice.kind !== "agent") : [];
  const asksAgent = allowAgent && hasAgentMention(text);
  useEffect(() => {
    if (!query || options || loading.current) return;
    loading.current = true;
    scoped<Mentionable>(mentionablePath(scope, subjectType, subjectId)).then(setOptions).catch(() => setOptions({ people: [], roles: [], can_mention_all: false, can_invite: false, agent: { available: false, note: "" } })).finally(() => { loading.current = false; });
  }, [query, options, scoped, scope, subjectType, subjectId]);
  const pick = (index: number) => {
    const choice = choices[index];
    if (!choice || choice.disabled) return;
    const next = insertMention(text, caret, choice.token);
    setText(next.text); setCaret(next.caret); setSelected(0);
    requestAnimationFrame(() => { area.current?.focus(); area.current?.setSelectionRange(next.caret, next.caret); });
  };
  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true); setError("");
    try { await onSubmit(text.trim(), { agentPrivate: asksAgent && agentPrivate }); setText(""); setCaret(0); setAgentPrivate(false); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  };
  return <div className={styles.composer}>
    {query && choices.length > 0 && <ul className={styles.picker} role="listbox" aria-label="选择要提及的人">
      {choices.map((choice, index) => <li key={choice.key} role="option" data-kind={choice.kind} aria-selected={index === selected} aria-disabled={choice.disabled} title={choice.reason} onMouseDown={event => { event.preventDefault(); pick(index); }}>
        <span>{choice.kind === "agent" && <Sparkle size={12} weight="fill" aria-hidden="true"/>}@{choice.label}</span><small>{choice.detail}{choice.reason && choice.kind !== "agent" ? ` · ${choice.reason}` : ""}</small>
      </li>)}
    </ul>}
    <textarea ref={area} aria-label={placeholder} placeholder={placeholder} value={text} maxLength={8000} disabled={disabled || busy}
      onChange={event => { setText(event.target.value); setCaret(event.target.selectionStart ?? event.target.value.length); setSelected(0); }}
      onSelect={event => setCaret(event.currentTarget.selectionStart ?? 0)}
      onKeyDown={event => {
        if (query && choices.length) {
          if (event.key === "ArrowDown") { event.preventDefault(); setSelected(value => (value + 1) % choices.length); return; }
          if (event.key === "ArrowUp") { event.preventDefault(); setSelected(value => (value - 1 + choices.length) % choices.length); return; }
          if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); pick(selected); return; }
          if (event.key === "Escape") { event.preventDefault(); setDismissed(query.start); return; }
        }
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void submit(); }
      }}/>
    {asksAgent && <label className={styles.agentOption}><input type="checkbox" checked={agentPrivate} disabled={busy} onChange={event => setAgentPrivate(event.target.checked)}/>小Pai 的回复只给我看</label>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.composerFoot}><span>{asksAgent ? "小Pai 按你的权限运行；读取的来源都对这里的人可见时，回复贴回串里，否则只给你看。" : "输入 @ 提及能看到此处的成员或小Pai；提及只通知，不授予访问权、不构成分派。"}</span><Button size="sm" disabled={disabled || busy || !text.trim()} onClick={() => void submit()}>{busy ? "发送中…" : submitLabel}</Button></div>
  </div>;
}

/** The run card under a message that @-mentioned 小Pai: status for everyone, the reply and sharing for its requester. */
function AgentRunCard({ api, scope, threadId, card, onOpenRun, onView }: {
  api: Api; scope: DiscussionScope; threadId: string; card: AgentCard; onOpenRun?: (runId: string) => void; onView: (view: ThreadView) => void;
}) {
  const [reply, setReply] = useState<AgentReply | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [sharing, setSharing] = useState<"body" | null>(null), [acknowledged, setAcknowledged] = useState(false), key = useRef<string | null>(null);
  const note = cardNote(card), canRead = card.own ? card.delivery === "private" : card.can_open_link;
  const open = async () => {
    setBusy(true); setError("");
    try { setReply(await api<AgentReply>(agentReplyPath(scope, threadId, card.request_id))); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "回复暂不可读。"); }
    finally { setBusy(false); }
  };
  const share = async (mode: "body" | "link") => {
    setBusy(true); setError("");
    key.current ??= crypto.randomUUID();
    try {
      const next = await api<ThreadView>(agentSharePath(scope, threadId, card.request_id), { mode, acknowledged: mode === "body" && acknowledged, request_key: key.current });
      key.current = null; setSharing(null); setReply(null); onView(next);
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  };
  const modes = reply?.share_modes ?? [];
  return <div className={styles.agentCard} data-tone={cardTone(card)} aria-label="小Pai 运行">
    <div className={styles.agentCardHead}>
      <Sparkle size={13} weight="fill" aria-hidden="true"/>
      <span className={styles.agentState} data-tone={cardTone(card)}>{card.label}</span>
      <span className={styles.meta}>{card.own ? "你发起的小Pai 运行" : `${card.requester_name} 发起`}{card.private_only ? " · 只给发起人看" : ""}</span>
      <span className={styles.agentActions}>
        {canRead && !reply && <button type="button" disabled={busy} onClick={() => void open()}>{card.own ? "查看回复" : "打开回复"}</button>}
        {card.own && card.run_id && onOpenRun && <button type="button" onClick={() => onOpenRun(card.run_id!)}>{card.state === "waiting_input" ? "去回答" : "在小Pai 中打开"}</button>}
      </span>
    </div>
    {note && <p className={styles.agentNote}>{note}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {reply && <div className={styles.agentReply}>
      <p className={styles.body}>{reply.body}</p>
      {card.own && reply.can_share && <div className={styles.agentShare}>
        {sharing === "body" ? <>
          <p className={styles.agentWarning}>{reply.body_warning}</p>
          <label className={styles.agentOption}><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)}/>我已了解，分享正文和链接</label>
          <div className={styles.row}>
            <Button size="xs" disabled={busy || !acknowledged} onClick={() => void share("body")}>确认分享正文</Button>
            <Button size="xs" variant="ghost" onClick={() => { setSharing(null); setAcknowledged(false); }}>取消</Button>
          </div>
        </> : <div className={styles.row}>
          <Button size="xs" variant="outline" disabled={busy} onClick={() => void share("link")}>分享链接</Button>
          {modes.includes("body") && <Button size="xs" variant="ghost" disabled={busy} onClick={() => setSharing("body")}>分享正文…</Button>}
          <span className={styles.meta}>{reply.customer_derived ? "读取过客户私有资料，只能分享链接；成员打开时按各自权限核对。" : "分享链接时，成员打开前按各自权限核对全部来源。"}</span>
        </div>}
      </div>}
      <Button size="xs" variant="ghost" onClick={() => setReply(null)}>收起</Button>
    </div>}
  </div>;
}

/** One discussion thread: messages, edit/retract for the author, follow, @小Pai runs, and the composer. */
export function DiscussionThread({ api, scope, target, title, live = true, onChanged, onOpenRun }: Props) {
  const scoped = api;
  const [view, setView] = useState<ThreadView | null>(null), [error, setError] = useState(""), [editing, setEditing] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null), [mode, setMode] = useState<LiveMode>("connecting"), [busy, setBusy] = useState(false);
  const generation = useRef(0), keys = useRef(new Map<string, string>()), token = useRef<string | undefined>(undefined);
  const path = target.kind === "thread" ? threadPath(scope, target.threadId) : commentsPath(scope, target.subjectType, target.subjectId);
  const load = useCallback(async () => {
    const mine = ++generation.current;
    try { const value = await scoped<ThreadView>(path); if (mine === generation.current) { setView(value); setError(""); } }
    catch (failure) { if (mine === generation.current) setError(failure instanceof Error ? failure.message : "讨论暂不可读。"); }
  }, [scoped, path]);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  useEffect(() => { token.current = view?.thread?.token; }, [view]);
  const threadId = view?.thread?.id ?? null;
  useEffect(() => {
    if (!live || !threadId || typeof window === "undefined" || typeof EventSource === "undefined") return;
    const delivery = liveDelivery({
      threads: () => [threadId], onMode: setMode, onChange: state => { if (state.threads[threadId] !== token.current) void load(); },
      open: url => new EventSource(url) as never, poll: value => api(value),
    });
    return () => delivery.stop();
  }, [live, threadId, api, load]);
  // A run's own progress does not move the thread; read again while a card can still change.
  const running = !!view?.messages.some(message => cardInProgress(message.agent_request));
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => void load(), AGENT_POLL_MS);
    return () => clearTimeout(timer);
  }, [running, view, load]);
  const keyFor = (purpose: string) => { const existing = keys.current.get(purpose); if (existing) return existing; const value = crypto.randomUUID(); keys.current.set(purpose, value); return value; };
  const post = async (body: string, options: SubmitOptions) => {
    const purpose = `post:${options.agentPrivate}:${body}`;
    const request = { body, request_key: keyFor(purpose), ...(options.agentPrivate ? { agent_private: true } : {}) };
    const next = target.kind === "thread" ? await scoped<ThreadView>(`${threadPath(scope, target.threadId)}/messages`, request) : await scoped<ThreadView>(commentsPath(scope, target.subjectType, target.subjectId), request);
    keys.current.delete(purpose); setView(next); onChanged?.();
  };
  const revise = async (message: DiscussionMessage, action: "edit" | "retract", body?: string) => {
    if (!threadId) return;
    const purpose = `${action}:${message.id}:${message.revision}:${body ?? ""}`;
    setBusy(true);
    try {
      const next = await scoped<ThreadView>(messagePath(scope, threadId, message.id, action), { ...(body !== undefined ? { body } : {}), expected_revision: message.revision, request_key: keyFor(purpose) });
      keys.current.delete(purpose); setView(next); setEditing(null); setConfirming(null); setError(""); onChanged?.();
    } catch (failure) { setError(errorText(failure)); if ((failure as { status?: number }).status === 409) void load(); } finally { setBusy(false); }
  };
  const follow = async () => {
    if (!view?.thread) return;
    setBusy(true);
    try { const result = await scoped<{ following: boolean }>(`${threadPath(scope, view.thread.id)}/follow`, { followed: !view.thread.following }); setView({ ...view, thread: { ...view.thread, following: result.following } }); }
    catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  };
  if (!view) return <div className={styles.thread}>{error ? <p role="alert" className={styles.error}>{error}</p> : <p className={styles.empty}>正在读取讨论…</p>}</div>;
  const subjectType = view.subject?.type ?? "project", subjectId = view.subject?.id;
  const retractTools = (message: DiscussionMessage) => confirming === message.id
    ? <><button type="button" disabled={busy} onClick={() => void revise(message, "retract")}>确认撤回</button><button type="button" onClick={() => setConfirming(null)}>取消</button></>
    : <button type="button" onClick={() => setConfirming(message.id)}>撤回</button>;
  return <section className={styles.thread} aria-label={title ?? view.thread?.title ?? "评论"}>
    <header className={styles.head}>
      <h3>{title ?? view.thread?.title ?? `${view.subject?.type_label ?? "对象"}评论`}</h3>
      {live && view.thread && <small className={styles.live} data-mode={mode}>{mode === "live" ? "实时" : mode === "polling" ? "每 30 秒刷新" : "连接中"}</small>}
      {view.thread && view.full_project && <Button size="xs" variant="ghost" disabled={busy} onClick={() => void follow()}>{view.thread.following ? "已关注" : "关注"}</Button>}
    </header>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {view.messages.length === 0 ? <p className={styles.empty}>还没有评论。</p> : <ol className={styles.messages}>
      {view.messages.map(message => {
        const fromAgent = message.author_kind === "agent";
        return <li key={message.id} className={styles.message} data-own={message.own} data-agent={fromAgent || undefined}>
          <header>
            {fromAgent && <Sparkle size={13} weight="fill" className={styles.agentMark} aria-hidden="true"/>}
            <strong>{message.author_name}</strong>
            {fromAgent && message.agent && <span className={styles.agentBy}>应 {message.agent.requested_by} 请求{message.agent.kind === "share" ? (message.agent.share_mode === "link" ? " · 发起人分享的链接" : " · 发起人分享") : ""}</span>}
            <time className={styles.meta} dateTime={message.created_at}>{new Date(message.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time>
            {message.edited && <span className={styles.meta}>已编辑</span>}
            {anchorLabel(message, view.subject) && <span className={styles.anchor}>{anchorLabel(message, view.subject)}</span>}
            {message.can_edit && editing !== message.id && <span className={styles.tools}>
              <button type="button" onClick={() => { setEditing(message.id); setConfirming(null); }}>编辑</button>
              {retractTools(message)}
            </span>}
            {fromAgent && message.can_retract && <span className={styles.tools}>{retractTools(message)}</span>}
          </header>
          {editing === message.id ? <Composer api={api} scope={scope} subjectType={subjectType} subjectId={subjectId} placeholder="编辑消息" submitLabel="保存修改" initial={message.body} allowAgent={false} onSubmit={body => revise(message, "edit", body)}/> : <MessageBody message={message} people={view.people}/>}
          {editing === message.id && <div className={styles.row}><Button size="xs" variant="ghost" onClick={() => setEditing(null)}>取消编辑</Button></div>}
          {message.agent_request && threadId && <AgentRunCard api={api} scope={scope} threadId={threadId} card={message.agent_request} onOpenRun={onOpenRun} onView={next => { setView(next); onChanged?.(); }}/>}
        </li>;
      })}
    </ol>}
    {view.can_post && <Composer api={api} scope={scope} subjectType={subjectType} subjectId={subjectId} placeholder={view.thread ? "回复…" : "写评论…"} allowAgent={view.full_project} onSubmit={post}/>}
    <p className={styles.note}>{view.note}</p>
  </section>;
}

/** Comments under one object (task or document), shown in its detail view. */
export function ObjectComments({ api, scope, subjectType, subjectId, onOpenRun }: { api: Api; scope: DiscussionScope; subjectType: "work_task" | "artifact"; subjectId: string; onOpenRun?: (runId: string) => void }) {
  return <div className={styles.comments}><DiscussionThread api={api} scope={scope} target={{ kind: "object", subjectType, subjectId }} title={subjectType === "work_task" ? "任务评论" : "文档评论"} onOpenRun={onOpenRun}/></div>;
}
