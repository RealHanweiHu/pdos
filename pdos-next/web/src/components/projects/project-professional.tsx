"use client";

import { useCallback, useMemo, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { Workspace } from "@/components/workspace";
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
  const [editors, setEditors] = useState<Record<string, boolean>>({ ...(initialPanel && Object.keys(intent.target).length ? {[initialPanel]:true} : {}) });
  const [savedVersion, setSavedVersion] = useState(0);
  const saved = useCallback(() => { setSavedVersion(value => value + 1); onSaved?.(); }, [onSaved]);
  const [visited, setVisited] = useState(false);
  const definition = professionalViews[view];
  const panel = definition.panels.find(([id]) => id === selected[view])?.[0] ?? definition.panels[0][0];
  const Summary = summaries[panel as keyof typeof summaries];
  const editing = panel !== "summary" && panel !== "files" && (!(Summary || recordPanels.has(panel)) || editors[panel]);
  if (editing && !visited) setVisited(true);
  const scope = { categoryId, productId, projectId, principalId, api, readVersion: readVersion + savedVersion };
  function choose(value: string) {
    setSelected(current => ({ ...current, [view]: value }));
    const params = new URLSearchParams(window.location.search);
    params.set("projectView", view); params.set("panel", value);
    window.history.replaceState(null, "", `?${params}`);
  }
  function editRecord(target:ProfessionalTarget) {
    setIntent(previous=>({target,serial:previous.serial+1})); setEditors(current=>({...current,[panel]:true}));
    const params=new URLSearchParams(window.location.search);
    for(const key of ["build","request","run","issue","change","feedback","publication"] as const) { params.delete(key); if(target[key])params.set(key,target[key]!); }
    window.history.replaceState(null,"",`?${params}`);
    requestAnimationFrame(()=>document.getElementById("project-professional-editor")?.scrollIntoView({block:"start"}));
  }
  return <ProfessionalTargetContext.Provider value={intent}><section className={styles.surface} aria-label={definition.title}>
    <header className={styles.heading}><h2>{definition.title}</h2><p>{definition.description}</p></header>
    {definition.panels.length > 1 && <nav className={styles.tabs} aria-label={`${definition.title}视图`}>{definition.panels.map(([id, label]) => <button type="button" key={id} aria-pressed={panel === id} onClick={() => choose(id)}>{label}</button>)}</nav>}
    {panel === "files" && <ProjectFiles api={api} categoryId={categoryId} productId={productId} productName={productName} manageHref={projectWorkspaceHref(categoryId, productId, projectId, "docs", "originals")}/>}
    {panel === "summary" && <ProjectBuildSummary {...scope} initialBuild={intent.target.build}/>}
    {recordPanels.has(panel) && <ProjectProfessionalRecords key={`${projectId}:${panel}`} api={scoped} productId={productId} projectId={projectId} panel={panel} readVersion={readVersion + savedVersion} initialBuild={intent.target.build} onEdit={editRecord}/>}
    {Summary && <Summary {...scope}/>}
    {(Summary || recordPanels.has(panel)) && <><button type="button" className={styles.editorToggle} aria-expanded={!!editing} aria-controls="project-professional-editor" onClick={() => setEditors(current => ({ ...current, [panel]: !editing }))}>维护记录与专业办理<CaretDown size={14}/></button></>}
    {(editing || visited) && <div id="project-professional-editor" hidden={!editing} className={styles.body}>
      <Workspace key={`${principalId}:${categoryId}:${productId}:${projectId}`} categoryId={categoryId} projectId={projectId} fixedProductId={productId} onSaved={saved} embeddedPanel={editing ? panel : ""}/>
    </div>}
  </section></ProfessionalTargetContext.Provider>;
}
