"use client";

import { ArrowsOutSimpleIcon, LinkSimpleIcon, SparkleIcon, XIcon } from "@phosphor-icons/react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, Suspense, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { ProjectConversation } from "./project-conversation";
import { ProductConversation } from "./product-conversation";
import { resolveXiaopaiPageContext, restoreXiaopaiPageContext, type XiaopaiPageContext } from "./xiaopai-page-context";
import { XiaopaiFollowup } from "./xiaopai-followup";

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
  const pathname = usePathname(), query = useSearchParams(), router = useRouter();
  const full = pathname === "/ask" && !query.get("meeting");
  const hidden = !identity || ["supplier", "customer"].includes(identity.user.role) || ["/login", "/setup"].includes(pathname);
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [contexts, setContexts] = useState<string[]>([]);
  const [conversations, setConversations] = useState<Record<string, string>>({});
  const [followupConversations, setFollowupConversations] = useState<Record<string, string>>({});
  const [requestedGoals, setRequestedGoals] = useState<Record<string, string>>({});
  const [source, setSource] = useState<XiaopaiPageContext | null>(null);
  const [pageExcerpt, setPageExcerpt] = useState("");
  const [personalConversations, setPersonalConversations] = useState<Record<string, string>>({});
  const [productPending, setProductPending] = useState(false);
  const [restoredPrivate, setRestoredPrivate] = useState<{ key: string; page?: XiaopaiPageContext; error?: string } | null>(null);
  const [pageHash, setPageHash] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const panel = useRef<HTMLElement>(null), launcher = useRef<HTMLButtonElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const visible = !hidden && (open || full);
  const queryString = query.toString();
  const liveContext = resolveXiaopaiPageContext(pathname, new URLSearchParams(queryString), pageHash);
  const legacyKey = full && query.get("conversation") && !query.get("source") && !query.get("project") ? query.get("conversation")! : "";
  const restoredPage = restoredPrivate?.key === legacyKey ? restoredPrivate.page : undefined;
  const page = full ? (query.get("project") ? { ...liveContext, label: "项目", href: `/projects?project=${query.get("project")}` } : restoreXiaopaiPageContext(query.get("source")) ?? (legacyKey ? restoredPage : source)) : liveContext;
  const projectId = page?.projectId ?? "";
  const current = projects.some(p => p.id === projectId) ? projectId : "";
  const project = projects.find(p => p.id === current);
  const pageConversation = full ? query.get("conversation") : null;
  const focusId = page?.focus?.id, focusKind = page?.focus?.kind;
  const personalScope = page?.productScope ?? { scope_kind: "personal" as const };
  const personalKey = JSON.stringify(personalScope);

  useEffect(() => {
    const launch = () => {
      if (hidden || full) return;
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
    if (!productPending) return;
    const leaving = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const navigating = (event: MouseEvent) => { const target = event.target instanceof Element ? event.target.closest("a[href]") : null; if (target && target.getAttribute("href") && !target.getAttribute("href")!.startsWith("#")) { event.preventDefault(); setError("原请求尚未确认，请先查询或重试原请求再离开此工作范围。"); } };
    window.addEventListener("beforeunload", leaving); document.addEventListener("click", navigating, true);
    return () => { window.removeEventListener("beforeunload", leaving); document.removeEventListener("click", navigating, true); };
  }, [productPending]);

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
      setLoading(true);
      void requestProjectList().then(value => {
        if (!active) return;
        if (!value) { setError("请重新登录后打开小Pai"); return; }
        setProjects(value);
      }).catch(() => { if (active) setError("页面上下文暂时无法读取，请稍后重试"); }).finally(() => { if (active) setLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [visible, projectId]);
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
  const close = () => { if (productPending) { setError("原请求尚未确认，请先查询或重试原请求。"); return; } setOpen(false); if (full) router.push(page?.href ?? "/"); else (origin.current?.isConnected ? origin.current : launcher.current)?.focus(); origin.current = null; };
  const expand = () => {
    if (productPending) { setError("原请求尚未确认，请先查询或重试原请求。"); return; }
    const params = new URLSearchParams();
    if (page) params.set("source", page.href);
    if (current && conversations[current]) params.set("conversation", conversations[current]);
    else if (personalConversations[personalKey]) params.set("conversation", personalConversations[personalKey]);
    router.push(`/ask${params.size ? `?${params}` : ""}`);
  };
  if (hidden) return null;
  const contextLabel = loading ? "正在读取当前页面…" : project?.name ?? page?.label ?? "个人对话";
  return <>
    {!full && <button ref={launcher} type="button" aria-label="打开小Pai" title="小Pai · 你的个人 Agent" aria-expanded={visible} aria-controls="xiaopai-panel" className="fixed bottom-5 right-5 z-40 rounded-full p-1 outline-none transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4 motion-reduce:transition-none" onClick={() => open ? close() : setOpen(true)}><PaiDot large/></button>}
    <section ref={panel} id="xiaopai-panel" tabIndex={-1} aria-label="小Pai对话" hidden={!visible} onKeyDown={e => { if (e.key === "Escape" && !full) close(); }} className={full ? "fixed inset-x-0 bottom-0 top-12 z-30 flex flex-col bg-background lg:left-56" : "fixed inset-0 z-40 flex flex-col overflow-hidden bg-background sm:inset-auto sm:bottom-6 sm:right-4 sm:top-16 sm:w-[420px] sm:rounded-lg sm:border sm:shadow-xl"}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-5 py-4"><div className="flex items-center gap-3"><PaiDot/><div><h1 className="text-sm font-semibold">小Pai</h1><p className="text-xs text-muted-foreground">你的个人 Agent</p></div></div><div className="flex gap-1">{!full && <Button size="icon" variant="ghost" aria-label="展开小Pai完整页面" onClick={expand}><ArrowsOutSimpleIcon aria-hidden="true"/></Button>}<Button size="icon" variant="ghost" aria-label="收起小Pai" onClick={close}><XIcon aria-hidden="true"/></Button></div></header>
      <div className={`flex min-h-0 flex-1 flex-col ${full ? "mx-auto w-full max-w-3xl" : ""}`}>
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3 text-xs text-muted-foreground" role="status"><LinkSimpleIcon aria-hidden="true" size={14}/><span className="shrink-0">已自动带入</span><span className="truncate font-medium text-foreground">{contextLabel}</span>{focusKind && <span className="shrink-0">· 当前工作对象</span>}</div>
        {projectId && !current && !loading && <p role="alert" className="px-5 pt-3 text-sm text-destructive">当前项目不存在或已无权访问，未读取其对话内容。</p>}
        {error && <p role="alert" className="px-5 pt-3 text-sm text-destructive">{error}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!current && <div className="flex min-h-full flex-col">
            <div className="flex flex-1 flex-col items-center justify-center py-12 text-center"><PaiDot large/><h2 className="mt-5 text-xl font-medium tracking-tight">有什么想一起处理？</h2><p className="mt-3 max-w-xs text-sm leading-6 text-muted-foreground">我会跟着你的工作页面带入上下文。<br/>直接说出目标，不需要先选项目。</p></div>
            {page && <details className="pb-3 text-xs text-muted-foreground"><summary className="cursor-pointer py-2">查看已带入的页面上下文</summary><p className="py-2">{page.label}{page.spaceId ? " · 当前市场空间" : ""} · 当前页面可见资料</p>{pageExcerpt ? <p className="max-h-40 overflow-y-auto whitespace-pre-wrap leading-5">{pageExcerpt}</p> : <p>已保留来源页面；未读取隐藏内容或其他工作范围。</p>}</details>}
          </div>}
          {contexts.filter(id => projects.some(p => p.id === id)).map(id => <div key={id} hidden={current !== id} className="space-y-4">
            <ProjectConversation presentation="assistant" onDelegateRequest={goal => setRequestedGoals(old => ({ ...old, [id]: goal }))} projectId={id} defaultOpen initialConversationId={conversations[id]} initialAttachmentId={current === id ? query.get("attachment") ?? undefined : undefined} initialFragment={Number(query.get("fragment")) || 1} initialWorkFocus={current === id && focusId && focusKind ? { id: focusId, kind: focusKind } : undefined} onConversationReady={cid => setConversations(old => old[id] === cid ? old : { ...old, [id]: cid })}/>
            <details open={!!requestedGoals[id]} className="border-t pt-3"><summary className="cursor-pointer py-2 text-xs text-muted-foreground">持续委托与跟进</summary><XiaopaiFollowup requestedGoal={requestedGoals[id]} projectId={id} userId={identity!.user.id} conversationId={followupConversations[id]} onConversationReady={cid => setFollowupConversations(old => old[id] === cid ? old : { ...old, [id]: cid })}/></details>
          </div>)}
        </div>
        {!current && !projectId && <div className="min-h-0 overflow-y-auto border-t px-5 py-4">{legacyKey && !restoredPage ? <p role="alert">{restoredPrivate?.key === legacyKey && restoredPrivate.error ? restoredPrivate.error : "正在核对原私人对话范围…"}</p> : page?.scopeError ? <p role="alert" className="text-sm text-destructive">{page.scopeError}</p> : <ProductConversation scope={personalScope} sources={page?.productSources} matrixSelection={page?.matrixSelection} matrixContext={page?.tab === "matrix"} initialAttachmentId={full ? query.get("attachment") ?? undefined : undefined} initialFragment={Number(query.get("fragment")) > 0 && Number.isInteger(Number(query.get("fragment"))) ? Number(query.get("fragment")) : 1} initialConversationId={personalConversations[personalKey] ?? (full ? pageConversation ?? undefined : undefined)} onConversationReady={id => setPersonalConversations(old => old[personalKey] === id ? old : { ...old, [personalKey]: id })} onPendingChange={value => { setProductPending(value); bridge?.setPending(value); }} onAuthorityLost={setError}/>}</div>}
      </div>
    </section>
  </>;
}
