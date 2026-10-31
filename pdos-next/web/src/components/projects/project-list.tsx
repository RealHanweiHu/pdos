"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { readPortfolio, type Portfolio } from "@/lib/portfolio-reads";
import { forecastAxis, projectForecast, projectOwner } from "@/lib/project-presentation";
import type { browserApi } from "@/lib/browser-api";
import { ProjectDirectoryView, type ProjectDirectoryEntry } from "./project-directory-view";

function dateLabel(value: string | null): string {
  if (!value) return "未知";
  const date = new Date(value);
  return `${String(date.getUTCMonth() + 1).padStart(2, "0")}月${String(date.getUTCDate()).padStart(2, "0")}日`;
}

export function ProjectList({ api, principalId = "", onOpenProject, onOpenPlan = onOpenProject, onStartProposal }: {
  api: typeof browserApi; principalId?: string;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenPlan?: (categoryId: string, projectId: string) => void;
  onStartProposal?: () => void;
}) {
  const [reading, setReading] = useState<{ api: typeof browserApi; scope: string; portfolio: Portfolio | null; error: string } | null>(null);
  const [reload, setReload] = useState(0);
  const scope = JSON.stringify([principalId, reload]);
  const current = reading?.api === api && reading.scope === scope ? reading : null;
  const portfolio = current?.portfolio ?? null, error = current?.error ?? "";
  useEffect(() => {
    let active = true;
    void readPortfolio(api).then(next => { if (active) setReading({ api, scope, portfolio: next, error: "" }); }).catch(failure => { if (active) setReading({ api, scope, portfolio: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, scope]);

  const source = portfolio?.projects ?? [];
  const axis = forecastAxis(source);
  const entries: ProjectDirectoryEntry[] = source.map(entry => {
    const forecast = projectForecast(entry);
    const governance = entry.project.governance, timeline = governance?.timeline;
    const position = (at: string | null | undefined) => axis && at && Number.isFinite(Date.parse(at)) ? (Date.parse(at) - axis.start) / (axis.end - axis.start) * 100 : undefined;
    const commitments = timeline?.commitments.filter(c => c.promised_at) ?? [];
    const validRange = forecast.earliest && forecast.latest && Date.parse(forecast.earliest) <= Date.parse(forecast.latest);
    return {
      id: entry.project.id, name: entry.project.name, phase: governance?.current_stage?.name ?? (governance?.completed ? "阶段已完成" : null), health: governance?.health.label ?? null,
      stages: governance?.stages.map(s => s.name), at: governance?.stages.findIndex(s => s.status === "current"),
      lead: projectOwner(entry), next: governance?.next_gate_name ?? null, gateDates: `${commitments.map(c => dateLabel(c.promised_at)).join("、") || "承诺未知"} / ${dateLabel(timeline?.forecast?.latest_finish ?? null)}`,
      note: entry.project.latest_status_update?.fact_summary || entry.project.purpose,
      dates: {
        基线: { label: dateLabel(timeline?.baseline?.latest_finish ?? null), position: position(timeline?.baseline?.latest_finish) },
        预测: { label: forecast.earliest === forecast.latest ? dateLabel(forecast.latest) : `${dateLabel(forecast.earliest)} — ${dateLabel(forecast.latest)}`,
          position: axis && validRange ? (Date.parse(forecast.latest!) - axis.start) / (axis.end - axis.start) * 100 : undefined,
          description: timeline?.task_key ? "明确关联的门禁里程碑预测" : "项目计划完成时间预测；尚未关联门禁里程碑" },
        承诺: { label: commitments.map(c => dateLabel(c.promised_at)).join("、") || "未提供", position: commitments.length === 1 ? position(commitments[0].promised_at) : undefined, description: "各责任人对接收者的原承诺分别保留" }, 实际: { label: dateLabel(timeline?.actual ?? null), position: position(timeline?.actual) },
      },
    };
  });
  function open(id: string, action: (categoryId: string, projectId: string) => void) {
    const entry = source.find(item => item.project.id === id);
    if (entry) action(entry.category.id, entry.project.id);
  }
  const retry = <Button size="sm" variant="outline" onClick={() => setReload(value => value + 1)}>重新读取</Button>;
  return <ProjectDirectoryView entries={entries} timeScale={axis ? Array.from({ length: 4 }, (_, index) => dateLabel(new Date(axis.start + (axis.end - axis.start) * index / 3).toISOString())) : ["暂无可读日期"]}
    onOpenProject={id => open(id, onOpenProject)} onOpenPlan={id => open(id, onOpenPlan)} onStartProposal={onStartProposal}>
    {error && <div className="workspace-read-error" role="alert"><p>{error}</p>{retry}</div>}
    {!current && <p className="subtle" role="status">正在读取项目…</p>}
    {!!portfolio?.readErrors.length && <div className="workspace-read-error" role="status">{portfolio.readErrors.map(item => <p key={item.path}>部分范围暂不可读：{item.message}</p>)}{retry}</div>}
    {portfolio && !source.length && !portfolio.readErrors.length && <p className="workspace-empty" role="status">暂无可见项目。立项通过后，项目会出现在这里。</p>}
  </ProjectDirectoryView>;
}
