"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowRight, FolderSimple, Package } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { groupByCategory, projectStateLabel, readPortfolio, type Portfolio } from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";
import { ProjectStatusSummary } from "./project-status-summary";

type Api = typeof browserApi;
const visibilityLabels: Record<string, string> = { private: "私有", category: "品类共享", audience: "指定受众" };

export function ProjectList({ api, principalId = "", onOpenProject, onOpenWorkbench }: {
  api: Api; principalId?: string;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenWorkbench: (categoryId: string, productId: string, projectId: string) => void;
}) {
  const [reading, setReading] = useState<{ api: Api; scope: string; portfolio: Portfolio | null; error: string } | null>(null);
  const [reload, setReload] = useState(0);

  const scope = JSON.stringify([principalId, reload]);
  const current = reading?.api === api && reading.scope === scope ? reading : null;
  const portfolio = current?.portfolio ?? null, error = current?.error ?? "";

  useEffect(() => {
    let active = true;
    void readPortfolio(api).then(next => { if (active) setReading({ api, scope, portfolio: next, error: "" }); }).catch(failure => { if (active) setReading({ api, scope, portfolio: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, scope]);

  const groups = portfolio ? groupByCategory(portfolio) : [];
  const total = portfolio?.projects.length ?? 0;

  return <>
    <div className="workspace-page-heading"><div className="min-w-0"><h1>项目列表</h1><p>本人可见的研发项目，按品类与型号归属，继续查看计划、风险与未决事项。</p></div><Button variant="outline" onClick={() => { setReading(null); setReload(value => value + 1); }}><ArrowClockwise/>刷新</Button></div>
    {error && <p role="alert" className="workspace-read-error">{error}</p>}
    {portfolio?.asOf && <p className="subtle mb-4">项目资料读取于 <time dateTime={portfolio.asOf}>{new Date(portfolio.asOf).toLocaleString()}</time></p>}
    {portfolio?.readErrors.map(item => <p key={item.path} role="status" className="subtle">部分范围暂不可读：{item.message}</p>)}
    {!portfolio && !error && <p role="status" className="subtle">正在读取项目…</p>}
    {portfolio && !portfolio.readErrors.length && total === 0 && <div className="workspace-empty" role="status"><Package size={24} aria-hidden="true"/><p>没有可见项目。立项提案经具名 G0 批准后建立项目；请到产品品类工作区起草提案。</p></div>}
    {groups.map(group => <section key={group.category.id} className="workspace-overview mb-8" aria-label={`${group.category.name}的项目`}>
      <header><h2>{group.category.name}</h2><span className="subtle">{group.products.reduce((count, item) => count + item.entries.length, 0)} 个项目</span></header>
      {group.products.map(productGroup => <div key={productGroup.product.id} className="mb-4">
        <p className="subtle mb-1 mt-4">{productGroup.product.name}</p>
        {productGroup.entries.map(entry => <div className="workspace-record-row flex-col sm:flex-row" key={entry.project.id}>
          <div className="flex w-full min-w-0 flex-1 items-center gap-3 sm:w-auto">
            <FolderSimple size={18} className="shrink-0 text-muted-foreground" aria-hidden="true"/>
            <div className="min-w-0 flex-1">
              <p className="break-words font-medium">{entry.project.name}</p>
              <ProjectStatusSummary update={entry.project.latest_status_update}/>
              <p className="subtle truncate">{entry.project.definition.title} · 固定 v{entry.project.definition.revision} · {visibilityLabels[entry.project.visibility] ?? entry.project.visibility}</p>
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-3 sm:w-auto">
            <span className="workspace-state">{projectStateLabel(entry)}</span>
            <span className="workspace-revision">v{entry.project.revision}</span>
            <Button size="sm" variant="outline" onClick={() => onOpenProject(entry.category.id, entry.project.id)}>驾驶舱</Button>
            <Button size="sm" variant="ghost" onClick={() => onOpenWorkbench(entry.category.id, entry.product.id, entry.project.id)}>工作台<ArrowRight size={14}/></Button>
          </div>
        </div>)}
      </div>)}
    </section>)}
  </>;
}
