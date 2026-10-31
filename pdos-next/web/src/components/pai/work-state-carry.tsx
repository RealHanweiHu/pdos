"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Folder, ArrowClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import styles from "../pai-conversation.module.css";
import { SearchScope } from "./search-scope";
import type { SearchPreferences } from "@/lib/search-preferences";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type State = {
  version: "agent-work-state/v1"; session_id: string | null; revision: number;
  root_goal: { text: string } | null; current_goal: { text: string } | null;
  constraints: { id: string; text: string }[];
  exclusions: { id: string; reason: string }[];
  focus_objects: { id: string; kind: string; version: number | null; note?: string; title?: string }[];
  citations?: { citation_id: string; title: string; source_revision: number; currentness: string }[];
  citation_directory?: { has_more: boolean };
  candidates?: { event_id: string; run_id: string; kind: string; operation: string | null;
    state: "pending" | "adopted" | "cancelled" | "unavailable"; receipt_id: string | null }[];
  completed_count: number; unfinished: string[]; notes: string[];
  context_incomplete: boolean; missing: string[];
  context_selection?: import("@/lib/explicit-context-corrections").ContextSelection;
  search_preferences?: SearchPreferences;
  search_context?: { label: string; kind: string; scoped: boolean };
};
type Change = { expected_revision: number; request_key: string } & ({ action: "remove_constraint" | "remove_exclusion" | "exclude_source"; item_id: string } | { action: "set_search_scope"; search_preferences: SearchPreferences });

/** Opening/refreshing reads only; an explicit delete creates a new server version. */
export function WorkStateCarry({ api, root, sessionId, disabled = false, onUnavailable, background = false, contextControl, onChange, refreshVersion = 0 }: {
  api: Api; root: string; sessionId: string; disabled?: boolean; onUnavailable?: () => void;
  background?: boolean; contextControl?: ReactNode; onChange?: (value: State) => void; refreshVersion?: number | string;
}) {
  const resource = `${root.replace(/agent-runs$/, "agent-sessions")}/${sessionId}/work-state`;
  const [reading, setReading] = useState<{ resource: string; value?: State; error?: string }>({ resource });
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState<Change | null>(null);
  const original = useRef<Change | null>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  const value = reading.resource === resource ? reading.value : undefined;
  useEffect(() => {
    const counter = generation;
    const own = ++counter.current;
    original.current = null; lock.current = false;
    void api<State>(resource).then(value => {
      if (value.version !== "agent-work-state/v1" || value.session_id && value.session_id !== sessionId) throw new Error("本次携带与当前会话不一致。");
      if (own === generation.current) { setReading({ resource, value }); setPending(null); setBusy(false); onChange?.(value); }
    }).catch(failure => {
      if (own === generation.current) setReading({ resource, error: failure instanceof Error ? failure.message : "本次携带暂不可读。" });
    });
    return () => { counter.current++; };
  }, [api, resource, sessionId, refresh, refreshVersion, onChange]);
  async function remove(action: Change["action"], itemId?: string, preferences?: SearchPreferences) {
    if (lock.current || !value) return;
    lock.current = true; setBusy(true);
    const own = generation.current;
    const request: Change = original.current ?? { expected_revision: value.revision, request_key: crypto.randomUUID(), ...(action === "set_search_scope" ? { action, search_preferences: preferences! } : { action, item_id: itemId! }) };
    original.current = request; setPending(request);
    try {
      await api<State>(resource, request);
      if (own !== generation.current) return;
      original.current = null; setPending(null); setRefresh(count => count + 1);
    } catch (failure) {
      if (own !== generation.current) return;
      const status = (failure as { status?: number }).status;
      if (status === 401 || status === 403) {
        original.current = null; setPending(null); setReading({ resource, error: "当前会话已不可读，携带内容已清除。" });
        onUnavailable?.();
      } else if (status === 409 || status === 404 || status === 422) {
        original.current = null; setPending(null); setRefresh(count => count + 1);
        setReading({ resource, error: "携带内容已变化，正在重新读取。" });
      } else setReading({ resource, value, error: "修改结果待核对，请重试原请求或刷新查看。" });
    } finally { lock.current = false; if (own === generation.current) setBusy(false); }
  }
  return <>
    {background && value?.search_context?.scoped && value.search_preferences && <SearchScope label={value.search_context.label} kind={value.search_context.kind} value={value.search_preferences} persisted control={contextControl} disabled={disabled || busy || !!pending} onChange={preferences => void remove("set_search_scope", undefined, preferences)}/>}
    {background && pending?.action === "set_search_scope" && reading.error && <div role="alert" className="text-xs break-words"><p>{reading.error}</p><Button type="button" size="sm" variant="outline" disabled={disabled || busy || !value} onClick={() => void remove("set_search_scope", undefined, pending.search_preferences)}>核对并重试查找范围</Button></div>}
    <details className={styles.carry}>
    <summary aria-label="本次携带" title="本次携带"><Folder size={15} aria-hidden="true"/><span>本次携带</span>{value && value.constraints.length > 0 && <span>{value.constraints.length}</span>}</summary>
    <div className="max-h-[60vh] overflow-y-auto break-words">
      <p>本次携带{value ? ` · 第 ${value.revision} 版` : ""}</p>
      {reading.error && <p role="alert">{reading.error}</p>}
      {!value && !reading.error && <p role="status">正在读取…</p>}
      {value && <>
        {value.context_selection && <div className="space-y-1"><p>资料条件：{value.context_selection.status === "unavailable" ? "选定条件当前不可用，请重新选择或解除" : value.context_selection.version_mode === "current" ? "只看当前有效资料" : value.context_selection.version_mode === "fixed" ? "只看所选版本" : value.context_selection.sources ? "只用所选资料" : "已更换焦点对象"}</p>{value.context_selection.status === "available" && <ul>{[...(value.context_selection.focus ? [value.context_selection.focus] : []), ...value.context_selection.versions, ...(value.context_selection.sources ?? [])].filter((source, index, rows) => rows.findIndex(row => row.source_type === source.source_type && row.source_id === source.source_id && row.source_revision === source.source_revision) === index).map((source, index) => <li key={index}>{source.title} · v{source.source_revision}</li>)}</ul>}</div>}
        {value.root_goal && <p>最初目标：{value.root_goal.text}</p>}
        {value.current_goal && <p>当前目标：{value.current_goal.text}</p>}
        {value.constraints.map(item => <p key={item.id}>约束：{item.text} <Button type="button" size="sm" variant="ghost" disabled={disabled || busy || !!pending} onClick={() => void remove("remove_constraint", item.id)}>移除约束</Button></p>)}
        {value.exclusions.map(item => <p key={item.id}>排除：{item.reason} <Button type="button" size="sm" variant="ghost" disabled={disabled || busy || !!pending} onClick={() => void remove("remove_exclusion", item.id)}>移除排除条件</Button></p>)}
        <p>携带 {value.focus_objects.length} 个焦点对象 · 已完成 {value.completed_count} 项动作</p>
        {(value.candidates ?? []).map((item, index) => <p key={item.event_id}>候选 {index + 1} · {({ domain: "业务草稿", category: "新品类", snapshot: "研究快照", verification_preparation: "复验准备" } as Record<string, string>)[item.kind] ?? "工作候选"} · {({ pending: "待本人确认", adopted: "已采用", cancelled: "已取消", unavailable: "当前不可用" })[item.state] ?? "当前不可用"}{item.state === "adopted" && item.receipt_id && <span> · 回执 {item.receipt_id}</span>}</p>)}
        {value.focus_objects.filter(item => item.kind === "artifact").map((item, index) => <p key={`${item.id}:${item.version}`}>{item.title || `资料 ${index + 1}`} · 第 {item.version} 版 <Button type="button" size="sm" variant="ghost" disabled={disabled || busy || !!pending || value.exclusions.some(excluded => excluded.id === item.id)} onClick={() => void remove("exclude_source", item.id)}>不相关</Button></p>)}
        {(value.citations ?? []).map(item => <p key={item.citation_id}>{item.title} · 第 {item.source_revision} 版{item.currentness === "history" ? " · 历史依据" : ""} <Button type="button" size="sm" variant="ghost" disabled={disabled || busy || !!pending || value.exclusions.some(excluded => excluded.id === item.citation_id)} onClick={() => void remove("exclude_source", item.citation_id)}>不相关</Button></p>)}
        {value.citation_directory?.has_more && <p>更多引用可在对话中继续读取。</p>}
        {value.focus_objects.filter(item => item.note).map(item => <p key={`${item.kind}:${item.id}:${item.version}`}>{item.note}</p>)}
        {value.unfinished.length > 0 && <p>待处理：{value.unfinished.join("；")}</p>}
        {value.notes.map(note => <p key={note}>{note}</p>)}
        {value.context_incomplete && <p role="alert">工作状态超出预算，请移除不再需要的约束后继续。</p>}
      </>}
      {pending && <Button type="button" size="sm" variant="outline" disabled={disabled || busy || !value} onClick={() => void remove(pending.action, "item_id" in pending ? pending.item_id : undefined, "search_preferences" in pending ? pending.search_preferences : undefined)}>核对并重试原请求</Button>}
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => { original.current = null; setPending(null); setRefresh(count => count + 1); }}><ArrowClockwise size={13} aria-hidden="true"/>刷新携带内容</Button>
    </div>
  </details></>;
}
