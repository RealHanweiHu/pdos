"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import {
  activeQuery, anchorLabel, commentsPath, insertMention, mentionablePath, mentionChoices, mentionError,
  messagePath, segments, threadPath, type DiscussionMessage, type DiscussionScope, type Mentionable, type ThreadView,
} from "@/lib/discussions";
import { liveDelivery, type LiveMode } from "@/lib/notifications";
import styles from "./discussion.module.css";

type Api = typeof browserApi;
export type ThreadTarget = { kind: "thread"; threadId: string } | { kind: "object"; subjectType: "work_task" | "artifact"; subjectId: string };
type Props = { api: Api; scope: DiscussionScope; target: ThreadTarget; title?: string; live?: boolean; onChanged?: () => void };

function errorText(failure: unknown) {
  return mentionError(failure) ?? (failure instanceof Error ? failure.message : "暂未保存，请重试。");
}

export function MessageBody({ message, people }: { message: DiscussionMessage; people: Record<string, string> }) {
  if (message.retracted) return <p className={styles.retracted}>{message.placeholder ?? "已撤回"}</p>;
  return <p className={styles.body}>{segments(message.body, people).map((part, index) => part.kind === "text" ? <span key={index}>{part.text}</span> : <span key={index} className={styles.chip} data-kind={part.mention}>@{part.label}</span>)}</p>;
}

export function Composer({ api, scope, subjectType, subjectId, placeholder, submitLabel = "发送", onSubmit, disabled, initial = "" }: {
  api: Api; scope: DiscussionScope; subjectType: string; subjectId?: string; placeholder: string; submitLabel?: string;
  onSubmit: (body: string) => Promise<void>; disabled?: boolean; initial?: string;
}) {
  const scoped = api;
  const [text, setText] = useState(initial), [caret, setCaret] = useState(initial.length), [options, setOptions] = useState<Mentionable | null>(null);
  const [selected, setSelected] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState(""), [dismissed, setDismissed] = useState(-1);
  const area = useRef<HTMLTextAreaElement>(null), loading = useRef(false);
  const found = activeQuery(text, caret), query = found && found.start !== dismissed ? found : null;
  const choices = query ? mentionChoices(options, query.query) : [];
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
    try { await onSubmit(text.trim()); setText(""); setCaret(0); } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  };
  return <div className={styles.composer}>
    {query && choices.length > 0 && <ul className={styles.picker} role="listbox" aria-label="选择要提及的人">
      {choices.map((choice, index) => <li key={choice.key} role="option" aria-selected={index === selected} aria-disabled={choice.disabled} title={choice.reason} onMouseDown={event => { event.preventDefault(); pick(index); }}>
        <span>@{choice.label}</span><small>{choice.detail}{choice.reason ? ` · ${choice.reason}` : ""}</small>
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
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <div className={styles.composerFoot}><span>输入 @ 提及能看到此处的成员；提及只通知，不授予访问权、不构成分派。</span><Button size="sm" disabled={disabled || busy || !text.trim()} onClick={() => void submit()}>{busy ? "发送中…" : submitLabel}</Button></div>
  </div>;
}

/** One discussion thread: messages, edit/retract for the author, follow, and the composer. */
export function DiscussionThread({ api, scope, target, title, live = true, onChanged }: Props) {
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
  const keyFor = (purpose: string) => { const existing = keys.current.get(purpose); if (existing) return existing; const value = crypto.randomUUID(); keys.current.set(purpose, value); return value; };
  const post = async (body: string) => {
    const purpose = `post:${body}`;
    const request = { body, request_key: keyFor(purpose) };
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
  return <section className={styles.thread} aria-label={title ?? view.thread?.title ?? "评论"}>
    <header className={styles.head}>
      <h3>{title ?? view.thread?.title ?? `${view.subject?.type_label ?? "对象"}评论`}</h3>
      {live && view.thread && <small className={styles.live} data-mode={mode}>{mode === "live" ? "实时" : mode === "polling" ? "每 30 秒刷新" : "连接中"}</small>}
      {view.thread && view.full_project && <Button size="xs" variant="ghost" disabled={busy} onClick={() => void follow()}>{view.thread.following ? "已关注" : "关注"}</Button>}
    </header>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {view.messages.length === 0 ? <p className={styles.empty}>还没有评论。</p> : <ol className={styles.messages}>
      {view.messages.map(message => <li key={message.id} className={styles.message} data-own={message.own}>
        <header>
          <strong>{message.author_name}</strong>
          <time className={styles.meta} dateTime={message.created_at}>{new Date(message.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time>
          {message.edited && <span className={styles.meta}>已编辑</span>}
          {anchorLabel(message, view.subject) && <span className={styles.anchor}>{anchorLabel(message, view.subject)}</span>}
          {message.can_edit && editing !== message.id && <span className={styles.tools}>
            <button type="button" onClick={() => { setEditing(message.id); setConfirming(null); }}>编辑</button>
            {confirming === message.id ? <><button type="button" disabled={busy} onClick={() => void revise(message, "retract")}>确认撤回</button><button type="button" onClick={() => setConfirming(null)}>取消</button></> : <button type="button" onClick={() => setConfirming(message.id)}>撤回</button>}
          </span>}
        </header>
        {editing === message.id ? <Composer api={api} scope={scope} subjectType={subjectType} subjectId={subjectId} placeholder="编辑消息" submitLabel="保存修改" initial={message.body} onSubmit={body => revise(message, "edit", body)}/> : <MessageBody message={message} people={view.people}/>}
        {editing === message.id && <div className={styles.row}><Button size="xs" variant="ghost" onClick={() => setEditing(null)}>取消编辑</Button></div>}
      </li>)}
    </ol>}
    {view.can_post && <Composer api={api} scope={scope} subjectType={subjectType} subjectId={subjectId} placeholder={view.thread ? "回复…" : "写评论…"} onSubmit={post}/>}
    <p className={styles.note}>{view.note}</p>
  </section>;
}

/** Comments under one object (task or document), shown in its detail view. */
export function ObjectComments({ api, scope, subjectType, subjectId }: { api: Api; scope: DiscussionScope; subjectType: "work_task" | "artifact"; subjectId: string }) {
  return <div className={styles.comments}><DiscussionThread api={api} scope={scope} target={{ kind: "object", subjectType, subjectId }} title={subjectType === "work_task" ? "任务评论" : "文档评论"}/></div>;
}
