"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight } from "@phosphor-icons/react";
import { browserApi } from "@/lib/browser-api";
import { Workspace } from "./workspace";
import { Button } from "./ui/button";
import type { PaiContext } from "./pai-rail";
import styles from "./projects/project-professional.module.css";

const panels = [["definition", "产品定义"], ["variants", "平台与差异"], ["originals", "文件"], ["sources", "原文与事实"], ["activity", "活动"], ["accounting", "费用记录"], ["lifecycle", "保留与隔离"]] as const;
function initialPanel() {
  if (typeof window === "undefined") return "definition";
  const params = new URLSearchParams(window.location.search), requested = params.get("task") || params.get("view");
  if (requested === "files") return "originals";
  return panels.find(([id]) => id === requested)?.[0] ?? "definition";
}
export function ModelWorkspace({ categoryId, productId, onBack, onPaiContext }: { categoryId: string; productId: string; onBack: () => void; onPaiContext: (context: PaiContext | null) => void }) {
  const [panel, setPanel] = useState<string>(initialPanel);
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ product: { id: string; name: string; purpose: string } | null; error: string } | null>(null);
  useEffect(() => {
    let active = true;
    browserApi<{ product: { id: string; name: string; purpose: string } }>(`v1/categories/${categoryId}/products/${productId}/workspace`).then(value => {
      if (value.product.id !== productId) throw new Error("型号范围无法核对，请重新读取。");
      if (active) setReading({ product: value.product, error: "" });
    }).catch(error => { if (active) setReading({ product: null, error: error.message }); });
    return () => { active = false; };
  }, [categoryId, productId, attempt]);
  useEffect(() => {
    const read = () => setPanel(initialPanel());
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);
  function choose(value: string) {
    setPanel(value);
    const params = new URLSearchParams(window.location.search);
    params.set("view", value); params.delete("task");
    window.history.replaceState(null, "", `?${params}`);
  }
  return <section className={styles.surface} aria-label="型号与定义">
    <Button size="xs" variant="ghost" onClick={onBack}><ArrowLeft/>返回品类</Button>
    <header className="workspace-page-heading"><div><h1>{reading?.product?.name ?? "型号与定义"}</h1><p>{reading?.product?.purpose ?? "产品定义与项目实施相连，父版和派生差异各自保留。"}</p></div><Button size="sm" variant="outline" onClick={() => choose("variants")}>准备派生<ArrowUpRight/></Button></header>
    {reading?.error ? <div role="alert"><p>{reading.error}</p><Button variant="outline" size="sm" onClick={() => setAttempt(value => value + 1)}>重新读取型号</Button></div> : !reading ? <p role="status">正在读取型号…</p> : <>
      <nav className={styles.tabs} aria-label="型号视图">{panels.map(([id, label]) => <button type="button" key={id} aria-pressed={panel === id} onClick={() => choose(id)}>{label}</button>)}</nav>
      <div className={styles.body}><Workspace categoryId={categoryId} fixedProductId={productId} embeddedPanel={panel} onPaiContext={onPaiContext}/></div>
    </>}
  </section>;
}
