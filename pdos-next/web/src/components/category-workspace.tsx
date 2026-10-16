"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Workspace } from "@/components/workspace";
import { CategoryCreateForm } from "@/components/category-create/category-create-form";
import { PersonalXiaopai } from "@/components/category-create/personal-xiaopai";
import { CategoryHome } from "@/components/category-home";
import { browserApi } from "@/lib/browser-api";
import type { CreatedCategory } from "@/components/category-create/contracts";
import type { PaiContext } from "@/components/pai-rail";

type Category = { id: string; name: string; purpose: string };

/** 产品品类工作区：品类选择 → 品类主页 → 品类工作台（内嵌）。 */
export function CategoryArea({ area, categories, categoryId, projectId, onSelectCategory, onCreated, onPaiContext, onOpenPai }: {
  area: "category" | "knowledge";
  categories: Category[];
  categoryId: string;
  projectId: string;
  onSelectCategory: (id: string) => void;
  onCreated: (category: CreatedCategory) => void;
  onPaiContext: (context: PaiContext | null) => void;
  onOpenPai: () => void;
}) {
  const [creationNotice, setCreationNotice] = useState("");
  const bench = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("bench") ?? "" : "";
  const category = categories.find(item => item.id === categoryId);

  useEffect(() => {
    if (area !== "knowledge" || !categoryId || bench === "knowledge") return;
    const params = new URLSearchParams(window.location.search);
    params.set("bench", "knowledge"); params.set("view", "sources");
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, [area, categoryId, bench]);

  function created(next: CreatedCategory) {
    onCreated(next);
    setCreationNotice(`品类已创建。${next.receiptId ? `回执：${next.receiptId}。` : ""}${next.continuationState === "awaiting_delivery" ? "小 Pai 的后续通知等待派送，创建已完成。" : ""}`);
  }
  function openWorkbench(bench: "products" | "knowledge", productId?: string) {
    const params = new URLSearchParams(window.location.search);
    params.set("bench", bench);
    params.delete("view"); params.delete("task");
    if (productId) params.set("product", productId);
    window.history.pushState(null, "", `?${params.toString()}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  if (!categoryId) {
    return <>
      <div className="workspace-page-heading"><div className="min-w-0"><h1>产品品类工作区</h1><p>品类是型号、立项提案与共享知识的范围根，也是项目的前置部分。选择品类进入，或与小Pai 对话新建。</p></div></div>
      <div className="grid gap-3 sm:grid-cols-2">{categories.map(item =>
        <button key={item.id} className="panel text-left" onClick={() => onSelectCategory(item.id)}>
          <strong>{item.name}</strong><p className="mt-2 text-sm text-muted-foreground">{item.purpose}</p>
        </button>)}
      </div>
      {categories.length === 0 && <p className="subtle mt-4">还没有可见品类。从下方的对话或手动入口建立第一个品类。</p>}
      <section className="panel mt-6" aria-label="新建品类">
        <h2 className="mb-4 font-semibold">新建品类</h2>
        <PersonalXiaopai onCreated={created} />
        <details className="mt-6"><summary className="cursor-pointer font-medium">手动建立（模型不可用时的备选入口）</summary><div className="mt-4"><CategoryCreateForm onCreated={created} /></div></details>
      </section>
    </>;
  }

  if (!bench && area === "category") {
    return <>
      {creationNotice && <p role="status" className="mb-4 break-all text-sm text-muted-foreground">{creationNotice}</p>}
      {categories.length > 0 && !category && <div className="panel mb-4"><p>此品类当前不可见。请返回选择其他品类。</p><Button className="mt-3" variant="outline" onClick={() => onSelectCategory("")}>返回品类列表</Button></div>}
      <CategoryHome key={categoryId} categoryId={categoryId} categoryName={category?.name ?? "已选品类"} api={browserApi} onOpenWorkbench={openWorkbench} onOpenPai={onOpenPai} />
    </>;
  }

  return <Workspace key={categoryId} categoryId={categoryId} projectId={projectId} onPaiContext={onPaiContext} />;
}
