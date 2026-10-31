"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ModelWorkspace } from "@/components/model-workspace";
import { Workspace } from "@/components/workspace";
import { CategoryCreateForm } from "@/components/category-create/category-create-form";
import { ArrowUpRight, MagnifyingGlass, Plus, Sparkle, X } from "@phosphor-icons/react";
import { ProposalList } from "@/components/proposals/proposal-list";
import styles from "./category-home.module.css";
import { CategoryHome } from "@/components/category-home";
import { browserApi } from "@/lib/browser-api";
import type { CreatedCategory } from "@/components/category-create/contracts";
import type { MaterialContext } from "./category-material-editor";
import type { PaiContext } from "@/components/pai-rail";

type Category = { id: string; name: string; purpose: string; owner_name?: string | null; readable_product_count?: number; my_draft_count?: number };

/** 产品品类工作区：品类选择 → 品类主页 → 品类工作台（内嵌）。 */
export function CategoryArea({ area, categories, categoryId, projectId, onSelectCategory, onCreated, onPaiContext, onOpenPai }: {
  area: "category" | "knowledge";
  categories: Category[];
  categoryId: string;
  projectId: string;
  onSelectCategory: (id: string) => void;
  onCreated: (category: CreatedCategory) => void;
  onPaiContext: (context: PaiContext | null) => void;
  onOpenPai: (options?: { presetSkillKeys?: string[] }) => void;
}) {
  const updateMaterialContext = useCallback((material: MaterialContext | undefined) => onPaiContext({ categoryId, productId: "", sources: [], material }), [categoryId, onPaiContext]);
  const createDialog = useRef<HTMLDialogElement>(null);
  const createTrigger = useRef<HTMLButtonElement>(null);
  const [query, setQuery] = useState("");
  const [creationNotice, setCreationNotice] = useState("");
  const bench = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("bench") ?? "" : "";
  const proposals = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("focus") === "proposals";
  const category = categories.find(item => item.id === categoryId);

  useEffect(() => {
    if (area !== "knowledge" || !categoryId || bench === "knowledge") return;
    const params = new URLSearchParams(window.location.search);
    params.set("bench", "knowledge"); params.set("view", "sources");
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, [area, categoryId, bench]);

  useEffect(() => { if (!bench && area === "category") onPaiContext(categoryId ? { categoryId, productId: "", sources: [] } : null); }, [bench, area, categoryId, onPaiContext]);

  function created(next: CreatedCategory) {
    createDialog.current?.close();
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
    const visible = categories.filter(item => `${item.name} ${item.purpose}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    return <>
      <div className="workspace-page-heading"><div><h1>品类</h1><p>从共享依据出发，管理型号与产品方向。</p></div><div className={styles.actions}><Button ref={createTrigger} size="sm" onClick={() => createDialog.current?.showModal()}><Plus/>新建品类</Button></div></div>
      <div className={styles.listToolbar}><span>{visible.length} 个品类</span><label className={styles.search}><MagnifyingGlass size={14} aria-hidden="true"/><input type="search" aria-label="搜索品类" placeholder="搜索品类" value={query} onChange={event => setQuery(event.target.value)}/></label></div>
      <div className={styles.categoryList}><div className={styles.categoryColumns}><span>品类</span><span>主要场景</span><span>负责人</span><span>型号</span><span>我的草稿</span></div>{visible.map(item => <button type="button" key={item.id} className={styles.categoryRow} onClick={() => onSelectCategory(item.id)}><strong>{item.name}<ArrowUpRight size={12} aria-hidden="true"/></strong><span>{item.purpose || "未填写"}</span><span>{item.owner_name ?? "未提供"}</span><span>{item.readable_product_count ?? "—"}</span><span>{item.my_draft_count ?? "—"}</span></button>)}</div>
      {visible.length === 0 && <p className={styles.empty}>{query ? "没有匹配的品类" : "尚无可管理品类，可以新建或让小Pai协助整理。"}</p>}
      <dialog ref={createDialog} aria-label="新建品类" onClose={() => createTrigger.current?.focus()}><div className={styles.dialogHeading}><h2>新建品类</h2><Button size="icon" variant="ghost" aria-label="关闭新建品类" onClick={() => createDialog.current?.close()}><X/></Button></div><button type="button" className={styles.paiCreate} onClick={() => { createDialog.current?.close(); onOpenPai({ presetSkillKeys: ["category_framing"] }); }}><Sparkle size={16}/>与小Pai一起创建<ArrowUpRight size={14}/></button><CategoryCreateForm onCreated={created}/></dialog>
    </>;
  }

  if (!bench && proposals && category) return <section aria-label="立项提案"><div className="workspace-page-heading"><div><h1>立项提案</h1><p>把想法和需求整理为可判断的产品方案。</p></div><Button size="sm" onClick={() => { updateMaterialContext({ kind: "proposal", title: `${category.name} · 新提案`, draft: { category_name: category.name, purpose: category.purpose }, request: { id: crypto.randomUUID(), prompt: "请根据当前品类的竞品、用户声音和规格字典，起草一份私有立项提案。先读取可用资料并列出待补充问题，提供可编辑候选，确认后保存。" } }); onOpenPai(); }}><Plus/>新建提案</Button></div><ProposalList key={categoryId} categories={categories} categoryId={categoryId} api={browserApi}/></section>;

  if (!bench && area === "category") {
    return <>
      {creationNotice && <p role="status" className="mb-4 break-all text-sm text-muted-foreground">{creationNotice}</p>}
      {categories.length > 0 && !category && <div className="panel mb-4"><p>此品类当前不可见。请返回选择其他品类。</p><Button className="mt-3" variant="outline" onClick={() => onSelectCategory("")}>返回品类列表</Button></div>}
      <CategoryHome key={categoryId} categoryId={categoryId} categoryName={category?.name ?? "已选品类"} categoryPurpose={category?.purpose ?? ""} categoryOwner={category?.owner_name} api={browserApi} onBack={() => onSelectCategory("")} onOpenWorkbench={openWorkbench} onPaiContext={updateMaterialContext} onOpenPai={context => { updateMaterialContext(context); onOpenPai(); }} />
    </>;
  }

  const modelId = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("product") ?? "";
  if (bench === "products" && modelId) return <ModelWorkspace key={`${categoryId}:${modelId}`} categoryId={categoryId} productId={modelId} onBack={() => onSelectCategory(categoryId)} onPaiContext={onPaiContext}/>;

  return <Workspace key={categoryId} categoryId={categoryId} projectId={projectId} onPaiContext={onPaiContext} />;
}
