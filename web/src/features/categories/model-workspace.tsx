"use client";

/* Operate (10-25 platform design, 型号与定义): one overview page with the facts
   that matter (purpose, definition, platform, projects) and a version / derivation
   table. Each professional area opens on demand in the shared drawer; the
   original controlled operations inside it are unchanged. */
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, ArrowUpRight } from "@phosphor-icons/react";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { readPortfolio } from "@/lib/portfolio-reads";
import { isLatestDefinition, type DefinitionList, type DefinitionRevision } from "@/lib/product-view";
import { kindLabels, type Variant, type VariantList } from "./lib/variant-view";
import type { PlatformList } from "./lib/platform-view";
import { Workspace } from "../shell/workspace";
import { Button } from "@/components/ui/button";
import { RetainedSheet } from "@/components/ui/detail-sheet";
import type { PaiContext } from "../xiaopai/pai-rail";
import styles from "./model-workspace.module.css";
import professional from "../projects/project-professional.module.css";

const panels = [["definition", "产品定义"], ["variants", "平台与差异"], ["originals", "文件"], ["sources", "原文与事实"], ["activity", "活动"], ["accounting", "费用记录"], ["lifecycle", "保留与隔离"]] as const;
type Panel = typeof panels[number][0];
type Reading<T> = { value: T; error: "" } | { value: null; error: string };
type Overview = {
  definitions: Reading<DefinitionList>;
  variants: Reading<VariantList>;
  platforms: Reading<PlatformList>;
  projects: Reading<{ id: string; name: string; categoryId: string; status: string }[]>;
};
const settle = async <T,>(read: Promise<T>): Promise<Reading<T>> => read.then(value => ({ value, error: "" as const }), (failure: unknown) => ({ value: null, error: failure instanceof Error ? failure.message : "暂不可读" }));

function requestedPanel(): Panel | "" {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search), requested = params.get("task") || params.get("view");
  if (requested === "files") return "originals";
  return panels.find(([id]) => id === requested)?.[0] ?? "";
}
const visibilityName = (value: string) => value === "private" ? "仅本人" : value === "audience" ? "指定评审人" : "品类授权成员";

export function ModelWorkspace({ categoryId, productId, onBack, onPaiContext }: { categoryId: string; productId: string; onBack: () => void; onPaiContext: (context: PaiContext | null) => void }) {
  const [drawer, setDrawer] = useState<{ open: boolean; panel: Panel }>(() => { const panel = requestedPanel(); return { open: !!panel, panel: panel || "definition" }; });
  const [visited, setVisited] = useState(drawer.open);
  if (drawer.open && !visited) setVisited(true);
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ product: { id: string; name: string; purpose: string } | null; error: string } | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const api = useMemo(() => categoryTransport(categoryId, browserApi), [categoryId]);
  useEffect(() => {
    let active = true;
    browserApi<{ product: { id: string; name: string; purpose: string } }>(`v1/categories/${categoryId}/products/${productId}/workspace`).then(value => {
      if (value.product.id !== productId) throw new Error("型号范围无法核对，请重新读取。");
      if (active) setReading({ product: value.product, error: "" });
    }).catch(error => { if (active) setReading({ product: null, error: error.message }); });
    // Each fact reads on its own; one unreadable part never shows as empty.
    void Promise.all([
      settle(api<DefinitionList>(`v1/products/${productId}/definitions`)),
      settle(api<VariantList>(`v1/products/${productId}/variants`)),
      settle(api<PlatformList>(`v1/products/${productId}/platform-links?page_size=200`)),
      settle(readPortfolio(browserApi).then(portfolio => {
        if (portfolio.readErrors.length) throw new Error(portfolio.readErrors[0].message);
        return portfolio.projects.filter(entry => entry.product.id === productId).map(entry => ({ id: entry.project.id, name: entry.project.name, categoryId: entry.category.id, status: entry.project.status }));
      })),
    ]).then(([definitions, variants, platforms, projects]) => { if (active) setOverview({ definitions, variants, platforms, projects }); });
    return () => { active = false; };
  }, [api, categoryId, productId, attempt]);
  useEffect(() => {
    const read = () => { const panel = requestedPanel(); if (panel) setDrawer({ open: true, panel }); };
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);
  function open(panel: Panel) {
    setDrawer({ open: true, panel });
    const params = new URLSearchParams(window.location.search);
    params.set("view", panel); params.delete("task");
    window.history.replaceState(null, "", `?${params}`);
  }
  function close() {
    setDrawer(current => ({ ...current, open: false }));
    const params = new URLSearchParams(window.location.search);
    params.delete("view"); params.delete("task");
    window.history.replaceState(null, "", `?${params}`);
  }
  const definitions = overview?.definitions.value?.items.filter(item => item.variant_id === null) ?? [];
  const latest = definitions.find(item => isLatestDefinition(item, definitions));
  const published = definitions.filter(item => item.status === "published").sort((a, b) => b.revision - a.revision)[0];
  const linked = overview?.platforms.value?.items.filter(platform => platform.links.some(link => link.attached && link.variant_id === null)) ?? [];
  const variants = overview?.variants.value?.items ?? [];
  const fact = <T,>(value: Reading<T> | undefined, render: (value: T) => string) => !overview ? "正在读取…" : value?.error ? `暂不可读：${value.error}` : render(value!.value as T);
  const label = panels.find(([id]) => id === drawer.panel)?.[1] ?? "型号";
  return <section className={styles.page} aria-label="型号与定义">
    <Button size="xs" variant="ghost" onClick={onBack}><ArrowLeft/>返回品类</Button>
    <header className="workspace-page-heading"><div><h1>{reading?.product?.name ?? "型号与定义"}</h1><p>产品定义与项目实施相连，父版和派生差异各自保留。</p></div><Button size="sm" variant="outline" aria-haspopup="dialog" onClick={() => open("variants")}>准备派生<ArrowUpRight/></Button></header>
    {reading?.error ? <div role="alert"><p>{reading.error}</p><Button variant="outline" size="sm" onClick={() => setAttempt(value => value + 1)}>重新读取型号</Button></div> : !reading ? <p role="status">正在读取型号…</p> : <>
      <dl className={styles.facts}>
        <div><dt>用途</dt><dd>{reading.product?.purpose || "尚未填写"}</dd></div>
        <div><dt>当前定义</dt><dd>{fact(overview?.definitions, () => latest ? `v${latest.revision} 草稿${published ? ` / v${published.revision} 已发布` : ""} · ${latest.specs.length} 项规格` : "尚无可见定义版本")}{(overview?.definitions.value?.unavailable_count ?? 0) > 0 && <small>另有 {overview!.definitions.value!.unavailable_count} 个版本来源待重核</small>}</dd></div>
        <div><dt>平台关联</dt><dd>{fact(overview?.platforms, () => linked.length ? linked.map(platform => `${platform.name}（${platform.code}）`).join("、") : "尚未关联平台")}</dd></div>
        <div><dt>当前项目</dt><dd>{!overview ? "正在读取…" : overview.projects.error ? `暂不可读：${overview.projects.error}` : overview.projects.value!.length ? <span className={styles.links}>{overview.projects.value!.map(project => <a key={project.id} href={`/?${new URLSearchParams({ area: "cockpit", category: project.categoryId, product: productId, project: project.id })}`}>{project.name}</a>)}</span> : "当前没有可见项目"}</dd></div>
      </dl>
      <section className={styles.section} aria-label="版本与派生">
        <header><h2>版本与派生</h2>{overview && !overview.definitions.error && !overview.variants.error && <span>{definitions.length + variants.length} 个</span>}</header>
        {!overview ? <p role="status" className={styles.note}>正在读取版本…</p> : <>
          {(overview.definitions.error || overview.variants.error) && <div role="alert" className={styles.note}><p>{overview.definitions.error || overview.variants.error}，以下仅显示已读取的部分。</p><Button size="sm" variant="outline" onClick={() => setAttempt(value => value + 1)}>重新读取</Button></div>}
          <div className={styles.tableScroll}><table>
            <thead><tr><th>版本 / 变体</th><th>来源</th><th>差异</th><th>状态</th></tr></thead>
            <tbody>
              {[...definitions].sort((a, b) => b.revision - a.revision).map(item => <VersionRow key={item.id} name={`${item.title} · v${item.revision}`} source={item.parent_definition_id ? `续自 v${definitions.find(parent => parent.id === item.parent_definition_id)?.revision ?? "前一版"}` : "首版"} difference={definitionDifference(item)} status={`${item.status === "published" ? "已发布" : "草稿"}${item === latest ? " · 当前" : ""} · ${visibilityName(item.visibility)}`} onOpen={() => open("definition")}/>)}
              {variants.map(variant => <VersionRow key={variant.id} name={`${variant.name} · ${kindLabels[variant.kind]}`} source={variantSource(variant, definitions)} difference={variantDifference(variant)} status={`草稿 v${latestRevision(variant)?.revision ?? 1} · ${visibilityName(variant.visibility)}`} onOpen={() => open("variants")}/>)}
            </tbody>
          </table></div>
          {!definitions.length && !variants.length && !overview.definitions.error && !overview.variants.error && <p className={styles.note}>还没有定义版本。可从“产品定义”核对原文后保存首版草稿。</p>}
        </>}
      </section>
      <nav className={styles.section} aria-label="型号资料与办理">
        <header><h2>资料与办理</h2></header>
        <div className={styles.entries}>{panels.map(([id, name]) => <button type="button" key={id} aria-haspopup="dialog" onClick={() => open(id)}><span>{name}</span><ArrowRight size={13}/></button>)}</div>
      </nav>
      {(visited || drawer.open) && <RetainedSheet open={drawer.open} title={`${reading.product?.name ?? "型号"} · ${label}`} onClose={close}>
        <div className={professional.body}><Workspace categoryId={categoryId} fixedProductId={productId} embeddedPanel={drawer.open ? drawer.panel : ""} onPaiContext={onPaiContext} onSaved={() => setAttempt(value => value + 1)}/></div>
      </RetainedSheet>}
    </>}
  </section>;
}

function VersionRow({ name, source, difference, status, onOpen }: { name: string; source: string; difference: string; status: string; onOpen: () => void }) {
  return <tr><td><button type="button" className={styles.rowLink} aria-haspopup="dialog" onClick={onOpen}>{name}<ArrowRight size={12}/></button></td><td>{source}</td><td>{difference}</td><td>{status}</td></tr>;
}
function definitionDifference(item: DefinitionRevision) {
  return item.parent_definition_id ? (item.differences.length ? `${item.differences.length} 处变化` : "与前一版相同") : `${item.specs.length} 项规格`;
}
function variantSource(variant: Variant, definitions: DefinitionRevision[]) {
  const latest = latestRevision(variant);
  if (!latest) return "父版待核对";
  return `${definitions.find(item => item.id === latest.parent_definition_id)?.title ?? "父版定义"} v${latest.parent_revision}`;
}
function variantDifference(variant: Variant) {
  const latest = latestRevision(variant);
  if (!latest) return "未记录";
  const fields = Object.keys(latest.overrides).filter(key => key !== "specs").length, specs = latest.overrides.specs?.length ?? 0;
  return fields + specs ? `${[fields && `${fields} 项定义`, specs && `${specs} 项规格`].filter(Boolean).join("、")}改写` : "沿用父版";
}
function latestRevision(variant: Variant) {
  return variant.revisions.reduce<Variant["revisions"][number] | undefined>((best, revision) => !best || revision.revision > best.revision ? revision : best, undefined);
}
