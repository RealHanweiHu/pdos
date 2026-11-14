"use client";

import { useEffect, useState } from "react";
import { browserApi } from "@/lib/browser-api";
import { isScopeNotesView, listPath, type NoteKind, type ScopeNotesView } from "@/lib/scope-notes";
import { Button } from "../../components/ui/button";
import { NoteForm } from "./scope-notes-section";
import styles from "./scope-notes.module.css";

type Api = typeof browserApi;
type Project = { id: string; label: string; category_id: string; product_id: string | null };
const message = (failure: unknown, fallback: string) => failure instanceof Error ? failure.message : fallback;

/** “分享到项目”“记为项目备忘”：本人选一个项目，核对受众后确认一次，生成一条新的团队备忘。
 * 个人记忆不会自动共享；这里只把文字带过去，原条目不变（P86 第 8 项、P87 第 3 项）。 */
export function ShareToProject({ api = browserApi, text, kind, sharedFrom, preselect, title, onDone, onCancel }: { api?: Api; text: string; kind: NoteKind; sharedFrom?: string; preselect?: string | null; title: string; onDone: (text: string) => void; onCancel: () => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [chosen, setChosen] = useState(preselect ?? "");
  const [view, setView] = useState<ScopeNotesView | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api<{ items: Project[] }>("v1/personal/preferences/options?kind=project").then(result => { if (live) setProjects(result.items); })
      .catch(failure => { if (live) setError(message(failure, "项目读取失败。")); });
    return () => { live = false; };
  }, [api]);
  const project = projects?.find(item => item.id === chosen) ?? null;
  useEffect(() => {
    if (!project) return;
    let live = true;
    api<ScopeNotesView>(listPath(project.category_id, "project", project.id)).then(result => { if (live) { if (isScopeNotesView(result)) { setView(result); setError(""); } else setError("这个项目的团队备忘暂不可读。"); } })
      .catch(failure => { if (live) setError(message(failure, "这个项目的团队备忘读取失败。")); });
    return () => { live = false; };
  }, [api, project]);
  const ready = project && view?.anchor.id === project.id ? view : null;
  return <div className={styles.share} role="group" aria-label={title}>
    <p className={styles.strong}>{title}</p>
    <p className={styles.hint}>会在所选项目下新建一条团队备忘，项目受众都能看到；你的个人记忆条目保持不变，仍只有你本人可见。</p>
    <label className={styles.reason}>项目<select value={chosen} disabled={!projects} onChange={event => { setChosen(event.target.value); setView(null); setError(""); }}><option value="">{projects ? "请选择项目" : "正在读取…"}</option>{projects?.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {ready && !ready.can_write && <p role="status" className={styles.hint}>你对这个项目所在品类只有读取权限，不能记团队备忘。</p>}
    {ready?.can_write && project ? <NoteForm key={project.id} api={api} scope={{ categoryId: project.category_id, productId: project.product_id, anchor: { kind: "project", id: project.id } }} view={ready} initial={{ statement: text, kind }} sharedFrom={sharedFrom} onDone={onDone} onCancel={onCancel}/>
      : <div className={styles.actions}><Button type="button" size="sm" variant="outline" onClick={onCancel}>取消</Button></div>}
  </div>;
}
