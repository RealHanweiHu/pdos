"use client";

import { useEffect, useState } from "react";
import { ArrowClockwise, ArrowUpRight, FloppyDisk, X } from "@phosphor-icons/react";
import { dateText, emptyView, filterOptions, filterRows, groupRows, healthTone, readProjectCockpit, readSavedViews, saveView, slipText, UNSET, writeSavedViews, type CockpitApi, type CockpitFocus, type CockpitRow, type CockpitView, type ProjectCockpit, type SavedView } from "@/lib/project-cockpit";
import s from "./project-manager-cockpit.module.css";

type Props = { api: CockpitApi; principalId: string; onOpenProject: (categoryId: string, projectId: string) => void };

function storage(): Storage | null { try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; } }

/** 管理者驾驶舱：按本人可见范围汇总，只下钻，不改期、不改分配（P75-3，B4）。 */
export function ProjectManagerCockpit({ api, principalId, onOpenProject }: Props) {
  const [reload, setReload] = useState(0);
  const key = JSON.stringify([principalId, reload]);
  const [reading, setReading] = useState<{ key: string; api: CockpitApi; data: ProjectCockpit | null; error: string } | null>(null);
  const [view, setView] = useState<CockpitView>(emptyView);
  const [saved, setSaved] = useState<{ owner: string; views: SavedView[] } | null>(null);
  const [naming, setNaming] = useState(""), [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    void readProjectCockpit(api).then(data => { if (active) setReading({ key, api, data, error: "" }); })
      .catch(failure => { if (active) setReading({ key, api, data: null, error: (failure as Error).message }); });
    return () => { active = false; };
  }, [api, key]);
  const views = saved?.owner === principalId ? saved.views : readSavedViews(storage(), principalId);
  const current = reading?.key === key && reading.api === api ? reading : null;
  if (!current) return <p role="status" className={s.muted}>正在读取驾驶舱…</p>;
  if (!current.data) return <div role="alert" className="workspace-read-error"><p>{current.error}</p><button type="button" className={s.chip} onClick={() => setReload(value => value + 1)}>重新读取</button></div>;
  const data = current.data;
  const options = filterOptions(data.items);
  const shown = filterRows(data.items, view);
  const groups = groupRows(shown, data.summary.health);
  const focus = (next: CockpitFocus) => setView(old => ({ ...old, focus: old.focus === next ? "" : next }));
  const persist = (next: SavedView[]) => { setSaved({ owner: principalId, views: next }); if (!writeSavedViews(storage(), principalId, next)) setNotice("本浏览器不能保存视图；筛选仍可用。"); };
  const filtered = view.set || view.category || view.owner || view.focus;

  return <section className={s.cockpit} aria-label="管理者驾驶舱">
    <p className={s.summary} aria-label="驾驶舱汇总">
      <span>在办 <b>{data.summary.active}</b></span>
      {data.summary.health.map(tier => <button type="button" key={tier.state} className={s.count} data-tone={healthTone(tier.state)} aria-pressed={view.focus === `health:${tier.state}`} onClick={() => focus(`health:${tier.state}`)}>{tier.label} <b>{tier.count}</b></button>)}
      <button type="button" className={s.count} aria-pressed={view.focus === "slipped"} onClick={() => focus("slipped")}>滑期节点 <b>{data.summary.slipped_nodes}</b></button>
      <button type="button" className={s.count} aria-pressed={view.focus === "my_decisions"} onClick={() => focus("my_decisions")}>待我决定的阶段评审 <b>{data.summary.my_stage_decisions}</b></button>
      {([["资源冲突", data.summary.resource_conflicts], ["状态更新缺失", data.summary.status_updates_missing], ["小Pai 例外", data.summary.agent_exceptions]] as const).map(([label, metric]) => <span key={label} className={s.unavailable} title={metric.reason}>{label} <b>未接入</b></span>)}
    </p>
    <div className={s.toolbar}>
      <label>项目集<select value={view.set} onChange={event => setView({ ...view, set: event.target.value })}><option value="">全部</option><option value={UNSET}>未归类</option>{options.sets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>品类<select value={view.category} onChange={event => setView({ ...view, category: event.target.value })}><option value="">全部</option>{options.categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>负责人<select value={view.owner} onChange={event => setView({ ...view, owner: event.target.value })}><option value="">全部</option>{options.owners.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {!!views.length && <label>已存视图<select value="" onChange={event => { const chosen = views.find(item => item.name === event.target.value); if (chosen) setView(chosen.view); }}><option value="">选择…</option>{views.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>}
      <form className={s.save} onSubmit={event => { event.preventDefault(); if (!naming.trim()) return; persist(saveView(views, naming, view)); setNaming(""); setNotice(`视图“${naming.trim().slice(0, 40)}”已保存在本浏览器。`); }}>
        <input aria-label="视图名称" placeholder="视图名称" maxLength={40} value={naming} onChange={event => setNaming(event.target.value)}/>
        <button type="submit" className={s.chip} disabled={!naming.trim()}><FloppyDisk size={13} aria-hidden="true"/>保存视图</button>
      </form>
      {filtered && <button type="button" className={s.chip} onClick={() => setView(emptyView)}><X size={13} aria-hidden="true"/>清除筛选</button>}
      <button type="button" className={s.chip} aria-label="刷新驾驶舱" onClick={() => setReload(value => value + 1)}><ArrowClockwise size={13} aria-hidden="true"/></button>
    </div>
    {notice && <p role="status" className={s.muted}>{notice}</p>}
    {data.unavailable_count > 0 && <p role="status" className={s.muted}>{data.unavailable_count} 个项目的关联资料当前不可读，未列入。</p>}
    {!groups.length && <p className={s.empty}>{data.items.length ? "没有符合筛选的项目。" : "暂无可见项目。"}</p>}
    {groups.map(group => <section key={group.state} className={s.group} aria-label={`${group.label}项目`}>
      <h2><span className={s.dot} data-tone={healthTone(group.state)} aria-hidden="true"/>{group.label}<small>{group.rows.length}</small></h2>
      <ul>{group.rows.map(row => <Row key={row.project.id} row={row} principalId={principalId} onOpenProject={onOpenProject}/>)}</ul>
    </section>)}
    <details className={s.rules}><summary>比较口径与计算规则</summary>
      <p>跨项目按当前阶段的出口条件比较（每项一个规则结果），不按任务、任务数或完成比例比较；框架出口成果待阶段节点建成后接入。驾驶舱只下钻，不提供改期或改分配。</p>
      <ul>{data.rules.map(rule => <li key={rule.id}><code>{rule.id}@{rule.version}</code> {rule.text}</li>)}</ul>
      <p>读取于 <time dateTime={data.as_of}>{new Date(data.as_of).toLocaleString()}</time></p>
    </details>
  </section>;
}

function Row({ row, principalId, onOpenProject }: { row: CockpitRow; principalId: string; onOpenProject: Props["onOpenProject"] }) {
  const times = row.next_node.times;
  const promised = times.commitments.filter(c => c.promised_at).map(c => dateText(c.promised_at)).join("、") || "未知";
  return <li className={s.row}>
    <div className={s.identity}>
      <button type="button" className={s.name} onClick={() => onOpenProject(row.project.category.id, row.project.id)}>{row.project.name}<ArrowUpRight size={12} aria-hidden="true"/></button>
      <small>{row.project.category.name} · {row.project.owner.id === principalId ? "本人负责" : row.project.owner.name ?? "负责人姓名暂不可读"}{row.project.set ? ` · ${row.project.set.name ?? "项目集"}` : ""}</small>
      {row.latest_update?.first_sentence ? <p className={s.update}>{row.latest_update.first_sentence}<small> — {row.latest_update.actor.name ?? "署名暂不可读"} · {dateText(row.latest_update.created_at)}</small></p> : <p className={s.muted}>尚无具名状态更新</p>}
    </div>
    <div className={s.stage}>
      <span className={s.label}>阶段</span>
      {row.stage.adopted ? <><span className={s.mini} aria-label={`当前阶段：${row.stage.current ?? "已完成"}`}>{row.stage.stages.map(stage => <i key={stage.name} title={stage.name} data-state={stage.status}/>)}</span><span>{row.stage.current ?? (row.stage.completed ? "阶段已完成" : "—")}</span></> : <span className={s.muted}>未采用阶段模板</span>}
      <span className={s.health} title={`${row.health.reason}（${row.health.rule?.id ?? "规则"}）`}><span className={s.dot} data-tone={healthTone(row.health.state)} aria-hidden="true"/>{row.health.label}</span>
    </div>
    <div className={s.node}>
      <span className={s.label}>{row.next_node.name ?? "下一节点未知"}</span>
      <span className={s.times}>基线 {dateText(times.baseline)} · 预测 {dateText(times.forecast)} · 承诺 {promised} · 实际 {dateText(times.actual)}</span>
      <span className={s.slip} data-state={row.next_node.slip.state}>{slipText(row.next_node.slip)}</span>
    </div>
    <div className={s.exit}>
      <span className={s.label}>出口条件</span>
      {row.exit_conditions.length ? <span className={s.conditions}>{row.exit_conditions.map(c => <span key={c.key} data-state={c.state} title={c.label}>{c.label} · {c.state_label}</span>)}</span> : <span className={s.muted}>无出口条件</span>}
      <span className={s.muted}>出口成果：{row.exit_outcomes.label}</span>
    </div>
    <div className={s.tail}>
      <span>风险 <b>{row.risk_count}</b></span>
      {row.my_decision && <span className={s.decide}>待我决定</span>}
      {!row.my_decision && row.review_pending && <span className={s.muted}>评审待负责人决定</span>}
    </div>
  </li>;
}
