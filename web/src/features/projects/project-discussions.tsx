"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatsCircle, Plus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import { mentionError, segments, topicsPath, type DiscussionScope, type ThreadView, type TopicList } from "@/lib/discussions";
import type { NotificationPreference } from "@/lib/notifications";
import { Composer, DiscussionThread } from "./discussion-thread";
import styles from "./discussion.module.css";

type Api = typeof browserApi;
type Props = { api: Api; categoryId: string; productId: string; projectId: string; principalId: string; readVersion?: number; initialThread?: string | null };

function preview(text: string) {
  return segments(text).map(part => part.kind === "text" ? part.text : `@${part.label}`).join("").slice(0, 80);
}

function NotificationSettings({ api, projectId }: { api: Api; projectId: string }) {
  const [value, setValue] = useState<NotificationPreference | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api<NotificationPreference>(`v1/personal/notification-preferences/${projectId}`).then(next => { if (alive) setValue(next); }).catch(failure => { if (alive) setError(failure.message); });
    return () => { alive = false; };
  }, [api, projectId]);
  const save = async (change: Partial<Pick<NotificationPreference, "level" | "muted" | "digest">>) => {
    if (!value) return;
    setBusy(true);
    try { setValue(await api<NotificationPreference>("v1/personal/notification-preferences", { project_id: projectId, level: change.level ?? value.level, muted: change.muted ?? value.muted, digest: change.digest ?? value.digest, expected_revision: value.revision })); setError(""); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "设置未保存。"); }
    finally { setBusy(false); }
  };
  return <details className={styles.settings}><summary>本项目的通知设置</summary>{value ? <div>
    <label>级别<select value={value.level} disabled={busy} onChange={event => void save({ level: event.target.value as NotificationPreference["level"] })}>{Object.entries(value.levels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
    <label><input type="checkbox" checked={value.muted} disabled={busy} onChange={event => void save({ muted: event.target.checked })}/>静音（只挡关注的变化和摘要）</label>
    <label><input type="checkbox" checked={value.digest} disabled={busy} onChange={event => void save({ digest: event.target.checked })}/>关注的变化改为每日摘要</label>
  </div> : <div>{error || "正在读取…"}</div>}{error && value && <p role="alert" className={styles.error}>{error}</p>}</details>;
}

/** 动态与讨论 (§5.1 item 7): project topics; every read and write is re-checked by the server. */
export function ProjectDiscussions({ api, categoryId, productId, projectId, principalId, readVersion = 0, initialThread = null }: Props) {
  const scope = useMemo<DiscussionScope>(() => ({ categoryId, productId, projectId }), [categoryId, productId, projectId]);
  const scoped = api;
  const [list, setList] = useState<TopicList | null>(null), [error, setError] = useState(""), [selected, setSelected] = useState<string | null>(initialThread);
  const [creating, setCreating] = useState(false), [title, setTitle] = useState(""), key = useRef<string | null>(null);
  const load = useCallback(async () => {
    try { setList(await scoped<TopicList>(topicsPath(scope))); setError(""); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "项目讨论暂不可读。"); }
  }, [scoped, scope]);
  useEffect(() => { void Promise.resolve().then(load); }, [load, readVersion, principalId]);
  const start = async (body: string) => {
    if (!title.trim()) throw new Error("请输入讨论标题。");
    key.current ??= crypto.randomUUID();
    try {
      const created = await scoped<ThreadView>(topicsPath(scope), { title: title.trim(), body, request_key: key.current });
      key.current = null; setTitle(""); setCreating(false); setSelected(created.thread?.id ?? null); void load();
    } catch (failure) { const text = mentionError(failure); throw text ? new Error(text) : failure; }
  };
  return <section aria-label="项目讨论">
    <div className={styles.head}><h3><ChatsCircle size={14} aria-hidden="true"/> 项目讨论</h3><Button size="xs" variant="ghost" onClick={() => setCreating(value => !value)}><Plus size={12}/>发起讨论</Button></div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {creating && <div className={styles.newTopic}>
      <input aria-label="讨论标题" placeholder="讨论标题" maxLength={160} value={title} onChange={event => setTitle(event.target.value)}/>
      <Composer api={api} scope={scope} subjectType="project" placeholder="第一条内容，可用 @ 提及成员" submitLabel="发起" onSubmit={start}/>
    </div>}
    {list && (list.items.length === 0 ? <p className={styles.empty}>还没有项目讨论。结论需要成为正式记录时，请转为任务或决定草稿。</p> : <ul className={styles.topics}>
      {list.items.map(item => <li key={item.id}><button type="button" className={styles.topic} aria-current={selected === item.id} onClick={() => setSelected(value => value === item.id ? null : item.id)}>
        <div><p>{item.title}</p><small>{item.latest ? `${item.latest.author_name}：${item.latest.retracted ? "已撤回" : preview(item.latest.body)}` : item.author_name} · {item.messages} 条{item.following ? " · 已关注" : ""}</small></div>
      </button></li>)}
    </ul>)}
    {selected && <div style={{ marginTop: 10 }}><DiscussionThread key={selected} api={api} scope={scope} target={{ kind: "thread", threadId: selected }} onChanged={() => void load()}/></div>}
    <NotificationSettings api={api} projectId={projectId}/>
  </section>;
}
