"use client";

import { useState, type ReactNode } from "react";
import { ArrowUpRight, Plus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import s from "./project-directory-view.module.css";

export type ProjectDirectoryDate = { label: string; position?: number; description?: string };
export type ProjectDirectoryEntry = {
  id: string; name: string; code?: string; phase: string | null; health: string | null;
  lead: string; next: string | null; gateDates: string; note: string;
  stages?: string[]; at?: number;
  dates: Record<"基线" | "预测" | "承诺" | "实际", ProjectDirectoryDate>;
};

type Props = {
  entries: ProjectDirectoryEntry[]; phaseOrder?: string[]; timeScale: string[];
  onOpenProject: (id: string) => void; onOpenPlan: (id: string) => void;
  onStartProposal?: () => void; children?: ReactNode;
};

/** The approved ui-lab project surface and the live directory share this presentation. */
export function ProjectDirectoryView({ entries, phaseOrder = [], timeScale, onOpenProject, onOpenPlan, onStartProposal, children }: Props) {
  const [view, setView] = useState("列表");
  const phases = [...new Set([...phaseOrder, ...entries.map(p => p.phase ?? "阶段未提供")])];
  return <div className={s.page}>
    <header className={s.heading}>
      <div><h1>项目</h1><p>查看阶段、负责人和下一门禁。</p></div>
      {onStartProposal && <Button variant="outline" onClick={onStartProposal}><Plus aria-hidden="true"/>从提案开始</Button>}
    </header>
    <div className={s.tabs} role="group" aria-label="项目视图">
      {["列表", "看板", "时间轴"].map(name => <button type="button" key={name} aria-pressed={view === name} onClick={() => setView(name)}>{name}</button>)}
    </div>
    {children}
    {entries.length > 0 && (view === "列表" ? <div className={s.tableWrap}>
      <table><thead><tr>{["项目", "阶段", "健康度", "负责人", "下一门禁", "承诺 / 预测"].map(h => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{entries.map(p => <tr key={p.id}>
          <td><button type="button" onClick={() => onOpenProject(p.id)}>{p.name}<ArrowUpRight size={12} aria-hidden="true"/></button></td>
          <td>{p.phase ?? "未提供"}</td><td>{p.health ?? "未知"}</td><td>{p.lead}</td><td>{p.next ?? "未提供"}</td><td>{p.gateDates}</td>
        </tr>)}</tbody>
      </table>
    </div> : view === "看板" ? <div className={s.board}>
      {phases.map(phase => <section key={phase} aria-label={`${phase}看板`}>
        <h2 className={s.sectionTitle}>{phase}</h2>
        {entries.filter(p => (p.phase ?? "阶段未提供") === phase).map(p => <button type="button" key={p.id} onClick={() => onOpenProject(p.id)}>
          {p.code && <span>{p.code}</span>}<h2>{p.name}</h2><p>{p.note}</p>
          <div><span className={s.status} data-tone={!p.health ? undefined : p.health === "正常" ? "success" : "warning"}><span/>{p.health ?? "未知"}</span><small>{p.lead}</small></div>
          {!!p.stages?.length && p.at !== undefined && <span className={s.miniStages} aria-label={`当前阶段：${p.phase}`}>
            {p.stages.map((stage, index) => <i key={stage} title={stage} data-state={index < p.at! ? "done" : index === p.at ? "current" : "future"}/>)}
          </span>}
        </button>)}
      </section>)}
    </div> : <div className={s.timeline}>
      {entries.map(p => <section key={p.id} aria-label={`${p.name}四时间`}>
        <div className={s.sectionTitle}><h2>{p.name}</h2><button type="button" className={s.textLink} onClick={() => onOpenPlan(p.id)}>查看计划<ArrowUpRight size={13} aria-hidden="true"/></button></div>
        <div className={s.timeScale}>{timeScale.map((date, index) => <span key={index}>{date}</span>)}</div>
        {(["基线", "预测", "承诺", "实际"] as const).map(name => { const date = p.dates[name]; return <div className={s.timeRow} key={name}>
          <span>{name}</span><div>{date.position === undefined ? <em title={date.description}>{date.label}</em> : <span className={s.timeMark} data-kind={name} title={date.description} style={{ left: `${date.position}%` }}>{date.label}</span>}</div>
        </div>; })}
      </section>)}
    </div>)}
    <p className={s.footnote}>阶段表示所在位置。看板用于查看；推进阶段需进入门禁评审。</p>
  </div>;
}
