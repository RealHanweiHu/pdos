/**
 * Personal notifications (P34 §8), 稍后提醒 (D73) and live delivery (D74).
 * The server decides who is told about what; the page only shows and asks.
 */

export type NotificationCategory = "mention" | "assigned" | "decide" | "agent" | "follow";
export type NotificationView = "inbox" | "snoozed" | "archived" | "digest";
export type NotificationItem = {
  id: string; category: NotificationCategory; category_label: string; reason: string; reason_label: string;
  subject_kind: "thread" | "work_task" | "project" | "member_handover"; subject_id: string; thread_id: string | null;
  project: { id: string; name: string; category_id: string; product_id: string | null };
  actors: string[]; event_count: number; first_at: string; last_at: string; read: boolean;
  snoozed_until: string | null; archived: boolean; delivery: "instant" | "digest"; change_seq: number;
  title: string; snippet: string | null;
  target: null | { view: string; thread_id?: string; subject_type?: string; subject_id?: string; message_id?: string | null };
};
export type NotificationPage = { items: NotificationItem[]; next_before: number | null; unread: Record<NotificationCategory, number>; cursor: string; merge_window_minutes: number };
export type NotificationPreference = { project_id: string; project_name: string; level: "all" | "important" | "mentions"; muted: boolean; digest: boolean; revision: number; levels: Record<string, string>; mute_scope: string };
export type HandoverEntry = {
  project: { id: string; category_id: string; product_id: string; name: string; owner_id: string; owner_name: string; left_at: string | null; product_revision: number };
  items: { kind: string; kind_label: string; subject_id: string; task_id: string | null; label: string; state: string }[];
  counts: { tasks: number; commitments: number; external_waits: number };
  tasks: { id: string; task_id: string; version_id: string; revision: number; state: string; title: string; goal: string; outcomes: { key: string; text: string; required: boolean }[]; sources?: unknown[]; recipient_id: string | null }[];
};
export type HandoverView = { items: HandoverEntry[]; scope_note: string };

export const categories: { id: NotificationCategory | "all"; label: string }[] = [
  { id: "all", label: "全部" }, { id: "mention", label: "提及我" }, { id: "assigned", label: "分派给我" },
  { id: "decide", label: "要我确认或决定" }, { id: "follow", label: "关注的变化" },
];
export const views: { id: NotificationView; label: string }[] = [
  { id: "inbox", label: "收件" }, { id: "snoozed", label: "稍后提醒" }, { id: "digest", label: "每日摘要" }, { id: "archived", label: "已归档" },
];

export function notificationsPath(view: NotificationView, category: NotificationCategory | "all", before?: number | null) {
  const query = new URLSearchParams();
  if (view !== "inbox") query.set("view", view);
  if (category !== "all") query.set("category", category);
  if (before) query.set("before", String(before));
  const text = query.toString();
  return `v1/personal/notifications${text ? `?${text}` : ""}`;
}

export function unreadTotal(page: Pick<NotificationPage, "unread"> | null) {
  if (!page) return 0;
  return Object.values(page.unread).reduce((sum, value) => sum + value, 0);
}

/** "许晴 等 2 人 发表了评论 · 3 条" — merged repeats read as one line (P41-9). */
export function headline(item: NotificationItem) {
  const who = item.actors.length === 0 ? "有人" : item.actors.length === 1 ? item.actors[0] : `${item.actors[0]} 等 ${item.actors.length} 人`;
  return `${who} ${item.reason_label}${item.event_count > 1 ? ` · ${item.event_count} 条` : ""}`;
}

/** D73 presets, computed in the reader's local time and sent with its offset. */
export function snoozeOptions(now: Date) {
  const at = (date: Date) => date.toISOString();
  const hour = new Date(now.getTime() + 60 * 60 * 1000);
  const afternoon = new Date(now); afternoon.setHours(15, 0, 0, 0);
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1); tomorrow.setHours(9, 0, 0, 0);
  const monday = new Date(now); monday.setDate(now.getDate() + ((8 - now.getDay()) % 7 || 7)); monday.setHours(9, 0, 0, 0);
  const options = [{ id: "hour", label: "1 小时后", until: at(hour) }];
  if (afternoon.getTime() - now.getTime() > 30 * 60 * 1000) options.push({ id: "afternoon", label: "今天 15:00", until: at(afternoon) });
  options.push({ id: "tomorrow", label: "明天 9:00", until: at(tomorrow) }, { id: "monday", label: "下周一 9:00", until: at(monday) });
  return options;
}

export function relativeTime(value: string, now: Date) {
  const minutes = Math.round((now.getTime() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} 小时前`;
  return new Date(value).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

// Live delivery ------------------------------------------------------------------

export type LiveMode = "connecting" | "live" | "polling";
type EventSourceLike = { addEventListener(type: string, listener: (event: { data: string; lastEventId?: string }) => void): void; close(): void; onerror: ((event: unknown) => void) | null };
type Timers = { setInterval(fn: () => void, ms: number): unknown; clearInterval(id: unknown): void; setTimeout(fn: () => void, ms: number): unknown; clearTimeout(id: unknown): void };
export type LiveOptions = {
  threads: () => string[];
  onChange: (state: { cursor: string; threads: Record<string, string> }) => void;
  onMode: (mode: LiveMode) => void;
  open: (url: string) => EventSourceLike;
  poll: (path: string) => Promise<{ cursor: string; threads: Record<string, string>; changed: boolean }>;
  timers?: Timers;
};
export const POLL_MS = 30000;

/**
 * One SSE stream per page; when it drops, poll every 30 s and retry the stream
 * on the same beat. On reconnect the stream reports the gap and the page refetches.
 */
export function liveDelivery(options: LiveOptions) {
  const timers: Timers = options.timers ?? { setInterval: (fn, ms) => setInterval(fn, ms), clearInterval: id => clearInterval(id as ReturnType<typeof setInterval>), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: id => clearTimeout(id as ReturnType<typeof setTimeout>) };
  let source: EventSourceLike | null = null, poller: unknown = null, retry: unknown = null, stopped = false, cursor = "", threads: Record<string, string> = {}, polling = false;
  const query = (extra: Record<string, string> = {}) => {
    const value = new URLSearchParams(extra);
    const ids = options.threads().slice(0, 20);
    if (ids.length) value.set("threads", ids.join(","));
    return value.toString();
  };
  const seen = (state: { cursor: string; threads: Record<string, string> }, initial = false) => {
    const changed = state.cursor !== cursor || JSON.stringify(state.threads) !== JSON.stringify(threads);
    cursor = state.cursor; threads = state.threads;
    if (changed && !initial) options.onChange(state);
  };
  const stopPolling = () => { if (poller !== null) timers.clearInterval(poller); poller = null; };
  const pollOnce = async () => {
    if (polling || stopped) return;
    polling = true;
    try { seen(await options.poll(`v1/personal/notifications/changes?${query(cursor ? { since: cursor } : {})}`)); } catch { /* keep the last state; next beat retries */ } finally { polling = false; }
  };
  const fallBack = () => {
    if (stopped) return;
    source?.close(); source = null;
    options.onMode("polling");
    if (poller === null) { poller = timers.setInterval(() => { void pollOnce(); connect(); }, POLL_MS); void pollOnce(); }
  };
  const connect = () => {
    if (stopped || source) return;
    const url = `/api/v1/personal/notifications/stream?${query(cursor ? { since: cursor } : {})}`;
    let opened: EventSourceLike;
    try { opened = options.open(url); } catch { fallBack(); return; }
    source = opened;
    const parse = (data: string) => { try { return JSON.parse(data) as { cursor: string; threads: Record<string, string> }; } catch { return null; } };
    opened.addEventListener("ready", event => { const state = parse(event.data); stopPolling(); options.onMode("live"); if (state) seen(state, cursor === ""); });
    opened.addEventListener("changed", event => { const state = parse(event.data); if (state) seen(state); });
    opened.addEventListener("reconnect", () => { opened.close(); if (source === opened) source = null; retry = timers.setTimeout(connect, 0); });
    opened.addEventListener("closed", () => { opened.close(); if (source === opened) source = null; fallBack(); });
    opened.onerror = () => { if (source === opened) fallBack(); };
  };
  options.onMode("connecting");
  connect();
  return {
    stop() { stopped = true; source?.close(); source = null; stopPolling(); if (retry !== null) timers.clearTimeout(retry); },
    /** Threads on screen changed: reopen so the stream also watches them. */
    refresh() { if (stopped) return; if (source) { source.close(); source = null; connect(); } else void pollOnce(); },
    get cursor() { return cursor; },
  };
}
