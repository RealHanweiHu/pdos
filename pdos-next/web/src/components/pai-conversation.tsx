import type { ReactNode } from "react";
import { Check, Crosshair, List, Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { usedSkillName } from "@/lib/run-process";
import styles from "./pai-conversation.module.css";

export type LoadedSkill = { key: string; version?: string };

/** Skill chips describe persisted load events, never a client-side capability grant. */
export function loadedSkillFacts(events: { event: { type: string; key?: string; version?: string } }[]): LoadedSkill[] {
  return [...new Map(events.flatMap(({ event }) => event.type === "skill_loaded" && event.key
    ? [[`${event.key}:${event.version ?? ""}`, { key: event.key, version: event.version }] as const] : [])).values()];
}

export function PaiScope({ scope, skills, hasRun, historyOpen, onHistoryToggle }: {
  scope: string; skills: LoadedSkill[]; hasRun: boolean; historyOpen?: boolean; onHistoryToggle?: () => void;
}) {
  return <div className={styles.scopeBar}>
    <span className={styles.scope}><Crosshair size={13} aria-hidden="true" />范围：{scope}</span>
    <span className={styles.skillLabel} title="未加载的技能不授予写工具；范围与可用动作由服务器核对。">已加载技能</span>
    {skills.map(skill => <span key={`${skill.key}:${skill.version ?? ""}`} className={styles.skillChip}><Check size={11} aria-hidden="true" />{usedSkillName(skill.key)}{skill.version ? ` · ${skill.version}` : ""}</span>)}
    {!skills.length && <span className={styles.scopeNote}>{hasRun ? "尚无可核对的加载记录" : "开始后按实际加载记录显示"}</span>}
    {onHistoryToggle && <Button size="sm" variant="ghost" className={styles.historyToggle} aria-expanded={!!historyOpen} onClick={onHistoryToggle}><List size={13} aria-hidden="true" />{historyOpen ? "返回对话" : "工作记录"}</Button>}
  </div>;
}

export function PaiMessage({ from, children }: { from: "user" | "pai"; children: ReactNode }) {
  return <article className={`${styles.message}${from === "user" ? ` ${styles.user}` : ""}`} aria-label={from === "user" ? "你委派的目标" : "小Pai 的实际结果"}>
    <p className={styles.who}>{from === "user" ? "你" : <span className={styles.agentTag}><Sparkle size={13} aria-hidden="true" />小Pai</span>}</p>
    <div className={from === "user" ? styles.bubble : styles.messageBody}>{children}</div>
  </article>;
}

export function PaiCarry({ scope, objects }: { scope: string; objects: string[] }) {
  return <details className={styles.carry} aria-label="本次发送携带什么">
    <summary>携带：{scope}{objects.length ? ` + ${objects.length} 个对象` : ""}</summary>
    <div><p>本次发送携带什么</p><p>范围：{scope}</p>
      <p>对象：{objects.length ? objects.join("；") : "未附加对象或原件"}</p>
      <p>技能：发送后由服务器按本次目标加载，以运行中的实际记录为准。</p>
    </div>
  </details>;
}

export function PaiPolicy() {
  return <details className={styles.policy}><summary>办理方式：自动 / 一次确认 / 具名决定</summary>
    <p>自动须具备当前资格和授权；一次确认先核对候选再保存；具名决定由有权人员在正式入口办理。</p>
  </details>;
}
