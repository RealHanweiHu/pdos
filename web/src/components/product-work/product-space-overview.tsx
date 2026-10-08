"use client";

import { ArrowRightIcon, SparkleIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { openXiaopai } from "@/components/ai/xiaopai-launcher";
import { ReadingPanel as Panel } from "./product-reading-ui";
import { useProductReading, inProductScope } from "./product-reading-context";
import { Button } from "@/components/ui/button";
import { ProductCandidateCard, type ProductItemCandidate } from "./product-candidate-card";
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
type Candidate = Partial<Pick<ProductItemCandidate, "parent_finding_id" | "item_position" | "item">> & { id: string; run_id: string; title: string; summary: string; status: "pending_review" | "accepted"; capability: string; product_line_id: string | null; created_at: string };
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
  const reading = useProductReading();
  const [queue, setQueue] = useState<Candidate[] | null>(null);
  const [professional, setProfessional] = useState<MyWork | null>(null);
  const live = useRef(true), revision = useRef(0);
  const base = `spaces/${workspace.space.id}`;
  useEffect(() => { live.current = true; return () => { live.current = false; revision.current += 1; }; }, []);
  const load = useCallback(async () => {
    const current = ++revision.current;
    try {
      const [data, work] = await Promise.all([request<Attention>(`${base}/product-work-attention`, "POST", { all_lines: true, product_line_id: null }), request<MyWork>("my-work")]);
      if (live.current && current === revision.current) { setQueue(Array.isArray(data.candidates) ? data.candidates : null); setProfessional(work); }
    } catch { if (live.current && current === revision.current) { setQueue(null); setProfessional(null); } }
  }, [base]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- Asynchronous read with stale response protection.
  useEffect(() => { void load(); }, [load]);
  const failure = useCallback(() => setQueue(null), []);
  useProductWorkUpdates(base, load, { paused: disabled, onError: failure });
  const lines = catalog.nodes.filter(node => node.level === "line");
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xs font-semibold text-muted-foreground">产品主题</h2>{catalog.can_create_line && <Button size="sm" variant="outline" onClick={onManualCreate} disabled={disabled}>新建产品主题</Button>}</div>
    {lines.length === 0 && <div className="space-y-3 rounded-lg border border-dashed p-5"><p className="text-sm">此空间还没有产品主题。</p><p className="text-xs text-muted-foreground">向小Pai交代产品目标，或登记产品主题后开始研究。</p><Button variant="outline" onClick={() => openXiaopai()}>从一个目标开始</Button></div>}
    <div className="space-y-3">{lines.map(line => {
      const tasks = workspace.research.filter(item => item.product_line_id === line.id);
      const todo = myWork(workspace, catalog, line.id);
      const candidateCount = queue?.filter(item => item.product_line_id === line.id).length;
      const professionalCount = (["experiments", "strategies", "definitions"] as const).reduce((sum, key) => sum + (professional?.[key] ?? []).filter(item => item.market_space_id === workspace.space.id && item.product_line_id === line.id && workspace.can_contribute && catalog.line_access[line.id]?.can_contribute).length, 0);
      const count = todo.research.length + todo.work.length + professionalCount + (candidateCount ?? 0);
      const next = candidateCount ? "裁决 AI 候选" : todo.work[0]?.state === "submitted" ? "接收专业成果" : todo.research[0]?.state === "active" ? "提交研究结论" : todo.research.length ? "开始研究" : "查看成果与证据缺口";
      return <button type="button" key={line.id} disabled={disabled} onClick={() => onOpen(line.id)} className="block w-full rounded-lg border bg-card px-[18px] py-4 text-left hover:border-primary/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"><div className="flex flex-wrap items-center gap-2.5"><h3 className="text-[15px] font-semibold">{line.name}</h3><span className="rounded-full border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">{({ proposed: tasks.some(item => item.state === "active") ? "研究中" : "拟议", developing: "开发中", available: "在售", retired: "已退役" } as Record<string, string>)[line.lifecycle] ?? "产品主题"}</span></div><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"><span>研究 <b className="font-mono font-semibold text-foreground">{tasks.length}</b></span>{([["competitors", "竞品"], ["segments", "细分"], ["opportunities", "机会"], ["experiments", "实验"]] as const).map(([key, label]) => { const items = inProductScope<{ product_line_id: string | null; is_latest?: boolean }>(reading[key], line.id); return <span key={key}>{label} <b className="font-mono font-semibold text-foreground">{items?.length ?? "—"}</b></span>; })}</div><div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs"><span className={count ? "font-medium text-primary" : "text-muted-foreground"}>{candidateCount === undefined && queue === null ? "候选队列暂未取得" : count ? `待我办理 ${count}` : "当前没有本人待办"}</span><span className="text-muted-foreground">下一步：<b className="font-medium text-foreground">{next}</b></span></div></button>;
    })}</div>
    <div><h3 className="mb-2 text-xs font-semibold text-muted-foreground">空间级</h3><div className="space-y-2"><Button variant="ghost" className="min-h-11 w-full justify-start border border-dashed text-xs text-muted-foreground" disabled={disabled} onClick={() => onOpen("")}>空间共享研究 · 跨主题共性资料与成果</Button><Button variant="ghost" className="min-h-11 w-full justify-start border border-dashed text-xs text-muted-foreground" disabled={disabled} onClick={() => onOpen("all")}>查看空间全部工作</Button></div></div>
  </div>;
}

function Item({ title, description, status, href, action }: { title: string; description: string; status?: string; href: string; action: string }) {
  return <Link href={href} aria-label={action} className="flex min-h-11 items-center gap-2 border-b px-3.5 py-2 last:border-b-0 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"><div className="min-w-0 flex-1"><h3 className="truncate text-[13px] font-medium">{title}</h3><p className="truncate text-[11px] text-muted-foreground">{description}</p></div><span className="shrink-0 text-[11px] text-muted-foreground">{status ?? action}</span><ArrowRightIcon aria-hidden="true" size={12}/></Link>;
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
  useProductWorkUpdates(base, load, { paused: !!selected || writing, onError: failure });
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
  const lineName = (line: string | null) => catalog.nodes.find(node => node.id === line)?.name ?? "品类共用研究";
  return <div className="min-w-0 space-y-3.5">
    {error && <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive"><p>{error}</p><Button variant="outline" size="sm" onClick={() => void load().catch(failure)}>重试读取待办</Button></div>}
    <div className="grid min-w-0 items-start gap-3.5 min-[1000px]:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-3.5">
        <Panel title="等待你裁决" count={attention ? candidates.length + mine.research.length + mine.work.length + professional.length : undefined}>
          {!attention && !error && <p role="status" className="px-4 py-4 text-sm text-muted-foreground">正在核对本人候选…</p>}
          {candidates.map(candidate => candidate.parent_finding_id && candidate.item_position && candidate.item ? <div className="m-3.5" key={candidate.id}><ProductCandidateCard base={base} candidate={candidate as ProductItemCandidate} disabled={writing} onRevise={() => setSelected(candidate)} onPendingChange={pendingChange} onAuthorityLost={onAuthorityLost}/></div> : <article key={candidate.id} className="m-3.5 space-y-2 rounded-lg border border-dashed border-primary/25 bg-primary/5 px-3.5 py-3"><div className="flex flex-wrap items-start gap-2"><span className="inline-flex items-center gap-1 text-xs text-primary"><SparkleIcon aria-hidden="true" size={14}/>AI 候选</span><h3 className="min-w-0 flex-1 break-words text-sm font-medium">{candidate.title}</h3><span className="text-xs text-pending">{candidate.status === "accepted" ? "已接受 · 待应用" : "待核对"}</span></div><p className="break-words text-xs leading-5 text-muted-foreground">{candidate.summary}</p><p className="text-xs text-muted-foreground">{lineName(candidate.product_line_id)} · {capabilities[candidate.capability]?.title ?? "产品工作"} · {new Date(candidate.created_at).toLocaleDateString()}</p>{candidate.capability === "rfq_requirements" ? <Link className="inline-flex min-h-11 items-center text-sm text-primary" href={runHref(candidate)}>核对需求候选</Link> : <Button size="sm" variant={selected?.id === candidate.id ? "outline" : "default"} disabled={writing} onClick={event => { reviewTrigger.current = event.currentTarget; setSelected(candidate); }}>{candidate.status === "accepted" ? "核对后独立应用" : "核对 / 修订候选"}</Button>}</article>)}
          {professional.map(({ item, collection, title, anchor }) => <Item key={`${collection}:${item.id}`} title={item.content?.title ?? item.title ?? item.hypothesis ?? title} description={item.content?.change_reason ?? item.decision_reason ?? "核对当前版本、依据与可办理动作。"} status={`${title} · ${({ draft: "草稿", in_review: "协审中", approved: "待开始", running: "执行中" } as Record<string, string>)[item.state] ?? item.state}`} href={href(collection, item.product_line_id, `${anchor}-${item.id}`)} action={collection === "experiments" ? "核对计划与结果" : "查看协审与发布条件"}/>)}
          {mine.work.map(item => <Item key={item.id} title={item.title} description={item.expected_output} status={stateLabels[item.state]} href={href("research", item.product_line_id, `work-${item.id}`)} action={item.state === "submitted" ? "核对并接收成果" : item.state === "pending_assignment" ? "分派负责人" : "去办理"}/>)}
          {mine.research.map(item => <Item key={item.id} title={item.question} description={item.expected_decision} status={stateLabels[item.state]} href={href("research", item.product_line_id, `research-${item.id}`)} action={item.state === "active" ? "核对并提交结论" : "开始研究"}/>)}
          {attention && !candidates.length && !mine.research.length && !mine.work.length && !professional.length && <p className="px-4 py-5 text-sm text-muted-foreground">当前没有等待你处理的事项。</p>}
          {Object.values(attention?.professional?.pages ?? {}).some(page => page.next_offset !== null && page.next_offset !== undefined) && <p className="px-4 py-3 text-xs text-muted-foreground">专业待办显示 My Work 最近一页，可在<a className="underline" href="/my-work">我的工作</a>继续查看。</p>}
          {attention?.limited && <p className="px-4 py-3 text-xs text-muted-foreground">当前读取最近 100 批本人候选，逐条展示待裁决与待应用项；更早记录可在所属视图的分析记录中查阅。</p>}
          {attention?.unavailable && <p className="px-4 py-3 text-xs text-pending">部分原运行的来源或权限已变化，未显示其私有内容。</p>}
        </Panel>
        {selected && <section ref={reviewPanel} tabIndex={-1} aria-label="审阅所选候选" className="min-w-0 scroll-mt-16 space-y-3 outline-none"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">{selected.title}</h2><Button variant="ghost" size="sm" disabled={writing} onClick={() => { setSelected(null); reviewTrigger.current?.focus(); void load().catch(failure); }}>收起审阅</Button></div><p className="text-xs text-muted-foreground">核对固定来源，接受与正式应用分别办理。</p>{selected.capability === "research_planning" ? <ProductResearchProposal key={selected.run_id} base={base} runId={selected.run_id} disabled={writing} autoLoad onPendingChange={pendingChange} onAccessDenied={onAuthorityLost}/> : <ProductEvidenceProposal key={selected.id} base={base} runId={selected.run_id} parentFindingId={selected.parent_finding_id} itemPosition={selected.item_position} initialEdit={!!selected.parent_finding_id} disabled={writing} autoLoad onPendingChange={pendingChange} onAccessDenied={onAuthorityLost}/> }<Link className="inline-flex min-h-11 items-center text-sm text-primary" href={runHref(selected)}>查看原运行与来源依据</Link></section>}
        <Panel title="缺口与信号">
          {issues.slice(0, 6).map(item => <Item key={item.id} title={item.name} description={[item.has_conflict ? "来源存在冲突" : "", item.is_stale ? "来源已陈旧" : "", item.superseded ? "已有新版，原引用仍需复核" : ""].filter(Boolean).join("；")} href={href("research")} action="核对来源"/>)}
          {unresolved.slice(0, 6).map(item => <Item key={item.id} title={item.question} description={item.unresolved.join("；")} href={href("research", item.product_line_id, `research-${item.id}`)} action="补齐研究缺口"/>)}
          {gaps.slice(0, 4).map(item => <Item key={item.run_id} title={`${capabilities[item.capability]?.title ?? "分析"}缺项`} description={item.missing.join("；")} href={runHref(item)} action="核对分析缺项"/>)}
          {!issues.length && !unresolved.length && !gaps.length && <p className="px-4 py-5 text-sm text-muted-foreground">{attention ? "当前可读记录中没有已登记的缺口信号。" : error ? "分析缺口暂未取得，请重试读取待办。" : "正在读取分析缺口…"}</p>}
        </Panel>
      </div>
      <div className="min-w-0 space-y-3.5">
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
