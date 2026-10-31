"use client";

import { useRef, useState } from "react";
import { Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { skillTitle, type AgentSkill } from "@/lib/agent-skills";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { RequestedSkill } from "@/lib/run-start-intent";
import styles from "./skill-picker.module.css";

type SkillChoice = Pick<AgentSkill, "skill_key" | "purpose" | "skill_version" | "skill_digest" | "enabled" | "available">;

export function SkillPicker({ api, value, onChange, disabled, resource = "v1/agent-skills" }: {
  api: WorkspaceTransport; value: RequestedSkill[]; onChange: (value: RequestedSkill[]) => void; disabled: boolean;
  resource?: "v1/agent-skills" | "v1/personal/agent-skills";
}) {
  const [items, setItems] = useState<SkillChoice[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  async function refresh() {
    const own = ++generation.current;
    setBusy(true); setItems(null); setError(""); onChange([]);
    try {
      const reading = await api<{ items: SkillChoice[] }>(resource);
      if (own !== generation.current) return;
      if (!Array.isArray(reading.items) || reading.items.some(item => typeof item.skill_key !== "string"
        || typeof item.purpose !== "string" || typeof item.enabled !== "boolean" || typeof item.available !== "boolean"
        || item.available && (typeof item.skill_version !== "string" || typeof item.skill_digest !== "string" || !/^[a-f0-9]{64}$/.test(item.skill_digest)))) throw new Error("技能列表无法核对，请重新读取。");
      setItems(reading.items);
    } catch (failure) { if (own === generation.current) setError(failure instanceof Error ? failure.message : "技能列表暂不可读。"); }
    finally { if (own === generation.current) setBusy(false); }
  }
  return <details className={styles.picker} onToggle={event => { if (event.currentTarget.open && items === null && !busy && !error) void refresh(); }}>
    <summary><Sparkle size={13} aria-hidden="true"/>{value.length ? `技能 · ${value.length}` : "自动选择技能"}</summary>
    <div className={styles.panel}>
      <p className={styles.title}>本次优先使用的技能</p>
      <p className={styles.note}>留空由小Pai按目标选择。已选技能在开始时加载，实际加载记录可在会话信息中查看。</p>
      {busy && <p role="status">正在读取技能…</p>}
      {error && <p role="alert">{error}</p>}
      {items?.length === 0 && <p>当前没有已登记的技能。</p>}
      <div className={styles.list}>{items?.map(item => <label key={item.skill_key}>
        <input type="checkbox" checked={value.some(selected => selected.key === item.skill_key)}
          disabled={disabled || busy || !item.enabled || !item.available || value.length >= 8 && !value.some(selected => selected.key === item.skill_key)}
          onChange={event => onChange(event.target.checked
            ? [...value, { key: item.skill_key, version: item.skill_version!, digest: item.skill_digest! }]
            : value.filter(selected => selected.key !== item.skill_key))}/>
        <span><strong>{skillTitle(item.skill_key)}</strong><small>{item.purpose}</small><small>{!item.available ? "当前配置不可用" : !item.enabled ? "租户尚未启用" : `已启用 · ${item.skill_version}`}</small></span>
      </label>)}</div>
      <div className={styles.actions}><Button type="button" size="sm" variant="ghost" disabled={disabled || busy} onClick={() => onChange([])}>清除选择</Button><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void refresh()}>刷新技能</Button></div>
    </div>
  </details>;
}
