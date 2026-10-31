"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { WorkspaceApi } from "@/lib/automation-rules";
import { visibleInbox, type InboxState } from "@/lib/inbox";
import { parseSummaryFeed, type SummaryFeedItem } from "@/lib/personal-summary";
import { SummaryRunReader } from "./pai/personal-summary-result";

type Props = { api: WorkspaceApi; principalId: string; states?: InboxState[]; query?: string; filter?: "all" | "unread" | "archived" | "followed"; disabled?: boolean; onChange?: (id: string, token: string, action: "read" | "archive") => void };
export function PersonalSummaryInbox(props: Props) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <ScopedSummaryInbox key={`${props.principalId}:${binding.revision}`} {...props}/>;
}
function ScopedSummaryInbox({ api, principalId, states = [], query = "", filter = "all", disabled = false, onChange }: Props) {
  const [items, setItems] = useState<SummaryFeedItem[]>([]), [cursor, setCursor] = useState<string | null>(null), [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false), [loaded, setLoaded] = useState(false), [error, setError] = useState("");
  const epoch = useRef(0), live = useRef(true), seen = useRef(new Set<string>());
  async function read(after: string | null = null) { if (busy) return; const stamp = ++epoch.current; setBusy(true); setError(""); if (!after) { setSelected(""); setItems([]); seen.current.clear(); } try { const value = parseSummaryFeed(await api<unknown>(`v1/personal/inbox/summaries?page_size=25${after ? `&cursor=${encodeURIComponent(after)}` : ""}`), principalId); if (!live.current || stamp !== epoch.current) return; if (value.next_cursor && (value.next_cursor === after || seen.current.has(value.next_cursor))) throw new Error("摘要列表位置未推进，请刷新。"); if (value.next_cursor) seen.current.add(value.next_cursor); setItems(previous => after ? [...new Map([...previous, ...value.items].map(i => [i.run_id, i])).values()] : value.items); setCursor(value.next_cursor); setLoaded(true); } catch (e) { if (live.current && stamp === epoch.current) { setSelected(""); if ([401, 403].includes(Number((e as { status?: number })?.status))) { setItems([]); setCursor(null); } setError(e instanceof Error ? e.message : "摘要列表读取失败。"); } } finally { if (live.current && stamp === epoch.current) setBusy(false); } }
  useEffect(() => { live.current = true; void Promise.resolve().then(() => { if (live.current) void read(); }); return () => { live.current = false; ++epoch.current; }; }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const state = (id: string) => states.find(s => s.kind === "run" && s.target_id === id);
  const rows = items.filter(i => `${i.title} ${i.category_name}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()) && visibleInbox(state(i.run_id), i.reading_token, filter));
  const chosen = rows.find(i => i.run_id === selected);
  return <section className="min-w-0 space-y-4" aria-label="本人摘要收件列表"><header className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold">我的定时摘要</h2><p className="mt-1 text-sm text-muted-foreground">来自本人已启用规则的实际完成记录。打开正文时重新核对来源读取权限。</p></div><Button size="sm" variant="outline" disabled={busy} onClick={() => void read()}><ArrowClockwise aria-hidden="true"/>刷新摘要</Button></header>{error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
    <ul className="space-y-2">{rows.map(row => <li key={row.run_id} className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-border p-3"><button type="button" className="min-w-0 flex-1 text-left text-sm focus-visible:outline-2 focus-visible:outline-primary" aria-pressed={selected === row.run_id} onClick={() => setSelected(row.run_id)}><strong className="block break-words">{row.title}{state(row.run_id)?.read_through !== row.reading_token && <span className="ml-2 text-xs font-normal text-primary">未读</span>}</strong><span className="mt-1 block text-muted-foreground">{row.category_name} · {row.status === "partial" ? "部分摘要已生成" : "摘要已生成"}</span><time className="text-xs text-muted-foreground" dateTime={row.as_of}>{new Date(row.as_of).toLocaleString("zh-CN")}</time></button>{onChange && <Button type="button" size="xs" variant="ghost" disabled={disabled} onClick={() => onChange(row.run_id, row.reading_token, "archive")}>{state(row.run_id)?.archived ? "移回收件箱" : "归档摘要"}</Button>}</li>)}</ul>
    {!rows.length && <p className="text-sm text-muted-foreground">{busy ? "正在读取本人摘要…" : loaded ? "当前筛选下暂无已生成摘要。" : "摘要列表尚未取得。"}</p>}{cursor && <Button size="sm" variant="outline" disabled={busy} onClick={() => void read(cursor)}>读取后续摘要</Button>}
    {chosen && <div className="rounded-lg border border-border p-3 sm:p-4"><SummaryRunReader key={`${principalId}:${chosen.run_id}`} api={api} principalId={principalId} categoryId={chosen.category_id} runId={chosen.run_id} onRead={() => { if (onChange && state(chosen.run_id)?.read_through !== chosen.reading_token) onChange(chosen.run_id, chosen.reading_token, "read"); }}/></div>}
  </section>;
}
