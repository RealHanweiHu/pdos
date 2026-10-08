"use client";

import { ArrowLeftIcon, ArrowClockwiseIcon, CaretRightIcon, ChatCircleDotsIcon, GearSixIcon, ListBulletsIcon, SquaresFourIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { openXiaopai } from "@/components/ai/xiaopai-launcher";
import { CategoryLifecycleAction } from "./category-lifecycle-action";
import { ProductSpaceOverview } from "./product-space-overview";
import { ProductProposals } from "./product-proposals";
import { ProductWorkScopeContext, useProductWorkUpdates } from "./product-work-scope";
import { navigateProductWork, productViews, productView, productWorkHref } from "./product-work-navigation";
import { useXiaopaiPending } from "@/components/ai/xiaopai-provider";
import { requestIdentity } from "@/components/workspace-api";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";
import { WorkHistory } from "./work-history";
import { WorkResponsibility, WorkResponsibilityLanding } from "./work-responsibility";
import { ProductRequestError, actionLabels, command, request, stateLabels, type Evidence, type Member, type ProductCatalog, type Research, type Space, type WorkItem, type Workspace } from "./product-work-api";

import { EvidencePicker } from "./evidence-picker";
import { DefinitionExports } from "./definition-exports";
import { DefinitionWorkspace } from "./definitions";
import { StrategyWorkspace } from "./strategies";
import { ExperimentWorkspace } from "./experiments";
import { OpportunityTree } from "./opportunities";
import { MarketSegments } from "./market-segments";
import { CompetitorWorkspace } from "./competitors";
import { ProductTree, SpaceSettings } from "./product-catalog";
import { ProductRoadmap } from "./product-roadmap";
import { ProductMatrix } from "./product-matrix";
import { ResearchCollection } from "./research-collection";
import { ResearchMeasurement } from "./research-measurement";
import { SourceCitations } from "./source-citations";
import { ProductSourceFiles } from "./product-source-files";
import { ProductAiPreparation } from "./product-ai-preparation";
import { ProductShadowEvaluation } from "./product-shadow-evaluation";
import { ProductReadingProvider } from "./product-reading-context";
import { ProductResearchEntries } from "./product-research-entries";
import { ReadingRecord } from "./product-reading-ui";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const lines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);
const accessLabels: Record<string, string> = { viewer: "只读", contributor: "协作", manager: "管理" };
const tabs = ["研究", "竞品", "细分 / JTBD", "机会树", "策略", "定义", "矩阵 / 路线图", "实验 / 决策", "导出中心", "投入观察", "能力评测"];

const tabKeys = ["research", "competitors", "segments", "opportunities", "strategies", "definitions", "matrix", "experiments", "exports", "measurement", "evaluation"];

const spaceLifecycleLabels: Record<string, string> = { draft: "草稿", active: "启用", archived: "已归档", retired: "已退役" };
const VIEW_STORAGE_KEY = "pdos.productWork.view";

function spaceMeta(space: Space) {
  const parts: string[] = [];
  if (space.user_groups.length) parts.push(`${space.user_groups.length} 个用户群`);
  if (space.regions.length) parts.push(`${space.regions.length} 个地域`);
  if (space.use_scenarios.length) parts.push(`${space.use_scenarios.length} 个场景`);
  if (space.research_questions.length) parts.push(`${space.research_questions.length} 个研究问题`);
  return parts.join(" · ");
}

const navigateWorkspace = navigateProductWork;

function useRequestId() {
  const last = useRef({ body: "", id: "" });
  return (body: unknown) => {
    const serialized = JSON.stringify(body);
    if (last.current.body !== serialized) last.current = { body: serialized, id: crypto.randomUUID() };
    return last.current.id;
  };
}

export function ProductWorkspace() {
  const paiPending = useXiaopaiPending();
  const { replace } = useRouter();
  const search = useSearchParams();
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [identityFailed, setIdentityFailed] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [spaces, setSpaces] = useState<Space[] | null>(null);
  const [canCreate, setCanCreate] = useState(false);
  const [sourceLock, setSourceLock] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"list" | "cards">(() => {
    try { return typeof window !== "undefined" && window.localStorage.getItem(VIEW_STORAGE_KEY) === "cards" ? "cards" : "list"; }
    catch { return "list"; }
  });
  const directoryRevision = useRef(0);
  const load = async () => { const revision = ++directoryRevision.current; const data = await request<{ items: Space[]; can_create: boolean }>("categories"); if (revision !== directoryRevision.current) return; setSpaces(data.items); setCanCreate(data.can_create); };
  useEffect(() => {
    let live = true;
    void requestIdentity().then((loaded) => {
      if (!live) return;
      if (loaded === null) { replace("/login"); return; }
      setIdentity(loaded);
    }).catch(() => { if (live) setIdentityFailed(true); });
    const reading = ++directoryRevision.current;
    void request<{ items: Space[]; can_create: boolean }>("categories").then((data) => {
      if (!live || reading !== directoryRevision.current) return; setSpaces(data.items); setCanCreate(data.can_create);
    }).catch((failure) => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [replace]);
  // Selection is derived from the ?space= deep link, so shared links and
  // browser back/forward keep the directory and workspace in sync.
  const targetSpace = search.get("category") ?? search.get("space") ?? "";
  const selected = spaces?.some(space => space.id === targetSpace) ? targetSpace : "";
  const closeSpace = () => { if (!paiPending) navigateWorkspace({ space: "" }); };
  const changeViewMode = (mode: "list" | "cards") => {
    setViewMode(mode);
    try { window.localStorage.setItem(VIEW_STORAGE_KEY, mode); } catch { /* Storage preference is optional. */ }
  };
  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }
  if (identityFailed) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">产品管理工作台暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">无法读取当前登录身份，请刷新重试。</p>
      </main>
    );
  }
  if (identity === null) {
    return <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">正在加载产品管理工作台…</main>;
  }
  const selectedSpace = spaces?.find((space) => space.id === selected) ?? null;
  const visibleSpaces = spaces?.filter(space => (space.lifecycle === "archived") === showArchived);
  const lifecycleChanged = (saved: Space) => {
    directoryRevision.current += 1;
    setSpaces(current => current?.map(space => space.id === saved.id ? { ...space, ...saved } : space) ?? null);
    if (saved.lifecycle === "archived" && selected === saved.id) navigateWorkspace({ space: "" });
    void load().catch(failure => setError(failure.message));
  };
  return <WorkspaceShell active="product-work" identity={identity} loggingOut={loggingOut} onLogout={() => void logout()}>
    <div className="space-y-6">
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {spaces && targetSpace && !selected && <p role="alert" className="text-sm text-destructive">此品类不存在或当前无权访问，请重新选择。</p>}
    {selectedSpace ? (
      <SpaceWorkspace key={`${selected}:${search.get("line") ?? "all"}`} spaceId={selected} onLifecycleChanged={lifecycleChanged} directoryBreadcrumb={<div className="flex min-w-0 items-center gap-1.5">
          <Button className="-ml-2 gap-1 text-muted-foreground" onClick={closeSpace} disabled={paiPending || sourceLock === `${selected}:${search.get("line") ?? "all"}`} size="sm" variant="ghost">
            <ArrowLeftIcon aria-hidden="true" className="size-4" />
            品类
          </Button>
          <span aria-hidden="true" className="text-sm text-muted-foreground">/</span>
          <span className="truncate text-sm font-medium">{selectedSpace.title}</span>
        </div>} canEvaluate={["owner", "admin"].includes(identity.user.role)} onSourcePendingChange={value => { const owner = `${selected}:${search.get("line") ?? "all"}`; setSourceLock(current => value ? owner : current === owner ? null : current); }}/>
    ) : (
      <>
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">品类</h1>
            <p className="mt-2 text-sm text-muted-foreground">从客户需求、新品想法或产品迭代开始一份提案。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" aria-pressed={showArchived} disabled={busy || paiPending} onClick={() => setShowArchived(!showArchived)}>{showArchived ? "返回品类列表" : "已归档"}</Button>
            <div aria-label="切换视图" className="flex items-center rounded-lg border p-0.5" role="group">
              {([["list", ListBulletsIcon, "列表"], ["cards", SquaresFourIcon, "卡片"]] as const).map(([mode, Icon, label]) => (
                <button
                  aria-label={`${label}视图`}
                  aria-pressed={viewMode === mode}
                  className={cn(
                    "flex size-11 items-center sm:size-7 justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
                    viewMode === mode && "bg-muted text-foreground",
                  )}
                  key={mode}
                  onClick={() => changeViewMode(mode)}
                  type="button"
                >
                  <Icon aria-hidden="true" className="size-4" />
                </button>
              ))}
            </div>
            {canCreate && <Button disabled={busy || paiPending} onClick={() => openXiaopai({goal:"category"})}><ChatCircleDotsIcon aria-hidden="true"/>新建品类</Button>}
            <Button variant="outline" disabled={busy} onClick={() => { setError(null); void load().catch((failure) => setError(failure.message)); }}>刷新</Button>
          </div>
        </header>
        {visibleSpaces?.length === 0 && <p className="text-sm text-muted-foreground">{showArchived ? "暂无已归档品类。" : canCreate ? "尚无可访问品类。点击新建品类，和小Pai一起明确方向并开始研究。" : "尚无可访问品类。请由品类负责人将你加入协作成员。"}</p>}
        {visibleSpaces && visibleSpaces.length > 0 && viewMode === "list" ? (
          <div className="overflow-hidden rounded-lg border bg-card">
            <ul className="divide-y" role="list">
              {visibleSpaces.map((space) => (
                <li key={space.id} className="flex items-center">
                  <Link
                    className="flex min-h-11 min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/25"
                    href={productWorkHref(space.id)}
                    onClick={event => { if (busy || paiPending) event.preventDefault(); }}
                  >
                    <span className="hidden max-w-[40%] shrink-0 truncate rounded border bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground sm:block">{space.code}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{space.title}</span>
                      {spaceMeta(space) ? <span className="mt-0.5 block truncate text-xs text-muted-foreground">{spaceMeta(space)}</span> : null}
                    </span>
                    <span className="shrink-0 rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{spaceLifecycleLabels[space.lifecycle] ?? space.lifecycle}</span>
                    <CaretRightIcon aria-hidden="true" className="hidden size-4 shrink-0 text-muted-foreground sm:block" />
                  </Link>
                  {space.can_restore && <div className="shrink-0 pr-2"><CategoryLifecycleAction space={space} compact disabled={busy || paiPending} onChanged={lifecycleChanged} onPendingChange={setBusy}/></div>}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {visibleSpaces && visibleSpaces.length > 0 && viewMode === "cards" ? (
          <div className="space-y-3">
            {visibleSpaces.map((space) => (
              <div key={space.id} className="overflow-hidden rounded-lg border bg-card">
              <Link
                className="block text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
                href={productWorkHref(space.id)}
                onClick={event => { if (busy || paiPending) event.preventDefault(); }}
              >
                <span className="block space-y-2 p-4">
                  <span className="flex items-center gap-2">
                    <span className="min-w-0 truncate rounded border bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{space.code}</span>
                    <span className="ml-auto rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{spaceLifecycleLabels[space.lifecycle] ?? space.lifecycle}</span>
                  </span>
                  <span className="block truncate text-sm font-medium">{space.title}</span>
                  {spaceMeta(space) ? <span className="block truncate text-xs text-muted-foreground">{spaceMeta(space)}</span> : null}
                </span>
              </Link>
              {space.can_restore && <div className="flex justify-end border-t px-2 py-1"><CategoryLifecycleAction space={space} compact disabled={busy || paiPending} onChanged={lifecycleChanged} onPendingChange={setBusy}/></div>}
              </div>
            ))}
          </div>
        ) : null}
      </>
    )}
    </div>
  </WorkspaceShell>;
}

function MemberSelect({ members, name, label, required = false, defaultValue = "" }: { members: Member[]; name: string; label: string; required?: boolean; defaultValue?: string }) {
  return <label className="text-sm">{label}<select name={name} required={required} defaultValue={defaultValue} className={field}><option value="">待指定</option>{members.filter((member) => member.access !== "viewer").map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>;
}

function SpaceWorkspace({ spaceId, directoryBreadcrumb, canEvaluate, onSourcePendingChange, onLifecycleChanged }: { spaceId: string; directoryBreadcrumb: ReactNode; canEvaluate: boolean; onSourcePendingChange: (pending: boolean) => void; onLifecycleChanged: (space: Space) => void }) {
  const paiPending = useXiaopaiPending();
  const [data, setData] = useState<Workspace | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const search = useSearchParams();
  const scopeFilter = "all";
  const legacyLine = search.get("line");

  const requestedTab = search.get("tab");
  const view = requestedTab ?? (search.has("line") ? "overview" : search.has("run") || search.has("responsibility_id") || typeof window !== "undefined" && /^#(?:work|research)-/.test(window.location.hash) ? "research" : "proposals");
  const tab = tabKeys.indexOf(view);
  const selectedView = productView(view);
  const [aiOpen, setAiOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formKind, setFormKind] = useState<"research" | "work" | null>(null);
  const stableId = useRequestId();
  const [responsibilityLock, setResponsibilityLock] = useState<string | null>(null);
  const base = `spaces/${spaceId}`;
  const live = useRef(true), authorityRevision = useRef(0), loadRevision = useRef(0);
  const sourcePendingCallback = useRef(onSourcePendingChange);
  useEffect(() => { sourcePendingCallback.current = onSourcePendingChange; }, [onSourcePendingChange]);
  useEffect(() => { live.current = true; return () => { live.current = false; authorityRevision.current += 1; loadRevision.current += 1; }; }, []);
  const clearAuthority = useCallback((message: string) => {
    authorityRevision.current += 1; loadRevision.current += 1;
    setData(null); setEvidence([]); setCatalog(null); setFormKind(null); setResponsibilityLock(null); setBusy(false); setError(message); sourcePendingCallback.current(false);
  }, []);
  const marketPendingChange = useCallback((value: boolean) => {
    setResponsibilityLock(current => value ? "market" : current === "market" ? null : current);
    sourcePendingCallback.current(value);
  }, []);
  const evaluationPendingChange = useCallback((value: boolean) => {
    setResponsibilityLock(current => value ? "evaluation" : current === "evaluation" ? null : current);
    sourcePendingCallback.current(value);
  }, []);
  const candidatePendingChange = useCallback((value: boolean) => {
    setResponsibilityLock(current => value ? "candidate" : current === "candidate" ? null : current);
    sourcePendingCallback.current(value);
  }, []);
  const masterPendingChange = useCallback((value: boolean) => {
    setResponsibilityLock(current => value ? "master-reference" : current === "master-reference" ? null : current);
    sourcePendingCallback.current(value);
  }, []);
  const load = useCallback(async () => {
    const current = authorityRevision.current, reading = ++loadRevision.current;
    const [workspace, sources, products] = await Promise.all([request<Workspace>(base), request<{ items: Evidence[] }>(`${base}/evidence`), request<ProductCatalog>(`${base}/products`)]);
    if (!live.current || current !== authorityRevision.current || reading !== loadRevision.current) return;
    setData(workspace); setEvidence(sources.items); setCatalog(products);
  }, [base]);
  useEffect(() => {
    let live = true;
    const current = authorityRevision.current;
    void load().catch(failure => { if (live && current === authorityRevision.current) { if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message); else setError(failure.message); } });
    return () => { live = false; };
  }, [load, clearAuthority]);
  useEffect(() => {
    if (!data || !catalog || tab !== 0 || !/^#(?:work|research)-/.test(window.location.hash)) return;
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [data, catalog, tab]);
  const act = async (work: () => Promise<unknown>) => { const current = authorityRevision.current; setBusy(true); setError(null); try { await work(); if (live.current && current === authorityRevision.current) await load(); } catch (failure) { if (live.current && current === authorityRevision.current) { if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message); else setError(failure instanceof Error ? failure.message : "操作失败"); } } finally { if (live.current && current === authorityRevision.current) setBusy(false); } };
  useProductWorkUpdates(base, load, { paused: busy || !!responsibilityLock || !!formKind || !["topics", "overview"].includes(view), onError: failure => { if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message); else setError("数据暂未更新，可重试读取。"); } });
  if (!data || !catalog) return <div className="space-y-4">{directoryBreadcrumb}<p className="text-sm">{error ?? "正在加载品类…"}</p>{error && <Button variant="outline" onClick={() => void act(load)}>重试</Button>}</div>;
  if (legacyLine && !["", "all"].includes(legacyLine) && !catalog.nodes.some(node => node.id === legacyLine && node.level === "line")) return <div className="space-y-4">{directoryBreadcrumb}<p role="alert" className="text-sm text-destructive">链接中的品类不存在或当前无权访问。请重新选择范围。</p><Button variant="outline" disabled={paiPending} onClick={() => { if (!paiPending) navigateWorkspace({ line: null }); }}>返回此品类</Button></div>;
  const name = (id: string | null) => data.members.find((member) => member.id === id)?.display_name ?? "未指定 / 成员已失效";
  const productLines = catalog.nodes.filter((node) => node.level === "line");
  const scopeName = (lineId: string | null) => lineId ? productLines.find((node) => node.id === lineId)?.name ?? "品类" : "品类共同研究";
  const matchesScope = (lineId: string | null) => scopeFilter === "all" || (lineId ?? "") === scopeFilter;
  const scopedMembers = (lineId: string | null) => lineId ? data.members.filter((member) => catalog.members.some((grant) => grant.product_line_id === lineId && grant.user_id === member.id && grant.access !== "viewer")) : data.members;
  const canWork = (lineId: string | null) => data.can_contribute && (!lineId || catalog.line_access[lineId]?.can_contribute === true);
  const visibleResearch = data.research.filter((task) => matchesScope(task.product_line_id));
  const visibleWork = data.work_items.filter((item) => matchesScope(item.product_line_id));

  const categoryLine = catalog.category_line_id ?? data.space.category_line_id ?? productLines[0]?.id ?? "";
  const formLine = categoryLine;
  const navigateTab = (next: string) => { if (!paiPending && !responsibilityLock) navigateWorkspace({ tab: next }); };
  const scopeValue = { scope: scopeFilter, setScope: () => {}, categoryLineId: categoryLine };
  return <ProductWorkScopeContext.Provider value={scopeValue}><ProductReadingProvider base={base} paused={busy || !!responsibilityLock || !!formKind} onAuthorityLost={clearAuthority}><section className="min-w-0 space-y-[18px] text-[13px]" data-product-workspace>
    <header className="space-y-3">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">{directoryBreadcrumb}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><h1 className="text-lg font-semibold">{data.space.title}</h1><p className="mt-1 text-sm text-muted-foreground">{view === "topics" ? "查看本品类的待办、研究成果和下一动作。" : data.space.user_groups.join("、") + (data.space.regions.length ? " · " + data.space.regions.join("、") : "")}</p></div>
        <div className="flex flex-wrap items-center gap-2">{view === "proposals" && !search.get("proposal") && data.can_contribute && <Button disabled={!!responsibilityLock || paiPending} onClick={() => openXiaopai({goal:"proposal"})}><ChatCircleDotsIcon aria-hidden="true"/>立项提案</Button>}{view !== "proposals" && <><Button variant="outline" size="sm" onClick={() => openXiaopai()}><ChatCircleDotsIcon aria-hidden="true"/>召唤小Pai</Button><Button size="sm" variant="ghost" disabled={!!responsibilityLock} onClick={() => navigateTab("proposals")}>立项提案</Button></>}<details className="relative"><summary className="min-h-9 cursor-pointer list-none rounded-lg px-3 py-2 text-xs text-muted-foreground hover:bg-muted">更多操作</summary><div className="absolute right-0 z-20 mt-1 flex w-48 flex-col rounded-lg border bg-card p-1 shadow-md"><Button variant="ghost" size="sm" className="justify-start" disabled={!!responsibilityLock || paiPending} onClick={() => navigateTab(view === "settings" ? "proposals" : "settings")}><GearSixIcon aria-hidden="true"/>{view === "settings" ? "返回品类资料" : "品类设置"}</Button><Button variant="ghost" size="sm" className="justify-start" disabled={!!responsibilityLock || paiPending} onClick={() => navigateTab("matrix")}>布局与路线图</Button><Button variant="ghost" size="sm" className="justify-start" disabled={!!responsibilityLock || paiPending} onClick={() => navigateTab("topics")}>专业资料</Button>{data.can_restore && <CategoryLifecycleAction space={data.space} disabled={busy || !!responsibilityLock || paiPending} onChanged={saved => { onLifecycleChanged(saved); if (saved.lifecycle === "active") void load().catch(failure => clearAuthority(failure.message)); }} onPendingChange={value => { setBusy(value); sourcePendingCallback.current(value); }}/>}<Button aria-label="刷新工作与来源" variant="ghost" size="sm" className="justify-start" disabled={busy || !!responsibilityLock} onClick={() => void act(load)}><ArrowClockwiseIcon aria-hidden="true"/>重新读取</Button></div></details></div>
      </div>
    </header>
    <WorkResponsibilityLanding spaceId={spaceId}/>
    {view !== "topics" && view !== "settings" && view !== "proposals" && <>
      <div className="hidden flex-wrap gap-1 border-b sm:flex" role="tablist" aria-label="产品管理工作区" onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || paiPending || responsibilityLock) return;
        event.preventDefault();
        const index = productViews.findIndex(([key]) => key === selectedView);
        const next = event.key === "Home" ? 0 : event.key === "End" ? productViews.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + productViews.length) % productViews.length;
        navigateTab(productViews[next][0]);
        document.getElementById(`product-tab-${productViews[next][0]}`)?.focus();
      }}>{productViews.map(([key, label]) => <Button key={key} id={`product-tab-${key}`} role="tab" tabIndex={selectedView === key ? 0 : -1} aria-controls="product-view-content" aria-selected={selectedView === key} variant="ghost" size="sm" className={cn("rounded-none border-b-2 border-transparent px-3", selectedView === key && "border-b-primary font-semibold text-primary")} disabled={!!responsibilityLock || paiPending} onClick={() => navigateTab(key)}>{label}</Button>)}</div>
      <label className="block text-sm sm:hidden">品类工作视图<select className={field} disabled={!!responsibilityLock || paiPending} value={selectedView} onChange={event => navigateTab(event.target.value)}>{productViews.map(([key, label]) => <option key={key} value={key}>{label}</option>)}{!productViews.some(([key]) => key === selectedView) && <option value={selectedView}>{tabs[tab] ?? "更多工作"}</option>}</select></label>
    </>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div id="product-view-content" role={productViews.some(([key]) => key === selectedView) ? "tabpanel" : undefined} aria-labelledby={productViews.some(([key]) => key === selectedView) ? `product-tab-${selectedView}` : undefined}>
    {view === "proposals" ? <ProductProposals onCatalogChanged={load} base={base} workspace={data} catalog={catalog} evidence={evidence} proposalId={search.get("proposal")} onAuthorityLost={clearAuthority} onPendingChange={candidatePendingChange}/> : view === "topics" ? <ProductSpaceOverview base={base} workspace={data} catalog={catalog} evidence={evidence} scope="all" onAuthorityLost={clearAuthority} onPendingChange={candidatePendingChange}/> : view === "overview" ? <ProductSpaceOverview base={base} workspace={data} catalog={catalog} evidence={evidence} scope={scopeFilter} onAuthorityLost={clearAuthority} onPendingChange={candidatePendingChange}/> : view === "settings" ? <>
      <SpaceSettings workspace={data} base={base} busy={busy || !!responsibilityLock} act={work => act(async () => { const saved = await work(); if (saved && typeof saved === "object" && "lifecycle" in saved) onLifecycleChanged(saved as Space); return saved; })}/>
      <WorkResponsibility spaceId={spaceId} kind="space" recordId={spaceId} disabled={busy || (!!responsibilityLock && responsibilityLock !== "space")} onLock={value => setResponsibilityLock(value ? "space" : null)} onChanged={load}/>
    <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">品类成员与权限</summary><ul className="mt-3 space-y-2 text-sm">{data.members.map((member) => <li key={member.id} className="flex items-center gap-3"><span>{member.display_name} · {accessLabels[member.access] ?? member.access}</span>{data.can_manage && member.id !== data.space.owner_user_id && <Button size="sm" variant="outline" disabled={busy || !!responsibilityLock} onClick={() => void act(() => request(`${base}/members/${member.id}`, "PUT", { access: null }))}>移除访问</Button>}</li>)}</ul>
      {data.can_manage && <form className="mt-3 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void act(() => request(`${base}/members/${form.get("user")}`, "PUT", { access: form.get("access") })); }}><label className="text-sm">成员<select required name="user" className={field}>{data.available_members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label><label className="text-sm">访问范围<select name="access" className={field}><option value="contributor">协作</option><option value="viewer">只读</option><option value="manager">管理（同时受岗位权限限制）</option></select></label><Button className="self-end" disabled={busy || !!responsibilityLock}>保存成员权限</Button></form>}
    </details>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => navigateTab("measurement")} disabled={!!responsibilityLock}>成效与投入</Button>{canEvaluate && <Button variant="outline" onClick={() => navigateTab("evaluation")} disabled={!!responsibilityLock}>能力评测</Button>}</div>
    </> : <>
    {[0, 1, 2, 3, 4, 5, 7].includes(tab) && <div className="space-y-3"><Button size="sm" variant="ghost" disabled={!!responsibilityLock || paiPending} aria-expanded={aiOpen || !!search.get("run")} onClick={() => setAiOpen(!aiOpen)}>资料核对与分析记录</Button>{(aiOpen || search.get("run")) && <ProductAiPreparation key={`${spaceId}:${tab}`} base={base} initialRunId={search.get("run") ?? undefined} initialLine={categoryLine} onLineChange={() => {}} capability={({ 0: "research_planning", 1: "competitor_analysis", 2: "market_analysis", 3: "opportunity_mapping", 4: "product_strategy", 5: "product_definition", 7: "experiment_design" } as Record<number, string>)[tab]} catalog={catalog} disabled={!!responsibilityLock || paiPending}/>}</div>}
    {[3,4].includes(tab) && <div className="flex flex-wrap gap-2" aria-label="机会与策略视图"><Button variant={tab === 3 ? "outline" : "ghost"} size="sm" onClick={() => navigateTab("opportunities")} disabled={!!responsibilityLock}>机会与方案</Button><Button variant={tab === 4 ? "outline" : "ghost"} size="sm" onClick={() => navigateTab("strategies")} disabled={!!responsibilityLock}>策略取舍</Button></div>}
    {tab === 10 ? canEvaluate ? <ProductShadowEvaluation base={base} disabled={!!responsibilityLock && responsibilityLock !== "evaluation"} onPendingChange={evaluationPendingChange} onAuthorityLost={clearAuthority}/> : <p role="alert" className="text-sm text-destructive">能力评测仅允许当前租户模型管理员办理。</p> : tab === 9 ? <ResearchMeasurement spaceId={spaceId} workspace={data} catalog={catalog}/> : tab === 8 ? <DefinitionExports base={base}/> : tab === 5 ? <DefinitionWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "definition" : null)}/> : tab === 4 ? <StrategyWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "strategy" : null)}/> : tab === 7 ? <ExperimentWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "experiment" : null)}/> : tab === 3 ? <OpportunityTree base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "opportunity" : null)}/> : tab === 2 ? <MarketSegments base={base} workspace={data} catalog={catalog} evidence={evidence} onAuthorityLost={clearAuthority} onPendingChange={marketPendingChange}/> : tab === 1 ? <CompetitorWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} /> : tab === 6 ? <><fieldset className="min-w-0" disabled={!!responsibilityLock}><ProductMatrix base={base} catalog={catalog} initialRecordId={search.get("record_id") ?? undefined} initialRunId={search.get("run") ?? undefined}/><ProductRoadmap base={base} catalog={catalog} workspace={data} evidence={evidence}/></fieldset><ProductTree evidence={evidence} catalog={catalog} workspace={data} base={base} busy={busy || (!!responsibilityLock && !["node", "master-reference"].includes(responsibilityLock))} act={act} refresh={load} onAuthorityLost={clearAuthority} onMasterPendingChange={masterPendingChange} onResponsibilityLock={value => setResponsibilityLock(value ? "node" : null)}/></> : tab !== 0 ? <div role="alert" className="rounded-md border p-4 text-sm"><p>此工作视图不存在或尚未接入。</p><p className="mt-1 text-muted-foreground">当前可在研究区登记问题、引用证据并分派专业评审或实验准备工作。</p></div> : <>
      <p className="text-sm text-muted-foreground">研究支持资料采集、搜索、页面订阅和专业协作。小Pai可核对本次资料与分析历史；分析开放状态及未完成项在分析记录中显示。</p>

      {data.can_contribute && <div className="flex flex-wrap gap-2"><Button onClick={() => openXiaopai()}><ChatCircleDotsIcon aria-hidden="true"/>交代研究目标</Button><Button size="sm" variant="outline" onClick={() => setFormKind(formKind === "research" ? null : "research")}>手动建研究任务</Button><Button size="sm" variant="outline" onClick={() => setFormKind(formKind === "work" ? null : "work")}>分派专业工作</Button></div>}
      {formKind && <form key={formKind} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2" onSubmit={(event) => {
        event.preventDefault(); const form = new FormData(event.currentTarget);
        const common = { owner_user_id: String(form.get("owner") ?? "") || null, product_line_id: categoryLine || null };
        const body = formKind === "research" ? { ...common, question: String(form.get("question")).trim(), user_groups: data.space.user_groups, regions: data.space.regions, time_scope: String(form.get("time_scope")).trim(), method: String(form.get("method")).trim(), expected_decision: String(form.get("expected_decision")).trim(), stop_conditions: lines(String(form.get("stop_conditions"))) } : { ...common, title: String(form.get("title")).trim(), action_type: String(form.get("action_type")), receiver_user_id: String(form.get("receiver") ?? "") || null, expected_output: String(form.get("expected_output")).trim(), completion_criteria: String(form.get("completion_criteria")).trim(), due_at: form.get("due") ? new Date(String(form.get("due"))).toISOString() : null };
        const kind = formKind;
        void act(async () => { await request(`${base}/${kind === "research" ? "research" : "work-items"}`, "POST", { ...body, request_id: stableId(body) }); setFormKind(null); });
      }}>
        {formKind === "research" ? <>
          <label className="text-sm sm:col-span-2">研究问题<textarea required name="question" maxLength={2048} className={field} /></label>
          <label className="text-sm">时间范围<input required name="time_scope" className={field} placeholder="例如近一年，或明确历史区间" /></label>
          <label className="text-sm">研究方法<input required name="method" className={field} placeholder="访谈、公开资料对比、实测等" /></label>
          <label className="text-sm">支持什么决定<textarea required name="expected_decision" className={field} /></label>
          <label className="text-sm">停止条件（每行一项）<textarea required name="stop_conditions" className={field} placeholder="明确证据范围、时间边界或未解决项处理方式" /></label>
        </> : <>
          <label className="text-sm">工作标题<input required name="title" maxLength={512} className={field} /></label>
          <label className="text-sm">工作类型<select name="action_type" className={field}>{Object.entries(actionLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="text-sm">预期输出<textarea required name="expected_output" maxLength={2048} className={field} /></label>
          <label className="text-sm">完成判据<textarea required name="completion_criteria" maxLength={2048} className={field} /></label>
          <MemberSelect key={`receiver:${formLine}`} members={scopedMembers(formLine || null)} name="receiver" label="接收人（专业审查、实验和交接准备需要）" />
          <label className="text-sm">目标时间<input type="datetime-local" name="due" className={field} /></label>
        </>}
        <MemberSelect key={`owner:${formLine}`} members={scopedMembers(formLine || null)} name="owner" label="负责人" required={formKind === "research"} defaultValue={data.current_user_id} />
        <div className="flex items-end gap-2"><Button disabled={busy || !canWork(formLine || null)}>创建</Button><Button type="button" variant="outline" onClick={() => setFormKind(null)}>取消</Button></div>
      </form>}
      <section className="space-y-2"><h3 className="text-xs font-semibold text-muted-foreground">研究任务</h3>{visibleResearch.length === 0 && <p className="text-sm text-muted-foreground">此范围尚无研究任务。</p>}{visibleResearch.map((task) => <ReadingRecord key={task.id} id={`research-${task.id}`} title={task.question} meta={`${stateLabels[task.state]} · ${name(task.owner_user_id)} · 证据 ${task.sources.length} 条 · 支持决定：${task.expected_decision}`} tone={task.state === "completed" ? "ok" : "active"} action={task.state === "active" ? "提交结论" : "查看研究"} disabled={busy || !!responsibilityLock}><ResearchCard key={`${task.id}:${task.version}`} task={task} scopeLabel={scopeName(task.product_line_id)} ownerName={name(task.owner_user_id)} canAct={canWork(task.product_line_id) && task.owner_user_id === data.current_user_id} evidence={evidence} busy={busy || !!responsibilityLock} act={act} base={base} onAuthorityLost={clearAuthority}/><WorkResponsibility spaceId={spaceId} kind="research" recordId={task.id} disabled={busy || !!responsibilityLock && responsibilityLock !== task.id} onLock={value => setResponsibilityLock(value ? task.id : null)} onChanged={load}/></ReadingRecord>)}</section>
      <ProductResearchEntries base={base} workspace={data} evidence={evidence} scope={scopeFilter} onAuthorityLost={clearAuthority}/>
      <section className="space-y-3"><h3 className="font-semibold">专业协作与补证</h3>{visibleWork.length === 0 && <p className="text-sm text-muted-foreground">此范围尚无专业工作项。</p>}{visibleWork.map((item) => <ReadingRecord id={`work-${item.id}`} key={item.id} title={item.title} meta={`${stateLabels[item.state]} · ${scopeName(item.product_line_id)} · ${item.expected_output}`} action={item.state === "submitted" ? "核对并接收" : "去办理"} tone={item.state === "completed" ? "ok" : "pending"}><WorkCard key={`${item.id}:${item.version}`} item={item} scopeLabel={scopeName(item.product_line_id)} workspace={{ ...data, members: scopedMembers(item.product_line_id), can_contribute: canWork(item.product_line_id), can_manage: data.can_manage && (!item.product_line_id || catalog.line_access[item.product_line_id]?.can_manage === true) }} evidence={evidence} busy={busy || !!responsibilityLock} act={act} base={base} onAuthorityLost={clearAuthority}/><WorkResponsibility spaceId={spaceId} kind="work" recordId={item.id} disabled={busy || !!responsibilityLock && responsibilityLock !== item.id} onLock={value => setResponsibilityLock(value ? item.id : null)} onChanged={load}/></ReadingRecord>)}</section>
      <details className="space-y-4 rounded-lg border p-4" open={!!search.get("run") || responsibilityLock === `rfq:${scopeFilter}` || responsibilityLock === "subscription" ? true : undefined}><summary className="cursor-pointer text-sm font-medium">资料与采集</summary><div className="mt-4 space-y-5">
      <ProductSourceFiles key={`${spaceId}:${scopeFilter}`} base={base} initialRunId={search.get("run") ?? undefined} lineId={scopeFilter === "all" ? null : scopeFilter || null} disabled={!!responsibilityLock && responsibilityLock !== `rfq:${scopeFilter}`} canEdit={canWork(scopeFilter === "all" ? null : scopeFilter || null)} onPendingChange={value => { setResponsibilityLock(current => value ? `rfq:${scopeFilter}` : current === `rfq:${scopeFilter}` ? null : current); onSourcePendingChange(value); }}/>
      <ResearchCollection onAuthorityLost={clearAuthority} onResponsibilityLock={value => setResponsibilityLock(value ? "subscription" : null)} base={base} workspace={data} evidence={evidence} lineId={scopeFilter === "all" ? null : scopeFilter || null} canCollect={data.can_collect && canWork(scopeFilter === "all" ? null : scopeFilter || null)} refresh={load} />
      </div></details>
    </>}

    </>}
    </div>
  </section></ProductReadingProvider></ProductWorkScopeContext.Provider>;
}

function ResearchCard({ task, scopeLabel, ownerName, canAct, evidence, busy, act, base, onAuthorityLost }: { task: Research; scopeLabel: string; ownerName: string; canAct: boolean; evidence: Evidence[]; busy: boolean; act: (work: () => Promise<unknown>) => Promise<void>; base: string; onAuthorityLost: (message: string) => void }) {
  const [note, setNote] = useState(""); const [findings, setFindings] = useState(""); const [unresolved, setUnresolved] = useState(""); const [selected, setSelected] = useState<string[]>([]);
  const selectedSources = evidence.filter((item) => selected.includes(item.id)).map((item) => item.reference);
  return <article className="space-y-2"><h4 className="font-medium">{task.question}</h4><p className="text-sm">{stateLabels[task.state]} · {ownerName} · {scopeLabel} · v{task.version}</p><p className="text-sm">{task.method} · {task.time_scope}</p><p className="text-sm">支持决定：{task.expected_decision}</p><p className="text-xs text-muted-foreground">停止条件：{task.stop_conditions.join("；")}</p>
    {task.source_finding_id && <p className="text-xs text-muted-foreground">来源：AI 研究候选，经人工接受并独立应用；不代表研究已完成。</p>}
    {task.conclusion && <div className="space-y-1 rounded-md bg-muted p-3 text-sm"><p>{task.conclusion}</p>{task.findings.map((item, i) => <p key={i}>发现：{item}</p>)}{task.unresolved.map((item, i) => <p key={i}>未解决：{item}</p>)}<p>关联证据 {task.sources.length} 项</p>{task.sources.length === 0 && <p className="text-muted-foreground">历史结论未关联原始快照，待补证核对。</p>}<SourceCitations key={`${base}:${task.sources.map(ref => `${ref.ref_id}:${ref.digest}`).join(",")}`} base={base} references={task.sources} evidence={evidence} onAuthorityLost={onAuthorityLost}/></div>}
    {task.state === "cancelled" && task.cancellation_reason && <p className="text-sm">取消原因：{task.cancellation_reason}</p>}
    {canAct && task.state === "draft" && <Button size="sm" disabled={busy} onClick={() => void act(() => request(`${base}/research/${task.id}/start`, "POST", { ...command(task), research_task_id: task.id }))}>开始研究</Button>}
    {canAct && ["draft", "active"].includes(task.state) && <details className="space-y-2"><summary className="cursor-pointer text-sm">{task.state === "active" ? "提交结论或取消" : "取消研究"}</summary><label className="block text-sm">结论 / 取消原因<textarea maxLength={2048} className={field} value={note} onChange={(e) => setNote(e.target.value)} /></label>{task.state === "active" && <>
      <label className="block text-sm">有依据的发现（每行一项）<textarea className={field} value={findings} onChange={(e) => setFindings(e.target.value)} /></label><label className="block text-sm">未解决事项（每行一项）<textarea className={field} value={unresolved} onChange={(e) => setUnresolved(e.target.value)} /></label><EvidencePicker options={evidence} selected={selected} onChange={setSelected} />
      <p className="text-xs text-muted-foreground">研究结论需至少关联一条原始证据快照；无可用证据时，可取消研究并保留原因。</p>
      <Button size="sm" disabled={busy || !note.trim() || selectedSources.length === 0} onClick={() => void act(() => request(`${base}/research/${task.id}/conclude`, "POST", { ...command(task), research_task_id: task.id, conclusion: note.trim(), findings: lines(findings), unresolved: lines(unresolved), source_refs: selectedSources }))}>提交研究结论</Button>
    </>}<Button size="sm" variant="outline" disabled={busy || !note.trim()} onClick={() => void act(() => request(`${base}/research/${task.id}/cancel`, "POST", { ...command(task), reason: note.trim() }))}>取消并保留原因</Button></details>}
  </article>;
}

function WorkCard({ item, scopeLabel, workspace, evidence, busy, act, base, onAuthorityLost }: { item: WorkItem; scopeLabel: string; workspace: Workspace; evidence: Evidence[]; busy: boolean; act: (work: () => Promise<unknown>) => Promise<void>; base: string; onAuthorityLost: (message: string) => void }) {
  const [note, setNote] = useState(""); const [selected, setSelected] = useState<string[]>([]);
  const owner = workspace.current_user_id === item.owner_user_id; const receiver = workspace.current_user_id === item.receiver_user_id;
  const name = (id: string | null) => workspace.members.find((member) => member.id === id)?.display_name ?? "待指定 / 已失效";
  const run = (action: string) => act(() => request(`${base}/work-items/${item.id}/actions`, "POST", { ...command(item), action, note: action === "start" ? "开始办理" : note.trim(), evidence: action === "submit" ? evidence.filter((source) => selected.includes(source.id)).map((source) => source.reference) : [] }));
  return <article id={`work-${item.id}`} className="space-y-2 rounded-lg border p-4"><h4 className="font-medium">{item.title}</h4><p className="text-sm">{actionLabels[item.action_type]} · {stateLabels[item.state]} · {scopeLabel} · {name(item.owner_user_id)}</p><p className="text-sm">输出：{item.expected_output}</p><p className="text-sm">完成判据：{item.completion_criteria}</p><p className="text-xs text-muted-foreground">{item.acceptance_required ? `接收人：${name(item.receiver_user_id)}` : "资料补证完成后直接记录结果"}{item.due_at ? ` · 目标 ${new Date(item.due_at).toLocaleString()}` : ""}</p>{item.result_note && <p className="text-sm">办理记录：{item.result_note}</p>}<SourceCitations key={`${base}:${item.evidence.map(ref => `${ref.ref_id}:${ref.digest}`).join(",")}`} base={base} references={item.evidence} evidence={evidence} onAuthorityLost={onAuthorityLost}/>
    {workspace.can_manage && ["pending_assignment", "ready"].includes(item.state) && <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void act(() => request(`${base}/work-items/${item.id}/assignment`, "POST", { ...command(item), owner_user_id: form.get("owner"), receiver_user_id: form.get("receiver") || null })); }}><MemberSelect members={workspace.members} name="owner" label="负责人" required defaultValue={item.owner_user_id ?? ""} /><MemberSelect members={workspace.members} name="receiver" label="接收人" required={item.acceptance_required} defaultValue={item.receiver_user_id ?? ""} /><Button size="sm" disabled={busy}>确认分派</Button></form>}
    {workspace.can_contribute && owner && item.state === "ready" && <Button size="sm" disabled={busy} onClick={() => void run("start")}>开始办理</Button>}
    {workspace.can_contribute && !["completed", "cancelled"].includes(item.state) && (owner || receiver || workspace.can_manage) && <div className="space-y-2"><label className="block text-sm">结果、接收意见或取消原因<textarea maxLength={2048} className={field} value={note} onChange={(e) => setNote(e.target.value)} /></label>
      {owner && item.state === "in_progress" && <><EvidencePicker options={evidence} selected={selected} onChange={setSelected} /><Button size="sm" disabled={busy || !note.trim() || selected.length === 0} onClick={() => void run("submit")}>{item.acceptance_required ? "提交接收" : "提交完成证据"}</Button></>}
      {receiver && item.state === "submitted" && <div className="flex gap-2"><Button size="sm" disabled={busy || !note.trim()} onClick={() => void run("accept")}>确认接收</Button><Button size="sm" variant="outline" disabled={busy || !note.trim()} onClick={() => void run("return")}>退回补充</Button></div>}
      {(owner || workspace.can_manage) && <Button size="sm" variant="outline" disabled={busy || !note.trim()} onClick={() => void run("cancel")}>取消工作项</Button>}
    </div>}
    <WorkHistory base={base} workId={item.id} version={item.version} evidence={evidence} />
  </article>;
}
