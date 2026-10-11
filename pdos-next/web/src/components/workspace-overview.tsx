"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, CheckCircle, ClipboardText, FileText, FolderSimple, GitBranch, Package, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { ExperienceData } from "@/components/workspace-experience";
import type { WorkspaceArea } from "@/lib/workspace-navigation";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { DefinitionList } from "@/lib/product-view";
import type { ProjectList } from "@/lib/project-plan-view";
import type { BuildList } from "@/lib/build-preparation-view";

type Props = { area: "products" | "projects"; data: ExperienceData; api: WorkspaceTransport; navigate: (area: WorkspaceArea, section?: string, task?: string) => void };
type Saved = { definitions: DefinitionList | null; projects: ProjectList | null; builds: BuildList | null };
const statusNames: Record<string, string> = { draft: "草稿", planned: "已计划", executing: "执行中", completed: "已完成", cancelled: "已取消", running: "执行中", disposed: "已记录处置" };

export function WorkspaceOverview({ area, data, api, navigate }: Props) {
  const [saved, setSaved] = useState<Saved>({ definitions: null, projects: null, builds: null });
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setLoading(true); setErrors([]);
      const results = await Promise.allSettled([
        api<DefinitionList>(`v1/products/${data.product.id}/definitions`),
        api<ProjectList>(`v1/products/${data.product.id}/projects`),
        api<BuildList>(`v1/products/${data.product.id}/builds`),
      ]);
      if (!active) return;
      const [definitions, projects, builds] = results;
      setSaved({ definitions: definitions.status === "fulfilled" ? definitions.value : null, projects: projects.status === "fulfilled" ? projects.value : null, builds: builds.status === "fulfilled" ? builds.value : null });
      setErrors(results.flatMap((result, index) => result.status === "rejected" ? [`${["型号定义", "研发项目", "试制"][index]}读取失败：${result.reason?.message ?? "服务暂不可用"}`] : []));
      setLoading(false);
    });
    return () => { active = false; };
  }, [data.product.id, data.product.revision, api, attempt]);

  const validClaims = data.claims.filter(item => item.status === "active" && item.source_status === "active");
  const unknownClaims = validClaims.filter(item => item.availability !== "known");
  const staleClaims = data.claims.filter(item => item.status === "active" && item.source_status !== "active");
  const activeSources = data.sources.filter(item => item.status === "active");
  const definitions = saved.definitions?.items ?? [];
  const projects = saved.projects?.items ?? [];
  const builds = saved.builds?.items ?? [];
  const nextSteps = area === "products" ? [
    { Icon: FileText, label: activeSources.length ? "继续整理研究资料" : "导入第一份资料", detail: activeSources.length ? `${activeSources.length} 份有效来源 · ${validClaims.length} 条有效事实` : "保留原件、定位原文，再登记有出处的事实", go: () => navigate("products", "research", "sources") },
    { Icon: unknownClaims.length || staleClaims.length ? WarningCircle : ClipboardText, label: unknownClaims.length || staleClaims.length ? "核对未知与失效来源" : "整理型号定义与规格", detail: unknownClaims.length || staleClaims.length ? `${unknownClaims.length} 条未知或冲突 · ${staleClaims.length} 条来源失效` : saved.definitions ? `${definitions.length} 份可见定义版本，草稿与正式发布分别办理` : "从当前证据整理使用场景、规格和验收条件", go: () => navigate("products", unknownClaims.length || staleClaims.length ? "research" : "definition") },
    { Icon: saved.projects && projects.length ? FolderSimple : GitBranch, label: saved.projects && projects.length ? "继续关联项目工作" : "派生型号或进入研发", detail: saved.projects && projects.length ? `${projects.length} 个可见项目，分别固定定义与研发范围` : "复用固定定义，保留派生差异与明确项目范围", go: () => navigate(saved.projects && projects.length ? "projects" : "products", saved.projects && projects.length ? "overview" : "variants") },
  ] : [
    { Icon: FolderSimple, label: "工作与首版计划", detail: saved.projects ? `${projects.length} 个可见项目 · ${projects.filter(item => item.plan).length} 个已保存计划` : "固定型号定义与范围，核对工作包、依赖和日历", go: () => navigate("projects", "plan") },
    { Icon: Package, label: "试制与实际产出", detail: saved.builds ? `${builds.length} 轮可见试制，配置、准备与实际分别保存` : "从固定双配置接齐套、开工条件与产出", go: () => navigate("projects", "builds") },
    { Icon: CheckCircle, label: "测试与样件交接", detail: "从实际样件接收进入方法核对、开测与结果处置", go: () => navigate("projects", "verification") },
  ];

  return <div className="workspace-overview">
    <dl className="workspace-object-counts">{[
      { Icon: ClipboardText, label: "定义版本", value: saved.definitions?.items.length, go: () => navigate("products", "definition") },
      { Icon: FolderSimple, label: "研发项目", value: saved.projects?.items.length, go: () => navigate("projects", "plan") },
      { Icon: Package, label: "试制", value: saved.builds?.items.length, go: () => navigate("projects", "builds") },
    ].map(({ Icon, label, value, go }) => <div key={label}><dt><Icon size={17} aria-hidden="true"/>{label}</dt><dd><button type="button" onClick={go} aria-label={`查看${label}`}><span className="font-mono">{value ?? "—"}</span><ArrowRight size={14} aria-hidden="true"/></button></dd></div>)}</dl>
    {loading && <p className="subtle" role="status">正在读取已保存结果…</p>}
    {errors.length > 0 && <div className="workspace-read-error" role="alert">{errors.map(error => <p key={error}>{error}</p>)}<Button variant="outline" onClick={() => setAttempt(value => value + 1)}><ArrowClockwise/>重新读取</Button></div>}
    <div className="workspace-overview-columns">
      <section className="workspace-overview-next"><header><h2>接下来</h2><span className="subtle">按当前事实接续</span></header><div className="workspace-next-list">{nextSteps.map(({ Icon, label, detail, go }) => <button key={label} type="button" onClick={go}><span className="workspace-next-icon"><Icon size={19} aria-hidden="true"/></span><span className="min-w-0"><span className="block font-medium">{label}</span><span className="subtle mt-1 block">{detail}</span></span><ArrowRight size={16} className="ml-auto shrink-0" aria-hidden="true"/></button>)}</div></section>
      <section className="workspace-overview-evidence"><header><h2>证据状态</h2><button type="button" onClick={() => navigate("products", "research")}>查看资料<ArrowRight size={14} aria-hidden="true"/></button></header><dl className="workspace-evidence-list"><div><dt><FileText size={16} aria-hidden="true"/>有效来源</dt><dd>{activeSources.length}<span>份</span></dd></div><div><dt><CheckCircle size={16} aria-hidden="true"/>有据事实</dt><dd>{validClaims.length}<span>条</span></dd></div><div><dt><WarningCircle size={16} aria-hidden="true"/>未知或冲突</dt><dd>{unknownClaims.length}<span>条</span></dd></div><div><dt><ClockIcon/>来源待重核</dt><dd>{staleClaims.length}<span>条</span></dd></div></dl><p className="subtle">计数仅来自当前授权范围，不表示专业结论或正式批准。</p></section>
    </div>
    <section className="workspace-saved-results"><header><h2>{area === "products" ? "已保存定义" : "已关联项目"}</h2><button type="button" onClick={() => navigate(area === "products" ? "products" : "projects", area === "products" ? "definition" : "plan")}>进入工作区<ArrowRight size={14} aria-hidden="true"/></button></header>
      {area === "products" ? <>
        {!loading && saved.definitions && definitions.length === 0 && <p className="workspace-list-empty">尚无可见定义。整理来源后，可以保存第一版定义草稿。</p>}
        {definitions.slice(0, 6).map(item => <div className="workspace-record-row" key={item.id}><ClipboardText size={18} aria-hidden="true"/><div className="min-w-0 flex-1"><p className="truncate font-medium">{item.title}</p><p className="subtle">{item.specs.length} 项规格 · {item.sources.length} 处来源</p></div><span className="workspace-state">{item.source_status === "current" ? "草稿" : "需重核"}</span><span className="workspace-revision">v{item.revision}</span></div>)}
      </> : <>
        {!loading && saved.projects && projects.length === 0 && <p className="workspace-list-empty">尚无可见项目。先固定一份型号定义，再明确研发范围。</p>}
        {projects.slice(0, 6).map(item => <div className="workspace-record-row" key={item.id}><FolderSimple size={18} aria-hidden="true"/><div className="min-w-0 flex-1"><p className="truncate font-medium">{item.name}</p><p className="subtle truncate">{item.definition.title} · 固定 v{item.definition.revision}</p></div><span className="workspace-state">{item.source_status !== "current" ? "需重核" : item.plan ? "已有计划" : "待建计划"}</span><span className="workspace-revision">v{item.revision}</span></div>)}
      </>}
      {(area === "products" ? saved.definitions?.has_more : saved.projects?.has_more) && <p className="subtle mt-3">当前显示首批可见结果，进入工作区查看其余记录。</p>}
      {(area === "products" ? saved.definitions?.unavailable_count : saved.projects?.unavailable_count) ? <p className="subtle mt-3">另有当前不可用记录，需在工作区核对来源或访问条件。</p> : null}
    </section>
    {area === "projects" && builds.length > 0 && <section className="workspace-saved-results"><header><h2>试制记录</h2><button type="button" onClick={() => navigate("projects", "builds")}>进入试制<ArrowRight size={14} aria-hidden="true"/></button></header>{builds.slice(0, 5).map(item => <div className="workspace-record-row" key={item.id}><Package size={18} aria-hidden="true"/><div className="min-w-0 flex-1"><p className="truncate font-medium">{item.name}</p><p className="subtle truncate">{item.project_name} · 计划 {item.planned_quantity} {item.unit}</p></div><span className="workspace-state">{statusNames[item.status] ?? "已保存"}</span></div>)}</section>}
  </div>;
}

function ClockIcon() { return <ArrowClockwise size={16} aria-hidden="true"/>; }
