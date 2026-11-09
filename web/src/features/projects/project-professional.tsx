"use client";

import { useCallback, useMemo, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { RetainedSheet } from "@/components/ui/detail-sheet";
import { Workspace } from "@/features/shell/workspace";
import { professionalViews, type ProfessionalView } from "@/lib/project-workspace-navigation";
import type { browserApi } from "@/lib/browser-api";
import { ProjectFiles } from "./project-files";
import { projectWorkspaceHref } from "@/lib/project-workspace-navigation";
import { ProjectBuildSummary } from "./project-build-summary";
import { ProjectBuildEngineering } from "./project-build-engineering";
import { ProjectManufacturingPreparation } from "./project-manufacturing-preparation";
import { ProjectPilots } from "./project-pilots";
import { ProjectReleasePackages } from "./project-release-packages";
import { ProjectExternalHandoffs } from "./project-external-handoffs";
import { categoryTransport } from "@/lib/category-transport";
import { recordPanels, type ProfessionalTarget } from "@/lib/professional-records";
import { ProfessionalTargetContext } from "./professional-target";
import { ProjectProfessionalRecords } from "./project-professional-records";
import styles from "./project-professional.module.css";

const summaries: Partial<Record<string, typeof ProjectBuildEngineering>> = { build: ProjectBuildEngineering, manufacturing: ProjectManufacturingPreparation, pilots: ProjectPilots, packages: ProjectReleasePackages, external: ProjectExternalHandoffs, exceptions: ProjectReleasePackages };

export function ProjectProfessional({ view, categoryId, productId, projectId, principalId, api, readVersion, productName = "当前型号", initialPanel = "", onSaved }: {
  view: ProfessionalView; categoryId: string; productId: string; projectId: string;
  principalId: string; api: typeof browserApi; readVersion: number; productName?: string; initialPanel?: string; onSaved?: () => void;
}) {
  const [selected, setSelected] = useState<Record<string, string>>({ [view]: initialPanel });
  const [routePanel, setRoutePanel] = useState(`${view}:${initialPanel}`);
  if (routePanel !== `${view}:${initialPanel}`) {
    setRoutePanel(`${view}:${initialPanel}`);
    if (initialPanel) setSelected(current => ({ ...current, [view]: initialPanel }));
  }
  const scoped = useMemo(() => categoryTransport(categoryId, api), [categoryId, api]);
  const [intent, setIntent] = useState(() => {
    const params = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
    const target: ProfessionalTarget = {};
    for (const key of ["build","request","run","issue","change","feedback","publication"] as const) { const value=params.get(key); if(value && /^[0-9a-f-]{36}$/i.test(value))target[key]=value; }
    return {target,serial:0};
  });
  const routeTargetKey = typeof window === "undefined" ? "" : ["build","request","run","issue","change","feedback","publication"].map(key => new URLSearchParams(window.location.search).get(key) ?? "").join(":");
  const [seenTargetKey, setSeenTargetKey] = useState(routeTargetKey);
  if (seenTargetKey !== routeTargetKey) {
    setSeenTargetKey(routeTargetKey);
    const params = new URLSearchParams(window.location.search), target: ProfessionalTarget = {};
    for (const key of ["build","request","run","issue","change","feedback","publication"] as const) { const value=params.get(key); if(value && /^[0-9a-f-]{36}$/i.test(value))target[key]=value; }
    setIntent(previous=>({target,serial:previous.serial+1}));
  }
  const definition = professionalViews[view];
  const panel = definition.panels.find(([id]) => id === selected[view])?.[0] ?? definition.panels[0][0];
  const panelLabel = definition.panels.find(([id]) => id === panel)?.[1] ?? definition.title;
  const Summary = summaries[panel as keyof typeof summaries];
  // Panels with a compact summary or record list keep their long professional
  // forms in the shared right-side drawer, opened only on demand (D40).
  const listed = !!Summary || recordPanels.has(panel);
  const inline = panel !== "summary" && panel !== "files" && !listed;
  const [drawer, setDrawer] = useState<{ open: boolean; panel: string }>(() => ({ open: !!initialPanel && Object.keys(intent.target).length > 0 && (!!summaries[initialPanel as keyof typeof summaries] || recordPanels.has(initialPanel)), panel: initialPanel }));
  const [drawerVisited, setDrawerVisited] = useState(drawer.open);
  if (drawer.open && !drawerVisited) setDrawerVisited(true);
  const [inlineVisited, setInlineVisited] = useState(inline);
  if (inline && !inlineVisited) setInlineVisited(true);
  const [savedVersion, setSavedVersion] = useState(0);
  const saved = useCallback(() => { setSavedVersion(value => value + 1); onSaved?.(); }, [onSaved]);
  const scope = { categoryId, productId, projectId, principalId, api, readVersion: readVersion + savedVersion };
  const drawerLabel = definition.panels.find(([id]) => id === drawer.panel)?.[1] ?? definition.title;
  function choose(value: string) {
    setSelected(current => ({ ...current, [view]: value }));
    const params = new URLSearchParams(window.location.search);
    params.set("projectView", view); params.set("panel", value);
    window.history.replaceState(null, "", `?${params}`);
  }
  function openDrawer() { setDrawer({ open: true, panel }); }
  function editRecord(target:ProfessionalTarget) {
    setIntent(previous=>({target,serial:previous.serial+1})); setDrawer({ open: true, panel });
    const params=new URLSearchParams(window.location.search);
    for(const key of ["build","request","run","issue","change","feedback","publication"] as const) { params.delete(key); if(target[key])params.set(key,target[key]!); }
    window.history.replaceState(null,"",`?${params}`);
  }
  return <ProfessionalTargetContext.Provider value={intent}><section className={styles.surface} aria-label={definition.title}>
    <header className={`${styles.heading} ${styles.headingRow}`}><div><h2>{definition.title}</h2><p>{definition.description}</p></div>{listed && <Button size="sm" variant="outline" aria-haspopup="dialog" onClick={openDrawer}>{panelLabel} · 专业办理<ArrowRight size={13}/></Button>}</header>
    {definition.panels.length > 1 && <nav className={styles.tabs} aria-label={`${definition.title}视图`}>{definition.panels.map(([id, label]) => <button type="button" key={id} aria-pressed={panel === id} onClick={() => choose(id)}>{label}</button>)}</nav>}
    {panel === "files" && <ProjectFiles api={api} categoryId={categoryId} productId={productId} productName={productName} manageHref={projectWorkspaceHref(categoryId, productId, projectId, "docs", "originals")}/>}
    {panel === "summary" && <ProjectBuildSummary {...scope} initialBuild={intent.target.build}/>}
    {recordPanels.has(panel) && <ProjectProfessionalRecords key={`${projectId}:${panel}`} api={scoped} productId={productId} projectId={projectId} panel={panel} readVersion={readVersion + savedVersion} initialBuild={intent.target.build} onEdit={editRecord}/>}
    {Summary && <Summary {...scope}/>}
    {(inlineVisited || inline) && <div className={styles.body} hidden={!inline}>
      <Workspace key={`inline:${principalId}:${categoryId}:${productId}:${projectId}`} categoryId={categoryId} projectId={projectId} fixedProductId={productId} onSaved={saved} embeddedPanel={inline ? panel : ""}/>
    </div>}
    {(drawerVisited || drawer.open) && <RetainedSheet open={drawer.open} title={`${drawerLabel} · 专业办理`} onClose={() => setDrawer(current => ({ ...current, open: false }))}>
      <p className={styles.drawerIntro}>按当前事实核对后办理；原有确认、具名决定和历史记录保留。关闭抽屉不会丢失未保存的填写。</p>
      <div id="project-professional-editor" className={styles.body}>
        <Workspace key={`drawer:${principalId}:${categoryId}:${productId}:${projectId}`} categoryId={categoryId} projectId={projectId} fixedProductId={productId} onSaved={saved} embeddedPanel={drawer.open ? drawer.panel : ""}/>
      </div>
    </RetainedSheet>}
  </section></ProfessionalTargetContext.Provider>;
}
