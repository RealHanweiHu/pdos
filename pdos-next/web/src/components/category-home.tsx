"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Books, ClipboardText, FileText, Package, Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { ProposalList } from "@/components/proposals/proposal-list";

type Api = typeof browserApi;
type Product = { id: string; name: string; purpose: string };
type KnowledgeItem = { kind: string; content: Record<string, unknown>; origin: string; status: string };
type ParameterItem = { parameter_id: string; version: number; key: string; name: string; unit: string | null; value_type: string };
const kindLabels: Record<string, string> = { boundary: "品类边界", segment: "细分", competitor: "竞品", voice: "用户声音", regulation: "法规认证", research_question: "研究问题" };
const originLabels: Record<string, string> = { human: "人工", ai_draft: "AI 草稿", imported: "导入" };

function knowledgeTitle(item: KnowledgeItem): string {
  for (const key of ["title", "name", "text", "summary", "question", "topic"]) {
    const value = item.content?.[key];
    if (typeof value === "string" && value.trim()) return value.slice(0, 120);
  }
  return kindLabels[item.kind] ?? item.kind;
}

export function CategoryHome({ categoryId, categoryName, api, onOpenWorkbench, onOpenPai }: {
  categoryId: string; categoryName: string; api: Api;
  onOpenWorkbench: (bench: "products" | "knowledge", productId?: string) => void;
  onOpenPai: () => void;
}) {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [knowledge, setKnowledge] = useState<KnowledgeItem[] | null>(null);
  const [parameters, setParameters] = useState<ParameterItem[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    const failures: string[] = [];
    void Promise.all([
      api<Product[]>(`v1/categories/${categoryId}/products`).then(value => { if (active) setProducts(value); }).catch(failure => failures.push((failure as Error).message)),
      api<{ items: KnowledgeItem[] }>(`v1/categories/${categoryId}/knowledge?page_size=50`).then(value => { if (active) setKnowledge(value.items); }).catch(failure => failures.push((failure as Error).message)),
      api<{ items: ParameterItem[] }>(`v1/categories/${categoryId}/parameters?page_size=50`).then(value => { if (active) setParameters(value.items); }).catch(failure => failures.push((failure as Error).message)),
    ]).then(() => { if (active) setErrors(failures); });
    return () => { active = false; };
  }, [api, categoryId]);

  return <>
    <div className="workspace-page-heading"><div className="min-w-0"><h1>{categoryName}</h1><p>品类是权限范围根：共享知识、规格字典、型号与立项提案都在这里汇聚，项目经提案 G0 评审后建立。</p></div><Button variant="outline" onClick={() => onOpenWorkbench("products")}>打开品类工作台<ArrowRight size={14}/></Button></div>
    {errors.map(message => <p key={message} role="status" className="subtle">部分内容暂不可读：{message}</p>)}
    <section className="panel mb-6" aria-label="立项提案">
      <div className="mb-4 flex items-center gap-2"><FileText className="text-primary" aria-hidden="true"/><h2 className="font-semibold">立项提案</h2><span className="subtle ml-auto">一案一页 · 唯一关卡是具名 G0 评审</span></div>
      <p className="subtle mb-4">客户需求、自主新品、派生迭代三个入口都落到同一种立项提案；AI 先起草，人做取舍。从对话创建的提案一律私有。</p>
      <div className="mb-5"><Button onClick={onOpenPai}><Sparkle/>打开品类小Pai，起草立项提案</Button></div>
      <ProposalList categoryId={categoryId} api={api} />
    </section>
    <div className="grid items-start gap-6 lg:grid-cols-2">
      <section className="panel" aria-label="型号列表">
        <div className="mb-4 flex items-center gap-2"><Package className="text-primary" aria-hidden="true"/><h2 className="font-semibold">型号</h2><span className="subtle ml-auto">{products?.length ?? "…"} 个</span></div>
        {!products && <p role="status" className="subtle">正在读取型号…</p>}
        {products?.length === 0 && <p className="subtle">尚无型号。进入品类工作台建立型号范围。</p>}
        <div className="space-y-3">{products?.map(item => <div key={item.id} className="flex items-center gap-3 border-t border-border pt-3 first:border-0 first:pt-0">
          <div className="min-w-0 flex-1"><p className="truncate font-medium">{item.name}</p><p className="subtle truncate">{item.purpose}</p></div>
          <Button size="sm" variant="ghost" onClick={() => onOpenWorkbench("products", item.id)}>打开<ArrowRight size={14}/></Button>
        </div>)}</div>
      </section>
      <section className="panel" aria-label="共享知识">
        <div className="mb-4 flex items-center gap-2"><Books className="text-primary" aria-hidden="true"/><h2 className="font-semibold">共享知识</h2><Button className="ml-auto" size="sm" variant="ghost" onClick={() => onOpenWorkbench("knowledge")}>进入知识区<ArrowRight size={14}/></Button></div>
        {!knowledge && <p role="status" className="subtle">正在读取知识…</p>}
        {knowledge?.length === 0 && <p className="subtle">尚无共享知识。品类研究产生的事实经确认后在这里共享。</p>}
        <div className="space-y-3">{knowledge?.slice(0, 6).map((item, index) => <div key={index} className="flex items-center gap-3 border-t border-border pt-3 first:border-0 first:pt-0">
          <div className="min-w-0 flex-1"><p className="break-words text-sm">{knowledgeTitle(item)}</p></div>
          <span className="workspace-state">{kindLabels[item.kind] ?? item.kind}</span>
          <span className="subtle">{originLabels[item.origin] ?? item.origin}</span>
        </div>)}</div>
      </section>
    </div>
    <section className="panel mt-6" aria-label="规格字典">
      <div className="mb-4 flex items-center gap-2"><ClipboardText className="text-primary" aria-hidden="true"/><h2 className="font-semibold">规格字典</h2><span className="subtle ml-auto">{parameters?.length ?? "…"} 条参数当前版本</span></div>
      {!parameters && <p role="status" className="subtle">正在读取规格字典…</p>}
      {parameters?.length === 0 && <p className="subtle">尚无字典参数。规格条目的键、名称、单位与测试条件都来自字典；缺失时按人工映射逐步补齐。</p>}
      <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2">{parameters?.slice(0, 12).map(item => <div key={`${item.parameter_id}:${item.version}`} className="flex items-baseline justify-between gap-3 border-t border-border pt-2 text-sm first:border-0 first:pt-0">
        <span className="min-w-0 truncate">{item.name}</span>
        <span className="subtle shrink-0">{item.unit ?? "无单位"} · v{item.version}</span>
      </div>)}</div>
    </section>
  </>;
}
