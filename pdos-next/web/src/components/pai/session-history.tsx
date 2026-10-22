"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { readSessionRuns } from "@/lib/pai-sessions";
import { readConversations, writePresentation, recoverPresentation } from "@/lib/pai-session-presentation";
import type { PaiConversationList, PaiConversation, PresentationAction, PresentationRequest } from "@/lib/pai-session-presentation";
import type { PaiSessionApi, PaiSessionRuns, PaiSessionScope } from "@/lib/pai-sessions";
import styles from "./session-history.module.css";

type Props = {
  api: PaiSessionApi; scope: { categoryId: string | null; proposalId?: string | null; projectId?: string | null }; principalId?: string;
  currentSessionId?: string | null; currentRunId?: string | null; refreshVersion?: number; disabled?: boolean;
  onSelectRun: (runId: string, sessionId: string) => void; onClearSelection: () => void;
};
const labels: Record<string, string> = { queued: "等待执行", running: "执行中", waiting_input: "待答复", completed: "已完成", partial: "部分结果", failed: "未完成", cancelled: "已取消" };
const friendlyTime = (value: string) => new Date(value).toLocaleString(undefined, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
const message = (failure: unknown) => failure instanceof Error ? failure.message : "会话读取暂不可用。";

/** API identity is part of the read scope, including when a caller changes transport in place. */
export function SessionHistory(props: Props) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <HistoryIdentity key={`${binding.revision}:${props.principalId ?? "resolve"}:${props.scope.categoryId ?? "personal"}:${props.scope.proposalId ?? ""}:${props.scope.projectId ?? ""}`} {...props} />;
}

function HistoryIdentity(props: Props) {
  const { api, principalId: knownPrincipalId, onClearSelection } = props;
  const [who, setWho] = useState<{ principalId?: string; error?: string }>({});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (knownPrincipalId) return;
    let active = true;
    void api<{ principal_id: string }>("v1/session").then(value => {
      if (typeof value.principal_id !== "string") throw new Error("当前身份无法核对。");
      if (active) setWho({ principalId: value.principal_id });
    }).catch(failure => { if (active) { setWho({ error: message(failure) }); onClearSelection(); } });
    return () => { active = false; };
  }, [api, knownPrincipalId, attempt, onClearSelection]);
  const principalId = props.principalId ?? who.principalId;
  if (!principalId) return <div className={styles.history}><p role={who.error ? "alert" : "status"}>{who.error || "正在核对当前身份…"}</p>{who.error && <Button size="sm" variant="ghost" onClick={() => { setWho({}); setAttempt(value => value + 1); }}>重新核对身份</Button>}</div>;
  return <HistoryPages {...props} principalId={principalId} />;
}

function HistoryPages({ api, scope, principalId, currentSessionId, currentRunId, refreshVersion = 0, disabled, onSelectRun, onClearSelection }: Props & { principalId: string }) {
  const [q, setQ] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [view, setView] = useState<"active" | "archived">("active");
  const [editor, setEditor] = useState<{ key: string; item: PaiConversation; title: string } | null>(null);
  const [operation, setOperation] = useState<{ request: PresentationRequest; key: string; state: "sending" | "unknown" | "recovering"; error: string } | null>(null);
  const [operationError, setOperationError] = useState("");
  const operationGeneration = useRef(0);
  const [list, setList] = useState<{ key: string; value: PaiConversationList | null; error: string; loading: boolean }>({ key: "", value: null, error: "", loading: true });
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [runs, setRuns] = useState<{ key: string; value: PaiSessionRuns | null; error: string; loading: boolean }>({ key: "", value: null, error: "", loading: false });
  const generation = useRef(0), runGeneration = useRef(0);
  const readScope: PaiSessionScope = { principalId, categoryId: scope.categoryId, proposalId: scope.proposalId };
  const listKey = JSON.stringify([principalId, scope.categoryId, scope.proposalId ?? null, q, view, refreshVersion, refresh]);
  const listCurrent = list.key === listKey ? list : { value: null, error: "", loading: true };
  const sessionId = list.key === listKey ? selectedSession : null;
  const runKey = `${listKey}:${sessionId ?? ""}`;
  const runsCurrent = runs.key === runKey ? runs : { value: null, error: "", loading: !!sessionId };
  const scopeRef = useRef({ api, listKey });
  useEffect(() => { scopeRef.current = { api, listKey }; });
  const loadList = useCallback(async (cursor?: string) => {
    const own = ++generation.current, key = listKey;
    if (!cursor) { setEditor(null); setSelectedSession(null); runGeneration.current++; setRuns({ key: "", value: null, loading: false, error: "" }); }
    setList(old => ({ key, value: cursor && old.key === key ? old.value : null, loading: true, error: "" }));
    try {
      const page = await readConversations(api, { principalId, categoryId: scope.categoryId, proposalId: scope.proposalId }, { q, cursor, view });
      if (generation.current !== own || scopeRef.current.listKey !== key || scopeRef.current.api !== api) return;
      setList(old => {
        const prior = cursor && old.key === key ? old.value : null;
        if (prior && (prior.next_cursor !== cursor || page.next_cursor === cursor)) return { key, value: null, loading: false, error: "分页位置已变化，请重新读取会话。" };
        return { key, loading: false, error: "", value: prior ? { ...page, items: [...prior.items, ...page.items.filter(item => !prior.items.some(previous => previous.session_id === item.session_id))] } : page };
      });
    } catch (failure) { if (generation.current === own && scopeRef.current.listKey === key) { setList({ key, value: null, loading: false, error: message(failure) }); setSelectedSession(null); setRuns({ key: "", value: null, loading: false, error: "" }); runGeneration.current++; onClearSelection(); } }
  }, [api, principalId, scope.categoryId, scope.proposalId, q, view, listKey, onClearSelection]);
  useEffect(() => {
    let active = true;
    const listCounter = generation, runCounter = runGeneration, operationCounter = operationGeneration;
    void Promise.resolve().then(() => { if (active) return loadList(); });
    return () => { active = false; listCounter.current++; runCounter.current++; operationCounter.current++; };
  }, [loadList]);
  const loadRuns = async (id: string, cursor?: string) => {
    const own = ++runGeneration.current, key = `${listKey}:${id}`;
    setRuns(old => ({ key, value: cursor && old.key === key ? old.value : null, loading: true, error: "" }));
    try {
      const page = await readSessionRuns(api, readScope, id, { cursor });
      if (runGeneration.current !== own || scopeRef.current.listKey !== listKey || scopeRef.current.api !== api) return;
      setRuns(old => {
        const prior = cursor && old.key === key ? old.value : null;
        if (prior && (prior.next_cursor !== cursor || page.next_cursor === cursor)) return { key, value: null, loading: false, error: "分页位置已变化，请重新读取本会话工作。" };
        return { key, loading: false, error: "", value: prior ? { ...page, items: [...prior.items, ...page.items.filter(item => !prior.items.some(previous => previous.run_id === item.run_id))] } : page };
      });
    } catch (failure) { if (runGeneration.current === own && scopeRef.current.listKey === listKey) {
      setRuns({ key, value: null, loading: false, error: message(failure) });
      if ((failure as { status?: number }).status !== 503) {
        setList({ key: listKey, value: null, loading: false, error: `${message(failure)} 请刷新会话以重新核对可读范围。` });
        setSelectedSession(null);
      }
      onClearSelection();
    } }
  };
  function clear() { setEditor(null); runGeneration.current++; setSelectedSession(null); setRuns({ key: "", value: null, loading: false, error: "" }); onClearSelection(); }
  const visibleEditor = editor?.key === listKey ? editor : null;
  const pending = operation && { ...operation, state: operation.key === listKey ? operation.state : "unknown" };
  async function manage(request: PresentationRequest, recovery = false) {
    const own = ++operationGeneration.current, key = listKey;
    setEditor(null); setOperationError("");
    setOperation({ request, key, state: recovery ? "recovering" : "sending", error: "" });
    try {
      if (recovery) await recoverPresentation(api, readScope, request); else await writePresentation(api, readScope, request);
      if (operationGeneration.current !== own || scopeRef.current.listKey !== key || scopeRef.current.api !== api) return;
      setOperation(null); clear(); setRefresh(value => value + 1);
    } catch (failure) {
      if (operationGeneration.current !== own || scopeRef.current.listKey !== key || scopeRef.current.api !== api) return;
      const status = (failure as { status?: number }).status;
      if (recovery || status === undefined || status >= 500) {
        setOperation({ request, key, state: "unknown", error: recovery && status === 404 ? "尚未查到原请求回执；可再次查询或明确重试原请求。" : message(failure) });
        if (status === 401 || status === 403) { clear(); setList({ key, value: null, loading: false, error: "当前会话范围须重新核对。" }); }
      } else {
        setOperation(null); clear(); setRefresh(value => value + 1);
        setOperationError(status === 409 ? "会话已发生变化，已重新读取；请核对后再操作。" : message(failure));
      }
    }
  }
  function startManagement(item: PaiConversation, action: PresentationAction, title?: string | null) {
    if (operation || disabled) return;
    const body = { expected_revision: item.presentation.revision, request_key: crypto.randomUUID(), action, ...(action === "rename" ? { title: title ?? null } : {}) };
    void manage({ sessionId: item.session_id, body });
  }
  const tooLong = [...q].length > 160;
  return <div className={styles.history} aria-label="持久会话记录">
    <label className={styles.search}><MagnifyingGlass size={13} aria-hidden="true" /><span className="sr-only">搜索会话名称、原目标或完整标识</span><input type="search" value={q} disabled={disabled} aria-invalid={tooLong} onChange={event => { clear(); setQ(event.target.value); }} placeholder="搜索会话或可读工作" /></label>
    <p className={styles.hint}>搜索包括名称和历史工作。先选会话，再选具体工作。</p>
    <div className={styles.tabs} role="group" aria-label="会话视图">{(["active", "archived"] as const).map(value => <Button key={value} size="sm" variant={view === value ? "secondary" : "ghost"} disabled={disabled} aria-pressed={view === value} onClick={() => { clear(); setView(value); }}>{value === "active" ? "未归档" : "已归档"}</Button>)}</div>
    <div className={styles.heading}><h2>我的会话</h2><Button size="sm" variant="ghost" disabled={disabled || listCurrent.loading} onClick={() => { clear(); setRefresh(value => value + 1); }}>刷新会话</Button></div>
    {operationError && <p role="alert">{operationError}</p>}
    {pending && <section className={styles.recovery} aria-label="核对原会话修改">
      <p role="status">{pending.state === "unknown" ? "会话修改结果尚未核对。原请求已保留；“刷新会话”只重新读取，不会再次提交。" : pending.state === "recovering" ? "正在查询原请求回执…" : "正在提交会话修改…"}</p>
      {pending.error && <p role="alert">{pending.error}</p>}
      <details className={styles.identifiers}><summary>原请求标识</summary><p>{pending.request.body.request_key}</p></details>
      {pending.state === "unknown" && <div className={styles.actions}><Button size="sm" variant="secondary" disabled={disabled} onClick={() => void manage(pending.request, true)}>查询原请求回执</Button><Button size="sm" variant="outline" disabled={disabled} onClick={() => void manage(pending.request)}>重试原请求</Button></div>}
    </section>}
    {tooLong && <p role="alert">搜索词最多 160 个字符。</p>}
    {listCurrent.loading && <p role="status">正在读取会话…</p>}
    {listCurrent.error && <p role="alert">{listCurrent.error}</p>}
    {!tooLong && listCurrent.value?.items.map(item => <div className={styles.sessionRecord} key={item.session_id}><button className={styles.session} type="button" title={`会话 ${item.session_id} · 建立于 ${item.created_at}`} disabled={disabled} aria-pressed={sessionId === item.session_id || currentSessionId === item.session_id} onClick={() => { clear(); setSelectedSession(item.session_id); void loadRuns(item.session_id); }}>
      <span className={styles.eyebrow}>{item.presentation.pinned ? "已置顶 · " : ""}{item.presentation.title ? "会话名称" : "最新原目标"}</span><strong>{item.presentation.title ?? item.latest_run.goal}</strong>{item.presentation.title && <span className={styles.meta}>最新原目标：{item.latest_run.goal}</span>}<span className={styles.meta}>{item.run_count} 项可读工作 · 最新工作：{labels[item.latest_run.status]}{item.latest_run.reverted ? " · 已撤回" : ""}</span>
      {item.matched_run && <span className={styles.match}>命中{item.matched_run.match_kind === "goal" ? "原目标" : item.matched_run.match_kind === "run_id" ? "运行标识" : "会话标识"}：{item.matched_run.goal}{item.matched_run.run_id !== item.latest_run.run_id ? "（历史工作）" : ""}</span>}
      <time className={styles.meta} dateTime={item.created_at}>建立于 {friendlyTime(item.created_at)}</time>
    </button><div className={styles.actions}>
      <Button size="sm" variant="ghost" disabled={disabled || !!operation || listCurrent.loading} onClick={() => setEditor({ key: listKey, item, title: item.presentation.title ?? "" })}>重命名</Button>
      <Button size="sm" variant="ghost" disabled={disabled || !!operation || listCurrent.loading} onClick={() => startManagement(item, item.presentation.pinned ? "unpin" : "pin")}>{item.presentation.pinned ? "取消置顶" : "置顶"}</Button>
      <Button size="sm" variant="ghost" disabled={disabled || !!operation || listCurrent.loading} onClick={() => startManagement(item, item.presentation.archived ? "restore" : "archive")}>{item.presentation.archived ? "恢复会话" : "归档"}</Button>
    </div>{visibleEditor?.item.session_id === item.session_id && <form className={styles.editor} onSubmit={event => { event.preventDefault(); if (visibleEditor.title.trim() && [...visibleEditor.title.trim()].length <= 160) startManagement(item, "rename", visibleEditor.title.trim()); }}>
      <label>会话名称<input aria-label="会话名称" value={visibleEditor.title} disabled={disabled || !!operation} onChange={event => setEditor({ ...visibleEditor, title: event.target.value })} /></label>
      <p className={styles.hint}>名称最多 160 个字符；恢复原目标会移除自定义名称。</p>
      <div className={styles.actions}><Button type="submit" size="sm" disabled={disabled || !!operation || !visibleEditor.title.trim() || [...visibleEditor.title.trim()].length > 160}>保存名称</Button><Button type="button" size="sm" variant="ghost" disabled={disabled || !!operation} onClick={() => startManagement(item, "rename", null)}>恢复原目标名称</Button><Button type="button" size="sm" variant="ghost" onClick={() => setEditor(null)}>取消</Button></div>
    </form>}</div>)}
    {!listCurrent.loading && !listCurrent.error && listCurrent.value?.items.length === 0 && <p className={styles.hint}>{q.trim() ? "当前范围没有匹配的可读会话。" : "当前范围暂无可读会话。"}</p>}
    {listCurrent.value?.next_cursor && <Button size="sm" variant="ghost" disabled={disabled || listCurrent.loading} onClick={() => void loadList(listCurrent.value!.next_cursor!)}>加载更多会话</Button>}
    {sessionId && <section className={styles.runs} aria-label="所选会话的工作">
      <h3>会话中的工作</h3><details className={styles.identifiers}><summary>记录标识</summary><p>会话 {sessionId}</p>{runsCurrent.value && <p>原建立时间：{runsCurrent.value.session.created_at}</p>}</details><p className={styles.hint}>仅选择具体工作后读取结果；继续资格仍按原运行核对。</p>
      {runsCurrent.loading && <p role="status">正在读取会话工作…</p>}{runsCurrent.error && <p role="alert">{runsCurrent.error}</p>}
      {runsCurrent.error && <Button size="sm" variant="ghost" disabled={disabled} onClick={() => void loadRuns(sessionId)}>重新读取会话工作</Button>}
      {runsCurrent.value?.items.map(item => <div key={item.run_id} className={styles.runRecord}><button type="button" className={styles.run} disabled={disabled || runsCurrent.loading} aria-pressed={currentRunId === item.run_id} onClick={() => onSelectRun(item.run_id, sessionId)}><strong>{item.goal}</strong><span className={styles.meta}>{labels[item.status]}{item.reverted ? " · 已撤回" : ""}</span><time dateTime={item.created_at} title={item.created_at}>{friendlyTime(item.created_at)}</time></button><details className={styles.identifiers}><summary>运行记录标识</summary><p>运行 {item.run_id}</p><p>原建立时间：{item.created_at}</p>{item.continued_from_id && <p>续接自 {item.continued_from_id}</p>}</details></div>)}
      {runsCurrent.value && <p className={styles.hint}>已加载 {runsCurrent.value.items.length} / {runsCurrent.value.session.run_count} 项可读工作</p>}
      {runsCurrent.value?.next_cursor && <Button size="sm" variant="ghost" disabled={disabled || runsCurrent.loading} onClick={() => void loadRuns(sessionId, runsCurrent.value!.next_cursor!)}>加载更多会话工作</Button>}
    </section>}
  </div>;
}
