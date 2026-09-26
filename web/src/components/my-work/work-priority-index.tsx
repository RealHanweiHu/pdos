"use client";

import { useState } from "react";
import type { MyWork } from "./my-work-types";
import { workDate } from "./work-dates";
import { Button } from "@/components/ui/button";

type Entry = { key: string; project: string; title: string; kind: string; due: string | null; blocked: boolean; high: boolean; confirm: boolean; score: number };
type Filter = "all" | "overdue" | "today" | "blocked" | "high" | "confirm";
const filters: { key: Filter; label: string }[] = [{ key: "all", label: "全部" }, { key: "overdue", label: "已逾期" }, { key: "today", label: "今日到期" }, { key: "blocked", label: "已阻塞" }, { key: "high", label: "高优先／严重" }, { key: "confirm", label: "待审阅／确认" }];
const ranks: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export function workCardAnchor(kind: string, id: string, project?: string) { return `work-${kind}-${project ? `${project}-` : ""}${id}`; }

export function WorkPriorityIndex({ work, today }: { work: MyWork; today: string }) {
  const [filter, setFilter] = useState<Filter>("all"), [project, setProject] = useState(""), [search, setSearch] = useState(""), [expanded, setExpanded] = useState(false);
  const common = { due: null, blocked: false, high: false, confirm: false, score: 0 };
  const entries: Entry[] = [
    ...work.tasks.map(item => ({ ...common, key: workCardAnchor("task", item.id), project: item.project.id, title: item.title, kind: "任务", due: item.due_date, blocked: item.status === "blocked", high: ["high", "critical"].includes(item.priority), confirm: item.status === "pending_approval", score: ranks[item.priority] ?? 0 })),
    ...work.issues.map(item => ({ ...common, key: workCardAnchor("issue", item.id), project: item.project.id, title: item.title, kind: "问题", due: item.target_date, high: ["high", "critical"].includes(item.severity), confirm: item.status === "verification", score: ranks[item.severity] ?? 0 })),
    ...work.risks.map(item => ({ ...common, key: workCardAnchor("risk", item.id), project: item.project.id, title: item.title, kind: `风险 ${item.likelihood}×${item.impact}`, due: item.target_date, score: item.likelihood * item.impact / 25 })),
    ...work.capa_actions.map(item => ({ ...common, key: workCardAnchor("capa", item.id), project: item.project.id, title: item.description, kind: "CAPA", due: item.due_date })),
    ...work.gate_signoffs.map(item => ({ ...common, key: workCardAnchor("gate", item.id), project: item.project.id, title: item.gate_name, kind: "阶段签核", due: item.review_due_at ? workDate(item.review_due_at) : null, confirm: true })),
    ...work.findings.map(item => ({ ...common, key: workCardAnchor("finding", item.id), project: item.project.id, title: item.title, kind: item.status === "accepted" ? "建议待应用" : "建议待审", confirm: true })),
    ...(work.cross_schedule_approvals ?? []).map(item => ({ ...common, key: workCardAnchor("cross", item.id, item.project.id), project: item.project.id, title: item.title, kind: "跨项目确认", confirm: true })),
    ...(work.id_design_actions ?? []).map(item => ({ ...common, key: workCardAnchor(`id-${item.kind}`, item.id), project: item.project.id, title: item.title, kind: item.kind === "freeze" ? "冻结确认" : "交付接收", confirm: true })),
    ...(work.cost_freeze_approvals ?? []).map(item => ({ ...common, key: workCardAnchor("cost-freeze", item.id), project: item.project.id, title: item.title, kind: "成本冻结待批", confirm: true })),
    ...(work.task_takeover_actions ?? []).map(item => ({ ...common, key: workCardAnchor("takeover", item.id), project: item.project.id, title: item.title, kind: item.mode === "review" ? "交接待接收" : "交接待补齐", due: item.due_date, blocked: item.status === "blocked", high: ["high", "critical"].includes(item.priority), confirm: item.mode === "review", score: ranks[item.priority] ?? 0 })),
    ...(work.risk_followup_actions ?? []).map(item => ({ ...common, key: workCardAnchor("risk-result", item.id), project: item.project.id, title: item.title, kind: item.mode === "review" ? "风险结果接收" : "风险结果提交／补齐", confirm: item.mode === "review" })),
    ...(work.change_execution_confirmations ?? []).map(item => ({ ...common, key: workCardAnchor("change", item.id), project: item.project.id, title: item.title, kind: "执行结果确认", confirm: true })),
  ];
  const projects = new Map([...work.tasks, ...work.issues, ...work.risks, ...work.capa_actions, ...work.gate_signoffs, ...work.findings, ...(work.cross_schedule_approvals ?? []), ...(work.id_design_actions ?? []), ...(work.change_execution_confirmations ?? []), ...(work.risk_followup_actions ?? []), ...(work.task_takeover_actions ?? []), ...(work.cost_freeze_approvals ?? [])].map(item => [item.project.id, item.project]));
  const matches = (entry: Entry, key: Filter) => key === "all" || key === "overdue" && !!entry.due && entry.due < today || key === "today" && entry.due === today || key === "blocked" && entry.blocked || key === "high" && entry.high || key === "confirm" && entry.confirm;
  const base = entries.filter(entry => (!project || entry.project === project) && `${entry.title} ${entry.kind} ${projects.get(entry.project)?.name} ${projects.get(entry.project)?.code}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const order = (entry: Entry) => entry.due && entry.due < today ? 0 : entry.blocked ? 1 : entry.due === today ? 2 : entry.high ? 3 : entry.confirm ? 4 : 5;
  const selected = base.filter(entry => matches(entry, filter)).sort((a, b) => order(a) - order(b) || (a.due ?? "9999").localeCompare(b.due ?? "9999") || b.score - a.score || a.key.localeCompare(b.key));
  const total = Object.values(work.counts).reduce((sum, value) => sum + (value ?? 0), 0);
  return <section aria-label="工作优先事项" className="mt-4 space-y-3 rounded-lg border bg-card p-4">
    <h2 className="font-semibold">先处理这些工作</h2>
    <p className="text-xs text-muted-foreground">按逾期、阻塞、今日到期、高优先、待确认整理。筛选只作用于当前已加载的 {entries.length} 条快捷入口，原工作卡和未提交内容保留。{total > entries.length ? ` 全部待办共 ${total} 条，未加载的事项不计入下方分类。` : ""}</p>
    <div className="flex flex-wrap gap-2"><label className="text-xs">项目<select className="ml-2 max-w-full rounded-md border bg-background p-2" value={project} onChange={event => { setProject(event.target.value); setExpanded(false); }}><option value="">已加载的全部项目</option>{[...projects.values()].sort((a,b) => a.name.localeCompare(b.name, "zh-CN")).map(item => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}</select></label><input aria-label="查找已加载的工作" className="min-w-0 flex-1 rounded-md border bg-background p-2 text-sm" placeholder="搜索标题、项目或类型" value={search} onChange={event => { setSearch(event.target.value); setExpanded(false); }}/></div>
    <div className="flex flex-wrap gap-2" role="group" aria-label="优先事项分类">{filters.map(item => <Button key={item.key} size="sm" variant={filter === item.key ? "default" : "outline"} aria-pressed={filter === item.key} onClick={() => { setFilter(item.key); setExpanded(false); }}>{item.label} {base.filter(entry => matches(entry, item.key)).length}</Button>)}</div>
    <ol className="space-y-2">{(expanded ? selected : selected.slice(0, 8)).map(entry => <li key={entry.key}><a href={`#${entry.key}`} className="flex min-h-11 flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted/50"><span className="text-xs text-primary">{entry.kind}</span><span className="min-w-0 flex-1 break-words">{entry.title}</span><span className="text-xs text-muted-foreground">{projects.get(entry.project)?.code}</span><span className="text-xs">{entry.due ? `${entry.due < today ? "逾期 " : entry.due === today ? "今日 " : ""}${entry.due}` : entry.blocked ? "阻塞待处理" : entry.confirm ? "等待办理" : "未设日期"}</span><span className="text-primary">定位工作卡</span></a></li>)}</ol>
    {!selected.length && <p className="text-sm text-muted-foreground">当前已加载范围内没有符合条件的工作。</p>}
    {selected.length > 8 && <Button size="sm" variant="ghost" onClick={() => setExpanded(value => !value)}>{expanded ? "收起快捷入口" : `显示全部 ${selected.length} 个匹配入口`}</Button>}
  </section>;
}
