"use client";

import { ArrowRightIcon, ChatCircleDotsIcon, SparkleIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { openXiaopai } from "@/components/ai/xiaopai-launcher";
import { Button } from "@/components/ui/button";
import { ProductEvidenceProposal } from "./product-evidence-proposal";
import { ProductResearchProposal } from "./product-research-proposal";
import { productWorkHref } from "./product-work-navigation";
import { useProductWorkUpdates } from "./product-work-scope";
import { ProductRequestError, request, stateLabels, type Evidence, type ProductCatalog, type Workspace } from "./product-work-api";

const capabilities: Record<string, { title: string; tab: string }> = {
  research_planning: { title: "研究计划", tab: "research" },
  rfq_requirements: { title: "客户需求", tab: "research" },
  competitor_analysis: { title: "竞品观察", tab: "competitors" },
  market_analysis: { title: "用户细分", tab: "segments" },
  opportunity_mapping: { title: "机会与方案", tab: "opportunities" },
  experiment_design: { title: "实验计划", tab: "experiments" },
  product_strategy: { title: "产品策略", tab: "strategies" },
  product_definition: { title: "产品定义", tab: "definitions" },
};
type Candidate = { id: string; run_id: string; title: string; summary: string; status: "pending_review" | "accepted"; capability: string; product_line_id: string | null; created_at: string };
type Run = { run_id: string; status: string; capability: string; product_line_id: string | null; created_at: string; missing: string[] };
type ProfessionalWork = { id: string; market_space_id: string; product_line_id: string | null; state: string; hypothesis?: string; title?: string; decision_reason?: string; content?: { title?: string; change_reason?: string } };
type MyWork = { experiments?: ProfessionalWork[]; strategies?: ProfessionalWork[]; definitions?: ProfessionalWork[]; pages?: Record<string, { next_offset?: number | null }> };
type Attention = { professional?: MyWork; candidates: Candidate[]; runs: Run[]; limited: boolean; unavailable: boolean };
const runLabels: Record<string, string> = { queued: "排队中", running: "分析中", succeeded: "分析已保存", degraded: "未完成", failed: "失败", cancelled: "已取消" };
const matches = (line: string | null, scope: string) => scope === "all" || (line ?? "") === scope;

function myWork(workspace: Workspace, catalog: ProductCatalog, scope: string) {
  const canWork = (line: string | null) => workspace.can_contribute && (!line || catalog.line_access[line]?.can_contribute);
  const canManage = (line: string | null) => workspace.can_manage && (!line || catalog.line_access[line]?.can_manage);
  const research = workspace.research.filter(item => matches(item.product_line_id, scope) && canWork(item.product_line_id) && item.owner_user_id === workspace.current_user_id && ["draft", "active"].includes(item.state));
  const work = workspace.work_items.filter(item => matches(item.product_line_id, scope) && canWork(item.product_line_id) && ((item.state === "submitted" && item.acceptance_required && item.receiver_user_id === workspace.current_user_id) || (["ready", "in_progress"].includes(item.state) && item.owner_user_id === workspace.current_user_id) || (item.state === "pending_assignment" && canManage(item.product_line_id))));
  return { research, work };
}

export function ProductTopicList({ workspace, catalog, onOpen, onManualCreate, disabled }: { workspace: Workspace; catalog: ProductCatalog; onOpen: (line: string) => void; onManualCreate: () => void; disabled: boolean }) {
  const lines = catalog.nodes.filter(node => node.level === "line");
  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-sm font-semibold">产品主题</h2><div className="flex flex-wrap gap-2"><Button onClick={openXiaopai}><ChatCircleDotsIcon aria-hidden="true"/>交代新目标</Button>{catalog.can_create_line && <Button variant="ghost" onClick={onManualCreate} disabled={disabled}>手动登记产品线</Button>}</div></div>
    {lines.length === 0 && <div className="space-y-3 rounded-lg border border-dashed p-6"><p className="text-sm">此空间还没有产品主题。</p><p className="text-sm text-muted-foreground">向小Pai说明产品目标，核对已有资料；需要登记归属时可使用产品线入口。</p><Button variant="outline" onClick={openXiaopai}>从一个目标开始</Button></div>}
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{lines.map(line => {
      const tasks = workspace.research.filter(item => item.product_line_id === line.id);
      const active = tasks.filter(item => item.state === "active");
      const todo = myWork(workspace, catalog, line.id);
      const count = todo.research.length + todo.work.length;
      return <article key={line.id} className="flex min-w-0 flex-col rounded-lg border bg-card p-5"><div className="flex items-start justify-between gap-3"><h3 className="break-words text-base font-medium">{line.name}</h3><span className="shrink-0 text-xs text-muted-foreground">{({ proposed: "拟议", developing: "开发中", available: "在售", retired: "已退役" } as Record<string, string>)[line.lifecycle] ?? "产品线"}</span></div><p className="mt-1 text-xs text-muted-foreground">{line.code}{line.regions?.length ? ` · ${line.regions.join("、")}` : ""}</p><p className="mt-5 text-sm">{active.length ? `${active.length} 项研究正在推进` : tasks.length ? `${tasks.length} 项研究，查看成果与未决问题` : "尚无研究任务"}</p><p className="mt-2 text-xs text-muted-foreground">{count ? `${count} 项工作待我办理` : "当前没有已登记的本人工作待办"}</p><Button variant="outline" className="mt-5 self-start" disabled={disabled} onClick={() => onOpen(line.id)}>{count ? "查看待办与下一动作" : "进入主题工作台"}<ArrowRightIcon aria-hidden="true"/></Button></article>;
    })}</div>
    <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-5"><div><h3 className="text-sm font-medium">空间共同研究</h3><p className="mt-1 text-xs text-muted-foreground">未绑定产品线的来源、研究和专业工作</p></div><Button variant="outline" disabled={disabled} onClick={() => onOpen("")}>进入共同研究</Button><Button variant="ghost" disabled={disabled} onClick={() => onOpen("all")}>查看空间全部工作</Button></div>
  </div>;
}

function Panel({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return <section className="min-w-0 overflow-hidden rounded-lg border bg-card"><header className="flex items-center justify-between gap-3 border-b px-4 py-3"><h2 className="text-sm font-semibold">{title}</h2>{count !== undefined && <span className="font-mono text-xs text-muted-foreground">{count}</span>}</header><div className="divide-y">{children}</div></section>;
}
function Item({ title, description, status, href, action }: { title: string; description: string; status?: string; href: string; action: string }) {
  return <div className="space-y-2 px-4 py-4"><div className="flex flex-wrap items-start justify-between gap-2"><h3 className="break-words text-sm font-medium">{title}</h3>{status && <span className="text-xs text-muted-foreground">{status}</span>}</div><p className="break-words text-sm leading-6 text-muted-foreground">{description}</p><Link href={href} className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-primary sm:min-h-9">{action}<ArrowRightIcon aria-hidden="true" size={14}/></Link></div>;
}

export function ProductSpaceOverview({ base, workspace, catalog, evidence, scope, onAuthorityLost, onPendingChange }: { base: string; workspace: Workspace; catalog: ProductCatalog; evidence: Evidence[]; scope: string; onPendingChange: (value: boolean) => void; onAuthorityLost: (message: string) => void }) {
  const [attention, setAttention] = useState<Attention | null>(null);
  const [error, setError] = useState("");
  const [writing, setWriting] = useState(false);
  const pendingChange = (value: boolean) => { setWriting(value); onPendingChange(value); };
  const [selected, setSelected] = useState<Candidate | null>(null);
  const live = useRef(true), revision = useRef(0);
  const reviewPanel = useRef<HTMLElement>(null), reviewTrigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (selected) { reviewPanel.current?.focus({ preventScroll: true }); reviewPanel.current?.scrollIntoView({ block: "start" }); } }, [selected]);
  useEffect(() => { live.current = true; return () => { live.current = false; revision.current += 1; }; }, []);
  const failure = useCallback((value: unknown) => {
    if (!live.current) return;
    if (value instanceof ProductRequestError && [401, 403].includes(value.status)) { revision.current += 1; setAttention(null); setSelected(null); onAuthorityLost(value.message); }
    else setError("AI 待办暂未更新，请重试读取；原工作仍可查看。");
  }, [onAuthorityLost]);
  const load = useCallback(async () => {
    const current = ++revision.current;
    try {
    const [data, professional] = await Promise.all([request<Attention>(`${base}/product-work-attention`, "POST", { product_line_id: scope === "all" ? null : scope || null, all_lines: scope === "all" }), request<MyWork>("my-work")]);
    if (!live.current || current !== revision.current) return;
    if (!Array.isArray(data.candidates) || !Array.isArray(data.runs)) throw new Error("待办回执不完整");
    setAttention({ ...data, professional }); setError("");
    } catch (error) { if (live.current && current === revision.current) throw error; }
  }, [base, scope]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- Asynchronous read; stale responses are revision-guarded.
  useEffect(() => { let active = true; void load().catch(error => { if (active) failure(error); }); return () => { active = false; }; }, [load, failure]);
  useProductWorkUpdates(base, load, { paused: !!selected, onError: failure });
  const mine = myWork(workspace, catalog, scope);
  const candidates = attention?.candidates ?? [];
  const professional = ([ ["experiments", "实验办理", "experiment"], ["strategies", "策略取舍", "strategy"], ["definitions", "定义与协审", "definition"] ] as const).flatMap(([collection, title, anchor]) => (attention?.professional?.[collection] ?? []).filter(item => item.market_space_id === workspace.space.id && matches(item.product_line_id, scope) && workspace.can_contribute && (!item.product_line_id || catalog.line_access[item.product_line_id]?.can_contribute)).map(item => ({ item, collection, title, anchor })));

  const href = (tab: string, line: string | null = scope === "all" ? null : scope || null, anchor?: string) => productWorkHref(workspace.space.id, tab, line, anchor);
  const runHref = (item: Run | Candidate) => `${href(capabilities[item.capability]?.tab ?? "research", item.product_line_id)}&run=${encodeURIComponent(item.run_id)}`;
  const activeResearch = workspace.research.filter(item => matches(item.product_line_id, scope) && item.state === "active");
  const activeWork = workspace.work_items.filter(item => matches(item.product_line_id, scope) && ["ready", "in_progress", "submitted"].includes(item.state));
  const scopedRefs = new Set([...workspace.research.filter(item => matches(item.product_line_id, scope)).flatMap(item => item.sources.map(ref => ref.ref_id)), ...workspace.work_items.filter(item => matches(item.product_line_id, scope)).flatMap(item => item.evidence.map(ref => ref.ref_id))]);
  const issues = evidence.filter(item => (scope === "all" || scopedRefs.has(item.id)) && (item.is_stale || item.superseded || item.has_conflict));
  const unresolved = workspace.research.filter(item => matches(item.product_line_id, scope) && item.unresolved.length > 0);
  const gaps = (attention?.runs ?? []).filter(item => item.missing.length > 0);
  const lineName = (line: string | null) => catalog.nodes.find(node => node.id === line)?.name ?? "空间共同研究";
  return <div className="min-w-0 space-y-5">
    <Button variant="outline" className="min-h-11 w-full justify-start text-muted-foreground" onClick={openXiaopai}><ChatCircleDotsIcon aria-hidden="true"/>说出下一目标，或把资料交给小Pai…</Button>
    {error && <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive"><p>{error}</p><Button variant="outline" size="sm" onClick={() => void load().catch(failure)}>重试读取待办</Button></div>}
    <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        <Panel title="等待你裁决" count={attention ? candidates.length + mine.research.length + mine.work.length + professional.length : undefined}>
          {!attention && !error && <p role="status" className="px-4 py-4 text-sm text-muted-foreground">正在核对本人候选…</p>}
          {candidates.map(candidate => <article key={candidate.id} className="space-y-3 px-4 py-4"><div className="flex flex-wrap items-start gap-2"><span className="inline-flex items-center gap-1 text-xs text-primary"><SparkleIcon aria-hidden="true" size={14}/>AI 候选</span><h3 className="min-w-0 flex-1 break-words text-sm font-medium">{candidate.title}</h3><span className="text-xs text-pending">{candidate.status === "accepted" ? "已接受 · 待应用" : "待核对"}</span></div><p className="break-words text-sm leading-6 text-muted-foreground">{candidate.summary}</p><p className="text-xs text-muted-foreground">{lineName(candidate.product_line_id)} · {capabilities[candidate.capability]?.title ?? "产品工作"} · {new Date(candidate.created_at).toLocaleDateString()}</p>{candidate.capability === "rfq_requirements" ? <Link className="inline-flex min-h-11 items-center text-sm text-primary" href={runHref(candidate)}>核对需求候选</Link> : <Button size="sm" variant={selected?.id === candidate.id ? "outline" : "default"} disabled={writing} onClick={event => { reviewTrigger.current = event.currentTarget; setSelected(candidate); }}>{candidate.status === "accepted" ? "核对后独立应用" : "核对 / 修订候选"}</Button>}</article>)}
          {professional.map(({ item, collection, title, anchor }) => <Item key={`${collection}:${item.id}`} title={item.content?.title ?? item.title ?? item.hypothesis ?? title} description={item.content?.change_reason ?? item.decision_reason ?? "核对当前版本、依据与可办理动作。"} status={`${title} · ${({ draft: "草稿", in_review: "协审中", approved: "待开始", running: "执行中" } as Record<string, string>)[item.state] ?? item.state}`} href={href(collection, item.product_line_id, `${anchor}-${item.id}`)} action={collection === "experiments" ? "核对计划与结果" : "查看协审与发布条件"}/>)}
          {mine.work.map(item => <Item key={item.id} title={item.title} description={item.expected_output} status={stateLabels[item.state]} href={href("research", item.product_line_id, `work-${item.id}`)} action={item.state === "submitted" ? "核对并接收成果" : item.state === "pending_assignment" ? "分派负责人" : "去办理"}/>)}
          {mine.research.map(item => <Item key={item.id} title={item.question} description={item.expected_decision} status={stateLabels[item.state]} href={href("research", item.product_line_id, `research-${item.id}`)} action={item.state === "active" ? "核对并提交结论" : "开始研究"}/>)}
          {attention && !candidates.length && !mine.research.length && !mine.work.length && !professional.length && <p className="px-4 py-5 text-sm text-muted-foreground">当前没有等待你处理的事项。</p>}
          {Object.values(attention?.professional?.pages ?? {}).some(page => page.next_offset !== null && page.next_offset !== undefined) && <p className="px-4 py-3 text-xs text-muted-foreground">专业待办显示 My Work 最近一页，可在<a className="underline" href="/my-work">我的工作</a>继续查看。</p>}
          {attention?.limited && <p className="px-4 py-3 text-xs text-muted-foreground">当前显示最近 100 项本人候选；更早记录可在所属视图的分析记录中查阅。</p>}
          {attention?.unavailable && <p className="px-4 py-3 text-xs text-pending">部分原运行的来源或权限已变化，未显示其私有内容。</p>}
        </Panel>
        {selected && <section ref={reviewPanel} tabIndex={-1} aria-label="审阅所选候选" className="min-w-0 scroll-mt-16 space-y-3 outline-none"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">{selected.title}</h2><Button variant="ghost" size="sm" disabled={writing} onClick={() => { setSelected(null); reviewTrigger.current?.focus(); void load().catch(failure); }}>收起审阅</Button></div><p className="text-xs text-muted-foreground">核对固定来源，接受与正式应用分别办理。</p>{selected.capability === "research_planning" ? <ProductResearchProposal key={selected.run_id} base={base} runId={selected.run_id} disabled={writing} autoLoad onPendingChange={pendingChange} onAccessDenied={onAuthorityLost}/> : <ProductEvidenceProposal key={selected.run_id} base={base} runId={selected.run_id} disabled={writing} autoLoad onPendingChange={pendingChange} onAccessDenied={onAuthorityLost}/>}<Link className="inline-flex min-h-11 items-center text-sm text-primary" href={runHref(selected)}>查看原运行与来源依据</Link></section>}
        <Panel title="缺口与信号">
          {issues.slice(0, 6).map(item => <Item key={item.id} title={item.name} description={[item.has_conflict ? "来源存在冲突" : "", item.is_stale ? "来源已陈旧" : "", item.superseded ? "已有新版，原引用仍需复核" : ""].filter(Boolean).join("；")} href={href("research")} action="核对来源"/>)}
          {unresolved.slice(0, 6).map(item => <Item key={item.id} title={item.question} description={item.unresolved.join("；")} href={href("research", item.product_line_id, `research-${item.id}`)} action="补齐研究缺口"/>)}
          {gaps.slice(0, 4).map(item => <Item key={item.run_id} title={`${capabilities[item.capability]?.title ?? "分析"}缺项`} description={item.missing.join("；")} href={runHref(item)} action="核对分析缺项"/>)}
          {!issues.length && !unresolved.length && !gaps.length && <p className="px-4 py-5 text-sm text-muted-foreground">{attention ? "当前可读记录中没有已登记的缺口信号。" : error ? "分析缺口暂未取得，请重试读取待办。" : "正在读取分析缺口…"}</p>}
        </Panel>
      </div>
      <div className="min-w-0 space-y-5">
        <Panel title="进行中">
          {activeResearch.slice(0, 5).map(item => <Item key={item.id} title={item.question} description={`${workspace.members.find(member => member.id === item.owner_user_id)?.display_name ?? "原负责人"} · ${item.method}`} status="研究中" href={href("research", item.product_line_id, `research-${item.id}`)} action="查看工作"/>)}
          {activeWork.slice(0, 5).map(item => <Item key={item.id} title={item.title} description={item.expected_output} status={stateLabels[item.state]} href={href("research", item.product_line_id, `work-${item.id}`)} action="查看进展"/>)}
          {!activeResearch.length && !activeWork.length && <p className="px-4 py-5 text-sm text-muted-foreground">当前范围没有已开始的研究或专业工作。</p>}
        </Panel>
        <Panel title="AI 最近运行">
          {(attention?.runs ?? []).slice(0, 6).map(item => <Item key={item.run_id} title={capabilities[item.capability]?.title ?? "产品工作"} description={`${lineName(item.product_line_id)} · ${new Date(item.created_at).toLocaleString()}`} status={runLabels[item.status] ?? item.status} href={runHref(item)} action="查看原运行"/>)}
          {attention && !attention.runs.length && <p className="px-4 py-5 text-sm text-muted-foreground">当前没有可读的本人运行记录。</p>}
        </Panel>
      </div>
    </div>
  </div>;
}
