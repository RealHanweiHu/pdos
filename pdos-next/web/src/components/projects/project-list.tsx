"use client";

import { useEffect, useState } from "react";
import { ArrowRight, FolderSimple, Package } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { groupByCategory, projectStateLabel, readPortfolio, type Portfolio } from "@/lib/portfolio-reads";
import type { browserApi } from "@/lib/browser-api";

type Api = typeof browserApi;
const visibilityLabels: Record<string, string> = { private: "私有", category: "品类共享", audience: "指定受众" };

export function ProjectList({ api, onOpenProject, onOpenWorkbench }: {
  api: Api;
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenWorkbench: (categoryId: string, productId: string) => void;
}) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void readPortfolio(api).then(next => { if (active) setPortfolio(next); }).catch(failure => { if (active) setError((failure as Error).message); });
    return () => { active = false; };
  }, [api]);

  const groups = portfolio ? groupByCategory(portfolio) : [];
  const total = portfolio?.projects.length ?? 0;

  return <>
    <div className="workspace-page-heading"><div className="min-w-0"><h1>项目列表</h1><p>本人权限内的全部研发项目，按品类与型号归属。权限过滤由服务端完成；跨品类投影接入前按品类逐一汇总。</p></div></div>
    {error && <p role="alert" className="workspace-read-error">{error}</p>}
    {portfolio?.readErrors.map(item => <p key={item.path} role="status" className="subtle">部分范围暂不可读：{item.message}</p>)}
    {!portfolio && <p role="status" className="subtle">正在读取项目…</p>}
    {portfolio && total === 0 && <div className="workspace-empty" role="status"><Package size={24} aria-hidden="true"/><p>没有可见项目。立项提案经具名 G0 批准后建立项目；请到产品品类工作区起草提案。</p></div>}
    {groups.map(group => <section key={group.category.id} className="workspace-overview mb-8" aria-label={`${group.category.name}的项目`}>
      <header><h2>{group.category.name}</h2><span className="subtle">{group.products.reduce((count, item) => count + item.entries.length, 0)} 个项目</span></header>
      {group.products.map(productGroup => <div key={productGroup.product.id} className="mb-4">
        <p className="subtle mb-1 mt-4">{productGroup.product.name}</p>
        {productGroup.entries.map(entry => <div className="workspace-record-row" key={entry.project.id}>
          <FolderSimple size={18} aria-hidden="true"/>
          <div className="min-w-0 flex-1">
            <p className="break-words font-medium">{entry.project.name}</p>
            <p className="subtle truncate">{entry.project.definition.title} · 固定 v{entry.project.definition.revision} · {visibilityLabels[entry.project.visibility] ?? entry.project.visibility}</p>
          </div>
          <span className="workspace-state">{projectStateLabel(entry)}</span>
          <span className="workspace-revision">v{entry.project.revision}</span>
          <Button size="sm" variant="outline" onClick={() => onOpenProject(entry.category.id, entry.project.id)}>驾驶舱</Button>
          <Button size="sm" variant="ghost" onClick={() => onOpenWorkbench(entry.category.id, entry.product.id)}>工作台<ArrowRight size={14}/></Button>
        </div>)}
      </div>)}
    </section>)}
  </>;
}
