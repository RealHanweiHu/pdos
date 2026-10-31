"use client";

import { useEffect, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { readProjectBuilds, type ProjectBuildApi, type ProjectBuildList, type ProjectBuildScope } from "@/lib/project-build-summary";
import { projectWorkspaceHref } from "@/lib/project-workspace-navigation";
import styles from "./project-views.module.css";

export function ProjectOverviewBuilds({ api, scope }: { api: ProjectBuildApi; scope: ProjectBuildScope }) {
  const { categoryId, productId, projectId } = scope;
  const [reading, setReading] = useState<ProjectBuildList | null>(null);
  const [error, setError] = useState(""), [attempt, setAttempt] = useState(0), [selected, setSelected] = useState("");
  useEffect(() => {
    let active = true;
    void readProjectBuilds(api, { categoryId, productId, projectId }).then(data => {
      if (active) { setReading(data); setError(""); }
    }).catch(failure => { if (active) { setReading(null); setError((failure as Error).message); } });
    return () => { active = false; };
  }, [api, categoryId, productId, projectId, attempt]);
  const build = reading?.items.find(item => item.id === selected);
  const href = (panel: string) => `${projectWorkspaceHref(categoryId, productId, projectId, "builds", panel)}${build ? `&build=${build.id}` : ""}`;
  return <div className={styles.sectionBox}>
    {error ? <p role="alert">{error} <button type="button" className={styles.outlineLink} onClick={() => setAttempt(value => value + 1)}>重新读取</button></p> : !reading ? <p role="status" className={styles.unknown}>正在读取本项目轮次…</p> : <>
      <label className={styles.overviewBuildSelect}>试制轮次<select value={selected} onChange={event => setSelected(event.target.value)}><option value="">{reading.items.length ? "选择需要查看的轮次" : "尚无可读轮次"}</option>{reading.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {(reading.hasMore || reading.unavailableCount > 0) && <p className={styles.noteInline}>轮次读取尚不完整，请进入专业页核对。</p>}
      {build ? <dl className={styles.buildFacts}><dt>轮次用途</dt><dd>{build.purpose}</dd><dt>工程配置</dt><dd>{build.engineering_configuration.name} · v{build.engineering_configuration.revision}</dd><dt>制造配置</dt><dd>{build.manufacturing_configuration.name} · v{build.manufacturing_configuration.revision}</dd><dt>计划数量</dt><dd>{build.planned_quantity} {build.unit}</dd><dt>验证目标</dt><dd>{build.verification_objectives || "尚未登记"}</dd></dl> : <p className={styles.noteInline}>按已保存轮次查看固定配置、计划数量与验证目标。</p>}
      {build && <p className={styles.noteInline}>{build.source_status === "current" ? "固定依据当前可读" : "固定依据需重核"}。计划数量与实际产出分别记录。</p>}
    </>}
    <div className={styles.rowActions}><a className={styles.outlineLink} href={href("summary")}>查看本项目 Builds<ArrowRight size={13}/></a>{build && <a className={styles.outlineLink} href={href("handoff")}>交样与接收</a>}</div>
  </div>;
}
