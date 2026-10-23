"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, CalendarBlank, CaretDown, FolderSimple, FunnelSimple, Info, Kanban, ListBullets, MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { projectStateLabel, readPortfolio, type Portfolio, type PortfolioProject } from "@/lib/portfolio-reads";
import { filterProjects, forecastAxis, forecastPosition, formatProjectDate, groupProjects, projectForecast, projectOwner, type ProjectGrouping, type ProjectView } from "@/lib/project-presentation";
import type { browserApi } from "@/lib/browser-api";
import { ProjectStatusSummary } from "./project-status-summary";
import styles from "./project-views.module.css";

type ProjectActions = {
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenWorkbench: (categoryId: string, productId: string, projectId: string) => void;
};

function Name({ entry, onOpenProject }: { entry: PortfolioProject } & Pick<ProjectActions, "onOpenProject">) {
  return <><button type="button" className={styles.title} onClick={() => onOpenProject(entry.category.id, entry.project.id)}>{entry.project.name}</button><p className={`${styles.subtext} ${styles.identity}`} title={entry.project.id}>{entry.project.id.slice(0, 8)}</p><p className={styles.subtext}>{entry.product.name} · {entry.category.name}</p></>;
}

function Owner({ entry }: { entry: PortfolioProject }) {
  return <span className={styles.owner}><span className={styles.avatar} aria-hidden="true">{entry.project.owner_name?.slice(0, 1) ?? "?"}</span>{projectOwner(entry)}</span>;
}

function Forecast({ entry }: { entry: PortfolioProject }) {
  const { earliest, latest } = projectForecast(entry);
  return <><p className={styles.unknown}>下一门禁待提供</p><p className={styles.subtext}>计划预测 {formatProjectDate(earliest)} — {formatProjectDate(latest)}</p></>;
}

function Actions({ entry, onOpenProject, onOpenWorkbench }: { entry: PortfolioProject } & ProjectActions) {
  return <><ProjectStatusSummary update={entry.project.latest_status_update}/><div className={styles.rowActions}><button type="button" onClick={() => onOpenProject(entry.category.id, entry.project.id)}>打开项目<ArrowRight size={12}/></button><button type="button" onClick={() => onOpenWorkbench(entry.category.id, entry.product.id, entry.project.id)}>工作与计划</button></div></>;
}

export function ProjectList({ api, principalId = "", onOpenProject, onOpenWorkbench }: {
  api: typeof browserApi; principalId?: string;
} & ProjectActions) {
  const [reading, setReading] = useState<{ api: typeof browserApi; scope: string; portfolio: Portfolio | null; error: string } | null>(null);
  const [reload, setReload] = useState(0);
  const [view, setView] = useState<ProjectView>("list");
  const [grouping, setGrouping] = useState<ProjectGrouping>("stage");
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [mine, setMine] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const scope = JSON.stringify([principalId, reload]);
  const current = reading?.api === api && reading.scope === scope ? reading : null;
  const portfolio = current?.portfolio ?? null, error = current?.error ?? "";
  useEffect(() => {
    let active = true;
    void readPortfolio(api).then(next => { if (active) setReading({ api, scope, portfolio: next, error: "" }); }).catch(failure => { if (active) setReading({ api, scope, portfolio: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, scope]);

  const entries = filterProjects(portfolio?.projects ?? [], { query, categoryId, ownerId: mine ? principalId : "" });
  const groups = groupProjects(entries, view === "board" ? "stage" : grouping);
  const axis = forecastAxis(entries);
  const actions = { onOpenProject, onOpenWorkbench };
  const filtered = !!query.trim() || !!categoryId || mine;

  return <div className="project-canvas">
    <div className="workspace-page-heading"><div className="min-w-0"><h1>项目</h1><p>本人权限内的研发项目。打开一行进入项目工作区；阶段、健康度与门禁只按已接入的记录显示。</p></div></div>
    <div className={styles.toolbar}>
      <div className={styles.views} role="group" aria-label="项目视图">{([{ id: "list", label: "列表", Icon: ListBullets }, { id: "board", label: "看板", Icon: Kanban }, { id: "timeline", label: "时间轴", Icon: CalendarBlank }] as const).map(item => <button type="button" key={item.id} aria-pressed={view === item.id} onClick={() => setView(item.id)}><item.Icon size={14} aria-hidden="true"/>{item.label}</button>)}</div>
      {view === "list" && <label className={styles.select}>分组<select aria-label="项目分组" value={grouping} onChange={event => setGrouping(event.target.value as ProjectGrouping)}><option value="stage">阶段</option><option value="owner">负责人</option><option value="category">品类</option></select></label>}
      <button type="button" className={styles.filterButton} aria-expanded={filtersOpen} aria-controls="project-filters" data-active={filtered} onClick={() => setFiltersOpen(value => !value)}><FunnelSimple size={14} aria-hidden="true"/>筛选{filtered && <span className={styles.filterDot}/>}</button>
      {principalId && <label className={styles.mine}><input type="checkbox" checked={mine} onChange={event => setMine(event.target.checked)}/>我负责的</label>}
      <div className={styles.summary}><span>{portfolio ? <><span className={styles.count}>{entries.length}</span> 个可见项目{filtered && ` / ${portfolio.projects.length}`}{portfolio.readErrors.length > 0 && " · 部分未读"}</> : error ? "项目暂不可读" : "正在读取…"}</span></div>
      <button type="button" className={styles.refresh} aria-label="刷新项目" title="刷新项目" onClick={() => { setReading(null); setReload(value => value + 1); }}><ArrowClockwise size={14}/><span className="sr-only">刷新</span></button>
    </div>
    <div id="project-filters" hidden={!filtersOpen} className={styles.filters}>
      <label className={styles.search}><MagnifyingGlass size={14} aria-hidden="true"/><input aria-label="搜索项目" placeholder="搜索项目、型号或编号…" value={query} onChange={event => setQuery(event.target.value)}/></label>
      <label className={styles.select}>品类<select aria-label="筛选品类" value={categoryId} onChange={event => setCategoryId(event.target.value)}><option value="">全部品类</option>{portfolio?.categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
      {filtered && <button type="button" className={styles.textButton} onClick={() => { setQuery(""); setCategoryId(""); setMine(false); }}>清除筛选</button>}
    </div>
    {error && <p role="alert" className="workspace-read-error">{error}</p>}
    {portfolio?.readErrors.map(item => <p key={item.path} role="status" className="workspace-read-error">部分范围暂不可读：{item.message}</p>)}
    {!portfolio && !error && <p role="status" className={styles.empty}>正在读取项目…</p>}
    {portfolio && entries.length === 0 && <div className={styles.empty} role="status"><FolderSimple size={28} aria-hidden="true"/><p>{filtered ? portfolio.readErrors.length ? "已读取项目中没有匹配项，部分范围暂不可读。" : "没有符合筛选条件的项目。" : portfolio.readErrors.length ? "当前未取得可展示的项目，请重试读取。" : "暂无可见项目。G0 批准后，真实开发项目会出现在这里。"}</p>{filtered && <Button size="sm" variant="outline" onClick={() => { setQuery(""); setCategoryId(""); setMine(false); }}>清除筛选</Button>}</div>}
    {view === "list" && groups.length > 0 && <div className={styles.listPanel}>{groups.map((group, index) => <section className={styles.group} key={group.id} aria-label={`${group.label}的项目`}><h2><button type="button" className={styles.groupTitle} aria-expanded={!collapsed[group.id]} aria-controls={`project-group-${index}`} onClick={() => setCollapsed(value => ({ ...value, [group.id]: !value[group.id] }))}><CaretDown size={13} aria-hidden="true"/>{group.label}<span>{group.entries.length}</span></button></h2><div id={`project-group-${index}`} hidden={collapsed[group.id]} className={styles.listScroll}><table className={styles.table}><colgroup>{["22%", "11%", "12%", "10%", "18%", "27%"].map((width, i) => <col key={i} style={{ width }}/>)}</colgroup><thead className={index > 0 ? "sr-only" : undefined}><tr><th scope="col">项目</th><th scope="col">阶段</th><th scope="col">健康度</th><th scope="col">负责</th><th scope="col">下一门禁 / 冻结点</th><th scope="col">最新状态更新</th></tr></thead><tbody>{group.entries.map(entry => <tr key={entry.project.id}><td><Name entry={entry} {...actions}/>{entry.project.source_status !== "current" && <span className={styles.readState} data-recheck="true">{projectStateLabel(entry)}</span>}</td><td><span className={styles.unknown}>待提供</span></td><td><span className={styles.unknown} title="尚未取得门禁规则结果，不能推断健康度"><i className={styles.statusDot}/>未知</span></td><td><Owner entry={entry}/></td><td><Forecast entry={entry}/></td><td><ProjectStatusSummary update={entry.project.latest_status_update}/><p className={styles.subtext}>{projectStateLabel(entry)}</p><div className={styles.rowActions}><button type="button" onClick={() => onOpenWorkbench(entry.category.id, entry.product.id, entry.project.id)}>工作与计划<ArrowRight size={12}/></button></div></td></tr>)}</tbody></table></div></section>)}</div>}
    {view === "board" && <><p className={styles.note}><Info size={14} aria-hidden="true"/>看板只展示项目事实，阶段推进须进入项目办理。阶段模板尚未接入时统一列为待提供。</p><div className={styles.board}>{groups.map(group => <section className={styles.column} key={group.id} aria-label={`${group.label}看板`}><h2 className={styles.groupTitle}>{group.label}<span>{group.entries.length}</span></h2>{group.entries.map(entry => <article className={styles.card} key={entry.project.id}><Name entry={entry} {...actions}/><dl><dt>负责人</dt><dd><Owner entry={entry}/></dd><dt>健康度</dt><dd className={styles.unknown}>尚无规则结果</dd><dt>计划预测</dt><dd>{formatProjectDate(projectForecast(entry).earliest)} — {formatProjectDate(projectForecast(entry).latest)}</dd><dt>下一门禁</dt><dd className={styles.unknown}>未提供</dd></dl><Actions entry={entry} {...actions}/></article>)}</section>)}</div></>}
    {view === "timeline" && entries.length > 0 && <><p className={styles.note}>当前显示计划的完成时间预测范围；阶段区间、门禁与冻结点待对应事实接入。基线、预测、承诺和实际分别呈现。</p><div className={styles.scroll}><div className={styles.timeline}><div className={styles.axis}><span>{axis ? formatProjectDate(new Date(axis.start).toISOString()) : "暂无可读日期"}</span><span>{axis ? formatProjectDate(new Date(axis.end).toISOString()) : ""}</span></div>{entries.map(entry => { const position = axis ? forecastPosition(entry, axis) : null; const forecast = projectForecast(entry); return <section className={styles.timeProject} key={entry.project.id} aria-label={`${entry.project.name}四时间`}><div><Name entry={entry} {...actions}/><Actions entry={entry} {...actions}/></div><div className={styles.timeRows}>{["基线", "预测", "承诺", "实际"].map(label => <div className={styles.timeRow} key={label}><span className={styles.timeLabel}>{label}</span><div className={styles.track}>{label === "预测" && position && <i className={styles.bound} style={{ left: `${position.left}%`, width: `${position.width}%` }}/>}<span className={styles.boundText}>{label === "预测" ? `${formatProjectDate(forecast.earliest)} — ${formatProjectDate(forecast.latest)}` : "未知"}</span></div></div>)}</div></section>; })}</div></div></>}
    {portfolio && entries.length > 0 && view === "list" && <p className={styles.note}><Info size={14} aria-hidden="true"/>阶段、健康度、下一门禁与冻结点待对应记录接入；具名更新按原记录展示，不由计划推断。</p>}
    {portfolio?.asOf && <p className={styles.readTime}>读取于 <time dateTime={portfolio.asOf}>{new Date(portfolio.asOf).toLocaleString()}</time></p>}
  </div>;
}
