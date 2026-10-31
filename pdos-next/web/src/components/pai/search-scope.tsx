"use client";

import type { ReactNode } from "react";
import type { SearchPreferences } from "@/lib/search-preferences";
import styles from "./search-scope.module.css";

/** Explicit human selection controls future retrieval; it never starts a Run. */
export function SearchScope({ label, kind = "project", value, onChange, disabled, control, persisted = false }: {
  label: string; kind?: string; value: SearchPreferences; onChange: (value: SearchPreferences) => void;
  disabled?: boolean; control?: ReactNode; persisted?: boolean;
}) {
  const object = kind === "proposal" ? "提案" : "项目";
  return <div className={styles.bar} aria-label="查找背景">
    <div className={styles.object} title={label}><span>当前对象：{label}</span>{control}</div>
    <details className={styles.picker}>
      <summary>查找范围：当前{object}{value.scope === "same_category" ? "＋同品类补查" : ""}</summary>
      <div className={styles.panel}>
        <label>查找范围<select value={value.scope} disabled={disabled} onChange={event => onChange({ ...value, scope: event.target.value as SearchPreferences["scope"] })}>
          <option value="same_category">当前{object}＋同品类补查</option><option value="current">只查当前{object}</option>
        </select></label>
        <p>当前{object}不足 3 条有效候选时，按本人权限补查同品类一次。</p>
        <label className={styles.check}><input type="checkbox" checked={value.include_customer_private} disabled={disabled || value.scope !== "same_category"} onChange={event => onChange({ ...value, include_customer_private: event.target.checked })}/>包含其他客户项目资料</label>
        <p>{persisted ? "选择保存在本次携带中，对后续消息生效。" : "随你发送的消息保存；不会自动检索或开始处理。"} 当前运行和原引用保持原选择。</p>
      </div>
    </details>
  </div>;
}
