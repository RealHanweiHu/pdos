"use client";

import { ArrowsOutSimpleIcon, LinkSimpleIcon, SparkleIcon, XIcon } from "@phosphor-icons/react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, Suspense, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { ProjectConversation } from "./project-conversation";
import { ProductConversation, type ProductConversationScope } from "./product-conversation";
import { resolveXiaopaiPageContext, restoreXiaopaiPageContext, type XiaopaiPageContext } from "./xiaopai-page-context";
import { XiaopaiFollowup } from "./xiaopai-followup";
import type { PreprojectLaunch } from "./xiaopai-launcher";
import { XiaopaiSession, type SessionActivity } from "./xiaopai-session";

type PersonalContext = { key: string; scope: ProductConversationScope; page: XiaopaiPageContext | null; goal?: PreprojectLaunch["goal"]; initialConversationId?: string };
const personalDefaultScope: ProductConversationScope = { scope_kind: "personal" };
function restoreBackground(key: string) {
  const contexts: PersonalContext[] = [], conversations: Record<string, string> = {}, notices: Record<string, string> = {};
  try {
    const rows: unknown = JSON.parse(sessionStorage.getItem(key) ?? "[]");
    if (!Array.isArray(rows)) return { contexts, conversations, notices };
    for (const row of rows.slice(0, 20)) {
      const page = restoreXiaopaiPageContext(row?.href);
      if (!page || page.scopeError || page.projectId || ![undefined, "category", "proposal"].includes(row.goal)) continue;
      const scope = page.productScope ?? personalDefaultScope;
      const expected = `${JSON.stringify(scope)}:${row.goal ?? "chat"}`;
      if (row.key !== expected || typeof row.conversationId !== "string") continue;
      contexts.push({ key: expected, scope, page, goal: row.goal, initialConversationId: row.conversationId });
      conversations[expected] = row.conversationId;
      if (row.notice === "已完成" || row.notice === "未完成，请查看原因") notices[expected] = row.notice;
    }
  } catch { /* Server receipts remain available when browser storage is unavailable. */ }
  return { contexts, conversations, notices };
}

const dotClass = "inline-flex shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-[inset_0_2px_4px_#ffffff40,inset_0_-3px_5px_#00000020]";
function PaiDot({ large = false }: { large?: boolean }) {
  return <span aria-hidden="true" className={`${dotClass} ${large ? "size-12" : "size-8"}`}><SparkleIcon weight="fill" size={large ? 24 : 16}/></span>;
}
type IdentityBridge = { setIdentity: (value: WorkspaceIdentity) => void; pending: boolean; setPending: (value: boolean) => void };
const Context = createContext<IdentityBridge | null>(null);
export function useXiaopaiPending() { return useContext(Context)?.pending ?? false; }
export function XiaopaiIdentity({ identity }: { identity: WorkspaceIdentity }) {
  const bridge = useContext(Context);
  useEffect(() => { bridge?.setIdentity(identity); }, [bridge, identity]);
  return null;
}
export function XiaopaiProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [pending, setPending] = useState(false);
  const [identityBridge] = useState(() => ({ setIdentity }));
  return <Context.Provider value={{ ...identityBridge, pending, setPending }}>{children}<Suspense fallback={null}><XiaopaiSurface key={identity ? `${identity.tenant.id}:${identity.user.id}` : "signed-out"} identity={identity}/></Suspense></Context.Provider>;
}
function XiaopaiSurface({ identity }: { identity: WorkspaceIdentity | null }) {
  const bridge = useContext(Context);
  const backgroundKey = `pdos-pai-background:${identity?.tenant.id}:${identity?.user.id}`;
  const [restoredBackground] = useState(() => restoreBackground(backgroundKey));
  const pathname = usePathname(), query = useSearchParams(), router = useRouter();
  const full = pathname === "/ask" && !query.get("meeting");
  const hidden = !identity || ["supplier", "customer"].includes(identity.user.role) || ["/login", "/setup"].includes(pathname);
  const [open, setOpen] = useState(false);
  const [preprojectLaunch,setPreprojectLaunch] = useState<PreprojectLaunch | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState("");
  const [contexts, setContexts] = useState<string[]>([]);
  const [conversations, setConversations] = useState<Record<string, string>>({});
  const [followupConversations, setFollowupConversations] = useState<Record<string, string>>({});
  const [requestedGoals, setRequestedGoals] = useState<Record<string, string>>({});
  const [source, setSource] = useState<XiaopaiPageContext | null>(null);
  const [pageExcerpt, setPageExcerpt] = useState("");
  const [personalConversations, setPersonalConversations] = useState<Record<string, string>>(restoredBackground.conversations);
  const [personalContexts, setPersonalContexts] = useState<PersonalContext[]>(restoredBackground.contexts);
  const [selectedPersonalKey, setSelectedPersonalKey] = useState<string | null>(null);
  const [activity, setActivity] = useState<Record<string, SessionActivity>>(() => Object.fromEntries(restoredBackground.contexts.filter(item => !restoredBackground.notices[item.key]).map(item => [item.key, "attention"])));
  const [notices, setNotices] = useState<Record<string, string>>(restoredBackground.notices);
  const [restoredPrivate, setRestoredPrivate] = useState<{ key: string; page?: XiaopaiPageContext; error?: string } | null>(null);
  const [pageHash, setPageHash] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [projectLoadAttempt, setProjectLoadAttempt] = useState(0);
  const panel = useRef<HTMLElement>(null), launcher = useRef<HTMLButtonElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const visible = !hidden && (open || full);
  const queryString = query.toString();
  const liveContext = resolveXiaopaiPageContext(pathname, new URLSearchParams(queryString), pageHash);
  const legacyKey = full && query.get("conversation") && !query.get("source") && !query.get("project") ? query.get("conversation")! : "";
  const restoredPage = restoredPrivate?.key === legacyKey ? restoredPrivate.page : undefined;
  const routePage = full ? (query.get("project") ? { ...liveContext, label: "项目", href: `/projects?project=${query.get("project")}` } : restoreXiaopaiPageContext(query.get("source")) ?? (legacyKey ? restoredPage : source)) : liveContext;
  const selectedPersonal = personalContexts.find(item => item.key === selectedPersonalKey);
  const page = selectedPersonal?.page ?? routePage;
  const projectId = selectedPersonal ? "" : page?.projectId ?? "";
  const current = projects.some(p => p.id === projectId) ? projectId : "";
  const project = projects.find(p => p.id === current);
  const pageConversation = full ? query.get("conversation") : null;
  const focusId = page?.focus?.id, focusKind = page?.focus?.kind;
  const personalScope = page?.productScope ?? personalDefaultScope;
  const personalKey = JSON.stringify(personalScope);
  const resumedKey = full && pageConversation ? personalContexts.find(item => personalConversations[item.key] === pageConversation)?.key : undefined;
  const personalSessionKey = selectedPersonalKey ?? resumedKey ?? `${personalKey}:${preprojectLaunch?.goal ?? "chat"}`;
  const personalAvailable = !current && !projectId && !(legacyKey && !restoredPage) && !page?.scopeError;
  const showingPersonal = visible && personalAvailable;
  const taskLabel = (key: string) => key.startsWith("project:") ? projects.find(item => `project:${item.id}` === key)?.name ?? "项目对话" : personalContexts.find(item => item.key === key)?.goal === "category" ? "新建品类研究" : personalContexts.find(item => item.key === key)?.page?.label ?? "个人对话";
  const updateActivity = (key: string, value: SessionActivity) => setActivity(old => old[key] === value ? old : { ...old, [key]: value });
  const replyReady = (key: string, status: string, showing: boolean) => {
    if (!showing) setNotices(old => ({ ...old, [key]: status === "answered" ? "已完成" : "未完成，请查看原因" }));
  };
  const showTask = (key: string) => {
    setNotices(old => { const next = { ...old }; delete next[key]; return next; });
    if (key.startsWith("project:")) router.push(`/ask?${new URLSearchParams({ source: `/projects?project=${key.slice(8)}`, ...(conversations[key.slice(8)] ? { conversation: conversations[key.slice(8)] } : {}) })}`);
    else { setSelectedPersonalKey(key); setOpen(true); }
  };
  useEffect(() => {
    if (!identity || hidden) return;
    const rows = personalContexts.filter(item => (activity[item.key] || notices[item.key]) && personalConversations[item.key]).map(item => ({
      key: item.key, href: item.page?.href ?? "/my-work", goal: item.goal,
      conversationId: personalConversations[item.key], notice: notices[item.key],
    }));
    try { sessionStorage.setItem(backgroundKey, JSON.stringify(rows)); } catch { /* Optional browser recovery index. */ }
  }, [identity, hidden, backgroundKey, personalContexts, activity, notices, personalConversations]);

  useEffect(() => {
    const launch = (event: Event) => {
      if (hidden || full) return;
      setSelectedPersonalKey(null);
      const intent = (event as CustomEvent).detail;
      setPreprojectLaunch(intent && ["category","proposal"].includes(intent.goal) ? {goal:intent.goal} : null);
      origin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setOpen(true);
    };
    window.addEventListener("pdos:open-xiaopai", launch);
    return () => window.removeEventListener("pdos:open-xiaopai", launch);
  }, [hidden, full]);

  useEffect(() => {
    if (!legacyKey || hidden) return;
    let active = true;
    void fetch(`/api/conversations/${encodeURIComponent(legacyKey)}`, { cache: "no-store" }).then(async response => { if (!response.ok) throw new Error("原私人对话当前不可读取，请重新核对权限。"); return response.json(); }).then(value => { if (!active) return; const row = value.conversation; if (!row || row.id !== legacyKey || row.visibility !== "private" || row.project_id || !["personal", "market_space", "product_line"].includes(row.scope_kind)) throw new Error("原对话范围不可用于当前私人入口。"); const params = new URLSearchParams(); if (row.scope_kind !== "personal") { if (!row.market_space_id || (row.scope_kind === "product_line" && !row.product_line_id)) throw new Error("原对话范围不完整"); params.set("space", row.market_space_id); if (row.scope_kind === "product_line") params.set("line", row.product_line_id); }
      const context = resolveXiaopaiPageContext(row.scope_kind === "personal" ? "/my-work" : "/product-work", params); if (context.scopeError || context.productScope?.scope_kind !== row.scope_kind) throw new Error("原对话范围不完整"); setRestoredPrivate({ key: legacyKey, page: context });
    }).catch(failure => { if (active) setRestoredPrivate({ key: legacyKey, error: failure instanceof Error ? failure.message : "原对话暂不可读" }); });
    return () => { active = false; };
  }, [legacyKey, hidden]);
  useEffect(() => {
    const capture = () => setPageHash(window.location.hash);
    const timer = window.setTimeout(capture, 0);
    window.addEventListener("hashchange", capture);
    return () => { window.clearTimeout(timer); window.removeEventListener("hashchange", capture); };
  }, [pathname, queryString]);
  useEffect(() => {
    if (hidden || !showingPersonal) return;
    const timer = window.setTimeout(() => {
      setPersonalContexts(old => old.some(item => item.key === personalSessionKey) ? old : [...old, {
        key: personalSessionKey, scope: personalScope, page: page ?? null, goal: preprojectLaunch?.goal,
        initialConversationId: preprojectLaunch ? undefined : pageConversation ?? undefined,
      }]);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [hidden, showingPersonal, personalSessionKey, personalKey, pageConversation, preprojectLaunch, page, personalScope]);

  const navigation = useRef(`${pathname}?${queryString}`);
  useEffect(() => {
    const next = `${pathname}?${queryString}`;
    if (navigation.current === next) return;
    navigation.current = next;
    if (full) return;
    const timer = window.setTimeout(() => { if (Object.values(activity).some(Boolean)) setOpen(false); setSelectedPersonalKey(null); setPreprojectLaunch(null); }, 0);
    return () => window.clearTimeout(timer);
  }, [pathname, queryString, full, activity]);

  useEffect(() => {
    if (hidden || pathname === "/ask") return;
    const timer = window.setTimeout(() => {
      setSource(resolveXiaopaiPageContext(pathname, new URLSearchParams(queryString), pageHash));
      setPageExcerpt("");
      setError(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [hidden, pathname, queryString, pageHash]);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    const timer = window.setTimeout(() => {
      if (!projectId) { setLoading(false); return; }
      setError(null);
      setLoading(true);
      void requestProjectList().then(value => {
        if (!active) return;
        if (!value) { setError("请重新登录后打开小Pai"); return; }
        setProjects(value);
        setLoadedProjectId(projectId);
      }).catch(() => { if (active) setError("项目信息暂时无法读取，请重新读取后继续"); }).finally(() => { if (active) setLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [visible, projectId, projectLoadAttempt]);
  useEffect(() => {
    if (!visible || !current) return;
    const timer = window.setTimeout(() => {
      setContexts(old => old.includes(current) ? old : [...old, current]);
      if (pageConversation) setConversations(old => old[current] === pageConversation ? old : { ...old, [current]: pageConversation });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [visible, current, pageConversation]);
  useEffect(() => {
    if (!visible || full) return;
    // Read only text already rendered for this user. Never scrape inputs,
    // hidden state, files, or another page, and never publish this snapshot.
    const main = document.querySelector("main");
    if (!main) return;
    const capture = () => setPageExcerpt((main.innerText ?? "").replace(/\n{3,}/g, "\n\n").trim().slice(0, 2400));
    const timer = window.setTimeout(capture, 0);
    const observer = new MutationObserver(capture);
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    return () => { window.clearTimeout(timer); observer.disconnect(); };
  }, [visible, full, pathname, queryString]);
  useEffect(() => {
    if (!visible) return;
    const timer = window.setTimeout(() => panel.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [visible]);
  const close = () => { setOpen(false); if (full) router.push(page?.href ?? "/"); else (origin.current?.isConnected ? origin.current : launcher.current)?.focus(); origin.current = null; };
  const expand = () => {
    const params = new URLSearchParams();
    if (page) params.set("source", page.href);
    if (current && conversations[current]) params.set("conversation", conversations[current]);
    else if (personalConversations[personalSessionKey]) params.set("conversation", personalConversations[personalSessionKey]);
    router.push(`/ask${params.size ? `?${params}` : ""}`);
  };
  if (hidden) return null;
  const contextLabel = loading ? "正在读取当前页面…" : project?.name ?? page?.label ?? "个人对话";
  return <>
    {!full && (Object.values(activity).some(Boolean) || Object.keys(notices).length > 0) && <aside aria-label="小Pai后台工作" className="fixed bottom-20 right-5 z-40 max-w-[calc(100vw-2.5rem)] rounded-lg border bg-background p-3 shadow-lg">
      <p role="status" className="text-xs text-muted-foreground">小Pai后台工作 · 可以继续使用其他页面</p>
      {[...new Set([...Object.keys(notices), ...Object.keys(activity).filter(key => activity[key])])].map(key => <Button key={key} size="sm" variant="ghost" className="mt-1 flex max-w-full whitespace-normal text-left" onClick={() => showTask(key)}>{taskLabel(key)} · {notices[key] ?? (activity[key] === "running" ? "处理中" : "待查询回执")} · 查看</Button>)}
    </aside>}
    {!full && <button ref={launcher} type="button" aria-label="打开小Pai" title="小Pai · 你的个人 Agent" aria-expanded={visible} aria-controls="xiaopai-panel" className="fixed bottom-5 right-5 z-40 rounded-full p-1 outline-none transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 motion-reduce:transition-none" onClick={() => open ? close() : setOpen(true)}><PaiDot large/></button>}
    <section ref={panel} id="xiaopai-panel" tabIndex={-1} aria-label="小Pai对话" hidden={!visible} onKeyDown={e => { if (e.key === "Escape" && !full) close(); }} className={full ? "xiaopai-full-panel fixed inset-x-0 bottom-0 top-12 z-30 flex flex-col bg-background" : pathname === "/product-work" ? "fixed inset-0 z-40 flex flex-col overflow-hidden border-l bg-background shadow-xl sm:left-auto sm:w-[420px]" : "fixed inset-0 z-40 flex flex-col overflow-hidden bg-background sm:inset-auto sm:bottom-6 sm:right-4 sm:top-16 sm:w-[420px] sm:rounded-lg sm:border sm:shadow-xl"}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-5 py-4"><div className="flex items-center gap-3"><PaiDot/><div><h1 className="text-sm font-semibold">小Pai</h1><p className="text-xs text-muted-foreground">你的个人 Agent</p></div></div><div className="flex gap-1">{!full && <Button size="icon" variant="ghost" aria-label="展开小Pai完整页面" onClick={expand}><ArrowsOutSimpleIcon aria-hidden="true"/></Button>}<Button size="icon" variant="ghost" aria-label="收起小Pai" onClick={close}><XIcon aria-hidden="true"/></Button></div></header>
      <div className={`flex min-h-0 flex-1 flex-col ${full ? "mx-auto w-full max-w-3xl" : ""}`}>
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3 text-xs text-muted-foreground" role="status"><LinkSimpleIcon aria-hidden="true" size={14}/><span className="shrink-0">已自动带入</span><span className="truncate font-medium text-foreground">{contextLabel}</span>{focusKind && <span className="shrink-0">· 当前工作对象</span>}</div>
        {projectId && loadedProjectId === projectId && !current && !loading && !error && <p role="alert" className="px-5 pt-3 text-sm text-destructive">当前项目不存在或已无权访问，未读取其对话内容。</p>}
        {error && <p role="alert" className="px-5 pt-3 text-sm text-destructive">{error}</p>}
        {projectId && error === "项目信息暂时无法读取，请重新读取后继续" && <div className="px-5 pt-2"><Button size="sm" variant="outline" disabled={loading} onClick={() => setProjectLoadAttempt(value => value + 1)}>重新读取项目</Button></div>}
        {contexts.filter(id => projects.some(p => p.id === id)).map(id => <div key={id} hidden={current !== id} className="flex min-h-0 flex-1 flex-col">
          <XiaopaiSession visible={visible && current===id} scope={{ scope_kind: "project", project_id: id }} identityKey={`${identity!.tenant.id}:${identity!.user.id}`} initialConversationId={conversations[id]} onConversationReady={cid => setConversations(old => old[id] === cid ? old : { ...old, [id]: cid })} onPendingChange={() => {}} onActivityChange={value => updateActivity(`project:${id}`, value)} onReplyReady={status => replyReady(`project:${id}`, status, visible && current === id)} onAuthorityLost={setError} renderTools={cid => <>
            <ProjectConversation presentation="assistant" onDelegateRequest={goal => setRequestedGoals(old => ({ ...old, [id]: goal }))} projectId={id} defaultOpen initialConversationId={cid} initialAttachmentId={current === id ? query.get("attachment") ?? undefined : undefined} initialFragment={Number(query.get("fragment")) || 1} initialWorkFocus={current === id && focusId && focusKind ? { id: focusId, kind: focusKind } : undefined}/>
            <details open={!!requestedGoals[id]} className="mt-4 border-t pt-3"><summary className="cursor-pointer py-2 text-xs text-muted-foreground">持续委托与跟进</summary><XiaopaiFollowup requestedGoal={requestedGoals[id]} projectId={id} userId={identity!.user.id} conversationId={followupConversations[id]} onConversationReady={cid => setFollowupConversations(old => old[id] === cid ? old : { ...old, [id]: cid })}/></details>
          </>}/>
        </div>)}
        {!current && !projectId && !personalAvailable && (legacyKey && !restoredPage ? <p role="alert" className="px-5 py-4">{restoredPrivate?.key === legacyKey && restoredPrivate.error ? restoredPrivate.error : "正在核对原私人对话范围…"}</p> : <p role="alert" className="px-5 py-4 text-sm text-destructive">{page?.scopeError}</p>)}
        {personalContexts.map(entry => <div key={entry.key} hidden={!personalAvailable || personalSessionKey !== entry.key} className="flex min-h-0 flex-1 flex-col">
          <XiaopaiSession visible={showingPersonal && personalSessionKey === entry.key} preprojectGoal={entry.goal} scope={entry.scope} identityKey={`${identity!.tenant.id}:${identity!.user.id}`} initialToolsOpen={!!(full && query.get("attachment"))} initialConversationId={entry.initialConversationId} onConversationReady={id => setPersonalConversations(old => old[entry.key] === id ? old : { ...old, [entry.key]: id })} onPendingChange={() => {}} onActivityChange={value => updateActivity(entry.key, value)} onReplyReady={status => replyReady(entry.key, status, showingPersonal && personalSessionKey === entry.key)} onAuthorityLost={message => { setPersonalConversations(old => { const next = { ...old }; delete next[entry.key]; return next; }); setNotices(old => { const next = { ...old }; delete next[entry.key]; return next; }); setError(message); }} renderTools={id => <ProductConversation scope={entry.scope} sources={entry.key === personalSessionKey ? page?.productSources : entry.page?.productSources} matrixSelection={entry.key === personalSessionKey ? page?.matrixSelection : entry.page?.matrixSelection} matrixContext={(entry.key === personalSessionKey ? page : entry.page)?.tab === "matrix"} initialAttachmentId={full && entry.key === personalSessionKey ? query.get("attachment") ?? undefined : undefined} initialFragment={Number(query.get("fragment")) > 0 && Number.isInteger(Number(query.get("fragment"))) ? Number(query.get("fragment")) : 1} initialConversationId={id} onPendingChange={value => bridge?.setPending(value)} onAuthorityLost={setError}/>}/>
        </div>)}
        {pageExcerpt && !full && <details className="shrink-0 border-t px-5 py-2 text-xs text-muted-foreground"><summary className="cursor-pointer">查看页面上下文</summary><p className="max-h-32 overflow-y-auto whitespace-pre-wrap py-2 leading-5">{pageExcerpt}</p></details>}
      </div>
    </section>
  </>;
}
