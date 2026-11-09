"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, ArrowSquareOut, Bell, Check, Clock } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import {
  categories, headline, liveDelivery, notificationsPath, relativeTime, snoozeOptions, views,
  type LiveMode, type NotificationCategory, type NotificationItem, type NotificationPage, type NotificationView,
} from "@/lib/notifications";
import { projectWorkspaceHref } from "@/lib/project-workspace-navigation";
import styles from "./work-notifications.module.css";

type Props = { api: typeof browserApi; onOpenTarget?: (href: string) => void; onUnread?: (count: number) => void };

export function targetHref(item: NotificationItem) {
  const product = item.project.product_id;
  if (!product) return null;
  const view = item.subject_kind === "member_handover" ? "team" : item.target?.view === "tasks" || item.subject_kind === "work_task" ? "tasks" : "now";
  const href = projectWorkspaceHref(item.project.category_id, product, item.project.id, view);
  if (item.subject_kind === "work_task") return `${href}&task=${item.subject_id}`;
  if (item.target?.subject_type === "work_task" && item.target.subject_id) return `${href}&task=${item.target.subject_id}`;
  if (item.subject_kind === "thread" && item.thread_id) return `${href}&thread=${item.thread_id}`;
  return href;
}

/** 提及我 / 分派给我 / 要我确认或决定 / 关注的变化 (§8), live over SSE with a 30 s fallback (D74). */
export function WorkNotifications({ api, onOpenTarget, onUnread }: Props) {
  const [view, setView] = useState<NotificationView>("inbox"), [category, setCategory] = useState<NotificationCategory | "all">("all");
  const [page, setPage] = useState<NotificationPage | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<LiveMode>("connecting"), [snoozing, setSnoozing] = useState<string | null>(null);
  const generation = useRef(0), reloadRef = useRef<() => void>(() => undefined);
  const load = useCallback(async () => {
    const mine = ++generation.current;
    try {
      const value = await api<NotificationPage>(notificationsPath(view, category));
      if (mine !== generation.current) return;
      setPage(value); setError(""); onUnread?.(Object.values(value.unread).reduce((sum, count) => sum + count, 0));
    } catch (failure) { if (mine === generation.current) setError(failure instanceof Error ? failure.message : "通知暂不可读。"); }
  }, [api, view, category, onUnread]);
  useEffect(() => { reloadRef.current = () => void load(); void Promise.resolve().then(load); }, [load]);
  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;
    const delivery = liveDelivery({ threads: () => [], onMode: setMode, onChange: () => reloadRef.current(), open: url => new EventSource(url) as never, poll: path => api(path) });
    return () => delivery.stop();
  }, [api]);
  const change = async (action: string, ids: string[], extra: Record<string, unknown> = {}) => {
    setBusy(true);
    try { await api("v1/personal/notifications/state", { notification_ids: ids, action, ...extra }); setSnoozing(null); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "未保存，请重试。"); }
    finally { setBusy(false); }
  };
  const open = (item: NotificationItem) => {
    const href = targetHref(item);
    if (!item.read) void change("read", [item.id]);
    if (href) { if (onOpenTarget) onOpenTarget(href); else window.location.assign(href); }
  };
  const now = new Date();
  return <section className={styles.page} aria-label="提及与工作通知">
    <div className={styles.tools}>
      <nav className={styles.chips} aria-label="通知分类">{categories.map(item => <button key={item.id} type="button" aria-pressed={category === item.id} onClick={() => setCategory(item.id)}>{item.label}{item.id !== "all" && page?.unread[item.id] ? <span className={styles.count}>{page.unread[item.id]}</span> : null}</button>)}</nav>
      <select aria-label="通知视图" value={view} onChange={event => setView(event.target.value as NotificationView)}>{views.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
      <small className={styles.live} data-mode={mode} title="断线时改为每 30 秒刷新，恢复后补齐遗漏">{mode === "live" ? "实时" : mode === "polling" ? "每 30 秒刷新" : "连接中"}</small>
      {view === "inbox" && <Button size="xs" variant="ghost" disabled={busy} onClick={() => void change("read_all", [], category === "all" ? {} : { category })}><Check/>全部已读</Button>}
    </div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {!page ? <p className={styles.empty}>正在读取通知…</p> : page.items.length === 0 ? <p className={styles.empty}>{view === "snoozed" ? "没有稍后提醒的通知。" : view === "digest" ? "每日摘要里没有未读的关注变化。" : view === "archived" ? "没有已归档的通知。" : "没有新通知。提及、分派和要你确认的事项会出现在这里。"}</p> : <ul className={styles.list}>
      {page.items.map(item => <li key={item.id} className={styles.item} data-unread={!item.read}>
        <button type="button" className={styles.row} onClick={() => open(item)} aria-label={`${item.category_label}：${item.title}`}>
          <span className={styles.dot} aria-hidden="true"/>
          <span className={styles.kind} data-category={item.category}>{item.category === "mention" ? "@" : item.category === "decide" ? "待" : item.category === "assigned" ? "派" : <Bell size={12}/>}</span>
          <span className={styles.text}>
            <span className={styles.title}>{item.title}</span>
            <span className={styles.line}>{headline(item)}</span>
            {item.snippet && <span className={styles.snippet}>{item.snippet}</span>}
            <span className={styles.meta}>{item.project.name} · {item.category_label}{item.snoozed_until && view === "snoozed" ? ` · ${new Date(item.snoozed_until).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} 提醒` : ""}</span>
          </span>
          <time dateTime={item.last_at}>{relativeTime(item.last_at, now)}</time>
        </button>
        <div className={styles.actions}>
          {targetHref(item) && <Button size="icon-xs" variant="ghost" aria-label="打开" title="打开" onClick={() => open(item)}><ArrowSquareOut/></Button>}
          {!item.archived && <Button size="xs" variant="ghost" disabled={busy} onClick={() => void change(item.read ? "unread" : "read", [item.id])}>{item.read ? "标为未读" : "已读"}</Button>}
          {view !== "archived" && (view === "snoozed" ? <Button size="xs" variant="ghost" disabled={busy} onClick={() => void change("unsnooze", [item.id])}>取消提醒</Button> : <span className={styles.snooze}>
            <Button size="icon-xs" variant="ghost" aria-label="稍后提醒" title="稍后提醒" aria-expanded={snoozing === item.id} onClick={() => setSnoozing(value => value === item.id ? null : item.id)}><Clock/></Button>
            {snoozing === item.id && <span className={styles.menu} role="menu">{snoozeOptions(now).map(option => <button key={option.id} type="button" role="menuitem" disabled={busy} onClick={() => void change("snooze", [item.id], { snooze_until: option.until })}>{option.label}</button>)}</span>}
          </span>)}
          <Button size="icon-xs" variant="ghost" aria-label={item.archived ? "恢复" : "归档"} title={item.archived ? "恢复" : "归档"} disabled={busy} onClick={() => void change(item.archived ? "restore" : "archive", [item.id])}><Archive/></Button>
        </div>
      </li>)}
    </ul>}
    <p className={styles.foot}>已读不等于完成。同一对象 {page?.merge_window_minutes ?? 10} 分钟内的变化合并为一条；你自己的操作不会通知你。</p>
  </section>;
}
