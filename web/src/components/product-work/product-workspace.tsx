"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { WorkHistory } from "./work-history";
import { WorkResponsibility, WorkResponsibilityLanding } from "./work-responsibility";
import { actionLabels, command, request, stateLabels, type Evidence, type Member, type ProductCatalog, type Research, type Space, type WorkItem, type Workspace } from "./product-work-api";

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

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const lines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);
const accessLabels: Record<string, string> = { viewer: "只读", contributor: "协作", manager: "管理" };
const tabs = ["研究", "竞品", "细分 / JTBD", "机会树", "策略", "定义", "矩阵 / 路线图", "实验 / 决策", "导出中心", "投入观察"];

function useRequestId() {
  const last = useRef({ body: "", id: "" });
  return (body: unknown) => {
    const serialized = JSON.stringify(body);
    if (last.current.body !== serialized) last.current = { body: serialized, id: crypto.randomUUID() };
    return last.current.id;
  };
}

export function ProductWorkspace() {
  const [spaces, setSpaces] = useState<Space[] | null>(null);
  const [canCreate, setCanCreate] = useState(false);
  const [selected, setSelected] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stableId = useRequestId();
  const load = async () => { const data = await request<{ items: Space[]; can_create: boolean }>("spaces"); setSpaces(data.items); setCanCreate(data.can_create); };
  useEffect(() => {
    let live = true;
    void request<{ items: Space[]; can_create: boolean }>("spaces").then((data) => {
      if (!live) return; setSpaces(data.items); setCanCreate(data.can_create);
      const target = new URLSearchParams(window.location.search).get("space");
      if (target && data.items.some((space) => space.id === target)) setSelected(target);
    }).catch((failure) => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, []);
  return <main className="space-y-6">
    <header><h1 className="text-2xl font-semibold">产品管理工作台</h1><p className="mt-2 text-sm text-muted-foreground">围绕市场空间组织研究、来源与专业协作，立项前即可开展工作。</p></header>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap items-center gap-3">
      <label className="min-w-64 flex-1 text-sm">市场空间<select className={field} value={selected} onChange={(event) => { setSelected(event.target.value); setCreateOpen(false); }}><option value="">选择市场空间</option>{spaces?.map((space) => <option key={space.id} value={space.id}>{space.code} · {space.title}</option>)}</select></label>
      {canCreate && <Button variant="outline" onClick={() => setCreateOpen(!createOpen)}>新建市场空间</Button>}
      <Button variant="outline" disabled={busy} onClick={() => { setError(null); void load().catch((failure) => setError(failure.message)); }}>刷新</Button>
    </div>
    {spaces?.length === 0 && <p className="text-sm text-muted-foreground">尚无可访问市场空间。{canCreate ? "可先登记用户群、地域、场景和研究问题。" : "请由空间负责人将你加入协作成员。"}</p>}
    {createOpen && canCreate && <form className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault(); const form = new FormData(event.currentTarget);
      const body = { code: String(form.get("code")).trim(), title: String(form.get("title")).trim(), user_groups: lines(String(form.get("groups"))), regions: lines(String(form.get("regions"))), use_scenarios: lines(String(form.get("scenarios"))), research_questions: lines(String(form.get("questions"))) };
      setBusy(true); setError(null);
      void request<Space>("spaces", "POST", { ...body, request_id: stableId(body) }).then(async (space) => { await load(); setSelected(space.id); setCreateOpen(false); }).catch((failure) => setError(failure.message)).finally(() => setBusy(false));
    }}>
      <label className="text-sm">空间编号<input required name="code" maxLength={128} pattern="[a-zA-Z0-9_.:-]+" className={field} placeholder="如 portable-inflation" /></label>
      <label className="text-sm">空间名称<input required name="title" maxLength={512} className={field} /></label>
      {[["groups", "用户群"], ["regions", "地域 / 市场"], ["scenarios", "使用场景"], ["questions", "待研究问题"]].map(([key, label]) => <label key={key} className="text-sm">{label}（每行一项）<textarea required name={key} className={field} /></label>)}
      <Button disabled={busy}>创建市场空间</Button>
    </form>}
    {selected && <SpaceWorkspace key={selected} spaceId={selected} />}
  </main>;
}

function MemberSelect({ members, name, label, required = false, defaultValue = "" }: { members: Member[]; name: string; label: string; required?: boolean; defaultValue?: string }) {
  return <label className="text-sm">{label}<select name={name} required={required} defaultValue={defaultValue} className={field}><option value="">待指定</option>{members.filter((member) => member.access !== "viewer").map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>;
}

function SpaceWorkspace({ spaceId }: { spaceId: string }) {
  const [data, setData] = useState<Workspace | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [catalog, setCatalog] = useState<ProductCatalog | null>(null);
  const [scopeFilter, setScopeFilter] = useState("all");
  const [formLine, setFormLine] = useState("");
  const [tab, setTab] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formKind, setFormKind] = useState<"research" | "work" | null>(null);
  const stableId = useRequestId();
  const [responsibilityLock, setResponsibilityLock] = useState<string | null>(null);
  const base = `spaces/${spaceId}`;
  const load = async () => { const [workspace, sources, products] = await Promise.all([request<Workspace>(base), request<{ items: Evidence[] }>(`${base}/evidence`), request<ProductCatalog>(`${base}/products`)]); setData(workspace); setEvidence(sources.items); setCatalog(products); };
  useEffect(() => {
    let live = true;
    void Promise.all([request<Workspace>(base), request<{ items: Evidence[] }>(`${base}/evidence`), request<ProductCatalog>(`${base}/products`)]).then(([workspace, sources, products]) => { if (live) { setData(workspace); setEvidence(sources.items); setCatalog(products); const tabs: Record<string, number> = { measurement: 9, exports: 8, experiments: 7, opportunities: 3, strategies: 4, definitions: 5, matrix: 6 }; setTab(tabs[new URLSearchParams(window.location.search).get("tab") ?? ""] ?? 0); const line = new URLSearchParams(window.location.search).get("line"); if (line && products.nodes.some((node) => node.id === line && node.level === "line")) { setScopeFilter(line); setFormLine(line); } } }).catch((failure) => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [base]);
  useEffect(() => {
    if (!data || !catalog || tab !== 0 || !/^#(?:work|research)-/.test(window.location.hash)) return;
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [data, catalog, tab]);
  const act = async (work: () => Promise<unknown>) => { setBusy(true); setError(null); try { await work(); await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作失败"); } finally { setBusy(false); } };
  if (!data || !catalog) return <div className="space-y-2"><p className="text-sm">{error ?? "正在加载市场空间…"}</p>{error && <Button variant="outline" onClick={() => void act(load)}>重试</Button>}</div>;
  const name = (id: string | null) => data.members.find((member) => member.id === id)?.display_name ?? "未指定 / 成员已失效";
  const productLines = catalog.nodes.filter((node) => node.level === "line");
  const scopeName = (lineId: string | null) => lineId ? productLines.find((node) => node.id === lineId)?.name ?? "产品线" : "市场空间共同研究";
  const matchesScope = (lineId: string | null) => scopeFilter === "all" || (lineId ?? "") === scopeFilter;
  const scopedMembers = (lineId: string | null) => lineId ? data.members.filter((member) => catalog.members.some((grant) => grant.product_line_id === lineId && grant.user_id === member.id && grant.access !== "viewer")) : data.members;
  const canWork = (lineId: string | null) => data.can_contribute && (!lineId || catalog.line_access[lineId]?.can_contribute === true);
  const visibleResearch = data.research.filter((task) => matchesScope(task.product_line_id));
  const visibleWork = data.work_items.filter((item) => matchesScope(item.product_line_id));

  return <section className="space-y-5">
    <div className="rounded-lg border p-4"><h2 className="font-semibold">{data.space.title}</h2><p className="mt-1 text-sm">{data.space.user_groups.join("、")} · {data.space.regions.join("、")}</p><p className="text-sm text-muted-foreground">{data.space.use_scenarios.join("；")}</p></div>
    <WorkResponsibility spaceId={spaceId} kind="space" recordId={spaceId} disabled={busy || (!!responsibilityLock && responsibilityLock !== "space")} onLock={value => setResponsibilityLock(value ? "space" : null)} onChanged={load}/>
    <WorkResponsibilityLanding spaceId={spaceId}/>
    <div className="flex gap-2 overflow-x-auto border-b pb-2" role="tablist" aria-label="产品管理工作区">{tabs.map((label, index) => <Button key={label} role="tab" aria-selected={index === tab} variant={index === tab ? "default" : "ghost"} size="sm" className="shrink-0" disabled={!!responsibilityLock} onClick={() => setTab(index)}>{label}</Button>)}</div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button size="sm" variant="outline" disabled={busy || !!responsibilityLock} onClick={() => void act(load)}>刷新工作与来源</Button>
    {tab === 9 ? <ResearchMeasurement spaceId={spaceId} workspace={data} catalog={catalog}/> : tab === 8 ? <DefinitionExports base={base}/> : tab === 5 ? <DefinitionWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "definition" : null)}/> : tab === 4 ? <StrategyWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "strategy" : null)}/> : tab === 7 ? <ExperimentWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "experiment" : null)}/> : tab === 3 ? <OpportunityTree base={base} workspace={data} catalog={catalog} evidence={evidence} onResponsibilityLock={value => setResponsibilityLock(value ? "opportunity" : null)}/> : tab === 2 ? <MarketSegments base={base} workspace={data} catalog={catalog} evidence={evidence} /> : tab === 1 ? <CompetitorWorkspace base={base} workspace={data} catalog={catalog} evidence={evidence} /> : tab === 6 ? <><fieldset disabled={!!responsibilityLock}><ProductMatrix base={base} catalog={catalog}/><ProductRoadmap base={base} catalog={catalog} workspace={data} evidence={evidence}/></fieldset><ProductTree evidence={evidence} catalog={catalog} workspace={data} base={base} busy={busy || (!!responsibilityLock && responsibilityLock !== "node")} act={act} refresh={load} onResponsibilityLock={value => setResponsibilityLock(value ? "node" : null)}/></> : tab !== 0 ? <div className="rounded-md border p-4 text-sm"><p>{tabs[tab]}的领域操作尚未接入。</p><p className="mt-1 text-muted-foreground">当前可在研究区登记问题、引用证据并分派专业评审或实验准备工作。</p></div> : <>
      <p className="text-sm text-muted-foreground">当前支持人工研究、公开页面采集与专业协作。已接入手动搜索与页面订阅入口，AI 研究运行尚未接入此工作区。</p>
      <label className="block max-w-md text-sm">工作归属<select className={field} value={scopeFilter} disabled={!!responsibilityLock} onChange={(event) => { setScopeFilter(event.target.value); setFormLine(event.target.value === "all" ? "" : event.target.value); }}><option value="all">全部可访问工作</option><option value="">市场空间共同研究</option>{productLines.map((line) => <option key={line.id} value={line.id}>{line.name}</option>)}</select></label>
      <ResearchCollection onResponsibilityLock={value => setResponsibilityLock(value ? "subscription" : null)} base={base} workspace={data} evidence={evidence} lineId={scopeFilter === "all" ? null : scopeFilter || null} canCollect={data.can_collect && canWork(scopeFilter === "all" ? null : scopeFilter || null)} refresh={load} />
      {data.can_contribute && <div className="flex gap-2"><Button size="sm" onClick={() => setFormKind(formKind === "research" ? null : "research")}>新建研究任务</Button><Button size="sm" variant="outline" onClick={() => setFormKind(formKind === "work" ? null : "work")}>分派专业工作</Button></div>}
      {formKind && <form key={formKind} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2" onSubmit={(event) => {
        event.preventDefault(); const form = new FormData(event.currentTarget);
        const common = { owner_user_id: String(form.get("owner") ?? "") || null, product_line_id: formLine || null };
        const body = formKind === "research" ? { ...common, question: String(form.get("question")).trim(), user_groups: data.space.user_groups, regions: data.space.regions, time_scope: String(form.get("time_scope")).trim(), method: String(form.get("method")).trim(), expected_decision: String(form.get("expected_decision")).trim(), stop_conditions: lines(String(form.get("stop_conditions"))) } : { ...common, title: String(form.get("title")).trim(), action_type: String(form.get("action_type")), receiver_user_id: String(form.get("receiver") ?? "") || null, expected_output: String(form.get("expected_output")).trim(), completion_criteria: String(form.get("completion_criteria")).trim(), due_at: form.get("due") ? new Date(String(form.get("due"))).toISOString() : null };
        const kind = formKind;
        void act(async () => { await request(`${base}/${kind === "research" ? "research" : "work-items"}`, "POST", { ...body, request_id: stableId(body) }); setFormKind(null); });
      }}>
        <label className="text-sm sm:col-span-2">任务归属<select className={field} value={formLine} onChange={(event) => setFormLine(event.target.value)}><option value="">市场空间共同研究</option>{productLines.filter((line) => catalog.line_access[line.id]?.can_contribute).map((line) => <option key={line.id} value={line.id}>{line.name}</option>)}</select></label>
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
      <section className="space-y-3"><h3 className="font-semibold">研究任务</h3>{visibleResearch.length === 0 && <p className="text-sm text-muted-foreground">此范围尚无研究任务。</p>}{visibleResearch.map((task) => <div key={task.id}><ResearchCard key={`${task.id}:${task.version}`} task={task} scopeLabel={scopeName(task.product_line_id)} ownerName={name(task.owner_user_id)} canAct={canWork(task.product_line_id) && task.owner_user_id === data.current_user_id} evidence={evidence} busy={busy || !!responsibilityLock} act={act} base={base} /><WorkResponsibility spaceId={spaceId} kind="research" recordId={task.id} disabled={busy || !!responsibilityLock && responsibilityLock !== task.id} onLock={value => setResponsibilityLock(value ? task.id : null)} onChanged={load}/></div>)}</section>
      <section className="space-y-3"><h3 className="font-semibold">专业协作与补证</h3>{visibleWork.length === 0 && <p className="text-sm text-muted-foreground">此范围尚无专业工作项。</p>}{visibleWork.map((item) => <div id={`work-${item.id}`} key={item.id}><WorkCard key={`${item.id}:${item.version}`} item={item} scopeLabel={scopeName(item.product_line_id)} workspace={{ ...data, members: scopedMembers(item.product_line_id), can_contribute: canWork(item.product_line_id), can_manage: data.can_manage && (!item.product_line_id || catalog.line_access[item.product_line_id]?.can_manage === true) }} evidence={evidence} busy={busy || !!responsibilityLock} act={act} base={base} /><WorkResponsibility spaceId={spaceId} kind="work" recordId={item.id} disabled={busy || !!responsibilityLock && responsibilityLock !== item.id} onLock={value => setResponsibilityLock(value ? item.id : null)} onChanged={load}/></div>)}</section>
    </>}
    <fieldset disabled={!!responsibilityLock}><SpaceSettings workspace={data} base={base} busy={busy} act={act} /></fieldset>
    <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">空间成员与权限</summary><ul className="mt-3 space-y-2 text-sm">{data.members.map((member) => <li key={member.id} className="flex items-center gap-3"><span>{member.display_name} · {accessLabels[member.access] ?? member.access}</span>{data.can_manage && member.id !== data.space.owner_user_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => request(`${base}/members/${member.id}`, "PUT", { access: null }))}>移除访问</Button>}</li>)}</ul>
      {data.can_manage && <form className="mt-3 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void act(() => request(`${base}/members/${form.get("user")}`, "PUT", { access: form.get("access") })); }}><label className="text-sm">成员<select required name="user" className={field}>{data.available_members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label><label className="text-sm">访问范围<select name="access" className={field}><option value="contributor">协作</option><option value="viewer">只读</option><option value="manager">管理（同时受岗位权限限制）</option></select></label><Button className="self-end" disabled={busy}>保存成员权限</Button></form>}
    </details>
  </section>;
}

function ResearchCard({ task, scopeLabel, ownerName, canAct, evidence, busy, act, base }: { task: Research; scopeLabel: string; ownerName: string; canAct: boolean; evidence: Evidence[]; busy: boolean; act: (work: () => Promise<unknown>) => Promise<void>; base: string }) {
  const [note, setNote] = useState(""); const [findings, setFindings] = useState(""); const [unresolved, setUnresolved] = useState(""); const [selected, setSelected] = useState<string[]>([]);
  return <article id={`research-${task.id}`} className="space-y-2 rounded-lg border p-4"><h4 className="font-medium">{task.question}</h4><p className="text-sm">{stateLabels[task.state]} · {ownerName} · {scopeLabel} · v{task.version}</p><p className="text-sm">{task.method} · {task.time_scope}</p><p className="text-sm">支持决定：{task.expected_decision}</p><p className="text-xs text-muted-foreground">停止条件：{task.stop_conditions.join("；")}</p>
    {task.conclusion && <div className="space-y-1 rounded-md bg-muted p-3 text-sm"><p>{task.conclusion}</p>{task.findings.map((item, i) => <p key={i}>发现：{item}</p>)}{task.unresolved.map((item, i) => <p key={i}>未解决：{item}</p>)}<p>关联证据 {task.sources.length} 项</p><ul>{task.sources.map((ref) => { const source = evidence.find((item) => item.id === ref.ref_id); return <li key={ref.ref_id} className="break-all text-xs">{source?.name ?? "历史来源（当前不可用）"} · {new Date(ref.as_of).toLocaleString()} · {ref.digest.slice(0, 12)}{source?.url && /^https?:\/\//i.test(source.url) ? <> · <a className="underline" href={source.url} target="_blank" rel="noreferrer">查看来源</a></> : null}{source?.is_stale ? " · 已陈旧" : ""}{source?.has_conflict ? " · 有冲突" : ""}</li>; })}</ul></div>}
    {canAct && task.state === "draft" && <Button size="sm" disabled={busy} onClick={() => void act(() => request(`${base}/research/${task.id}/start`, "POST", { ...command(task), research_task_id: task.id }))}>开始研究</Button>}
    {canAct && ["draft", "active"].includes(task.state) && <details className="space-y-2"><summary className="cursor-pointer text-sm">{task.state === "active" ? "提交结论或取消" : "取消研究"}</summary><label className="block text-sm">结论 / 取消原因<textarea maxLength={2048} className={field} value={note} onChange={(e) => setNote(e.target.value)} /></label>{task.state === "active" && <>
      <label className="block text-sm">有依据的发现（每行一项）<textarea className={field} value={findings} onChange={(e) => setFindings(e.target.value)} /></label><label className="block text-sm">未解决事项（每行一项）<textarea className={field} value={unresolved} onChange={(e) => setUnresolved(e.target.value)} /></label><EvidencePicker options={evidence} selected={selected} onChange={setSelected} />
      <Button size="sm" disabled={busy || !note.trim() || (lines(findings).length > 0 && selected.length === 0)} onClick={() => void act(() => request(`${base}/research/${task.id}/conclude`, "POST", { ...command(task), research_task_id: task.id, conclusion: note.trim(), findings: lines(findings), unresolved: lines(unresolved), source_refs: evidence.filter((item) => selected.includes(item.id)).map((item) => item.reference) }))}>提交研究结论</Button>
    </>}<Button size="sm" variant="outline" disabled={busy || !note.trim()} onClick={() => void act(() => request(`${base}/research/${task.id}/cancel`, "POST", { ...command(task), reason: note.trim() }))}>取消并保留原因</Button></details>}
  </article>;
}

function WorkCard({ item, scopeLabel, workspace, evidence, busy, act, base }: { item: WorkItem; scopeLabel: string; workspace: Workspace; evidence: Evidence[]; busy: boolean; act: (work: () => Promise<unknown>) => Promise<void>; base: string }) {
  const [note, setNote] = useState(""); const [selected, setSelected] = useState<string[]>([]);
  const owner = workspace.current_user_id === item.owner_user_id; const receiver = workspace.current_user_id === item.receiver_user_id;
  const name = (id: string | null) => workspace.members.find((member) => member.id === id)?.display_name ?? "待指定 / 已失效";
  const run = (action: string) => act(() => request(`${base}/work-items/${item.id}/actions`, "POST", { ...command(item), action, note: action === "start" ? "开始办理" : note.trim(), evidence: action === "submit" ? evidence.filter((source) => selected.includes(source.id)).map((source) => source.reference) : [] }));
  return <article id={`work-${item.id}`} className="space-y-2 rounded-lg border p-4"><h4 className="font-medium">{item.title}</h4><p className="text-sm">{actionLabels[item.action_type]} · {stateLabels[item.state]} · {scopeLabel} · {name(item.owner_user_id)}</p><p className="text-sm">输出：{item.expected_output}</p><p className="text-sm">完成判据：{item.completion_criteria}</p><p className="text-xs text-muted-foreground">{item.acceptance_required ? `接收人：${name(item.receiver_user_id)}` : "资料补证完成后直接记录结果"}{item.due_at ? ` · 目标 ${new Date(item.due_at).toLocaleString()}` : ""}</p>{item.result_note && <p className="text-sm">办理记录：{item.result_note}</p>}{item.evidence.length > 0 && <ul className="text-xs text-muted-foreground">{item.evidence.map((ref) => <li key={ref.ref_id}>{evidence.find((source) => source.id === ref.ref_id)?.name ?? "历史来源（当前不可用）"} · {new Date(ref.as_of).toLocaleString()} · {ref.digest.slice(0, 12)}</li>)}</ul>}
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
