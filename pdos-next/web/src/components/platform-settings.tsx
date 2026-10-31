"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { ConnectedModelSettings } from "./model_configuration/connected-settings";
import { ConnectedEmbeddingSettings } from "./model_configuration/embedding-settings";
import { ConnectedAgentSkills } from "./model_configuration/agent-skills";
import { ConnectedAgentBudgets } from "./model_configuration/agent-budgets";
import { ConnectedMcpManagement } from "./model_configuration/mcp-management";
import { ConnectedProviderAgreements } from "./model_configuration/provider-agreements";
import { ConnectedAutomationRules } from "./automation-rules";
import { DingTalkSettings } from "./dingtalk-settings";
import { PersonalPreferences } from "./personal-preferences";
import { Button } from "./ui/button";
import styles from "./platform-settings.module.css";

const tabs = [["preferences", "个人偏好"], ["members", "成员与范围"], ["pai", "小Pai与模型"], ["integrations", "集成与治理"]] as const;
function Retained({ active, children }: { active: boolean; children: ReactNode }) {
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  return active || visited ? <div hidden={!active} className={styles.retained}>{children}</div> : null;
}
function Members({ categoryId }: { categoryId: string }) {
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ items: { id: string; name: string }[]; error: string } | null>(null);
  useEffect(() => {
    let active = true;
    browserApi<{ items: { id: string; name: string }[] }>(`v1/categories/${categoryId}/participants`).then(value => { if (active) setReading({ items: value.items, error: "" }); }).catch(error => { if (active) setReading({ items: [], error: error.message }); });
    return () => { active = false; };
  }, [categoryId, attempt]);
  if (!reading) return <p role="status">正在读取当前品类成员…</p>;
  if (reading.error) return <div role="alert"><p>{reading.error}</p><Button size="sm" variant="outline" onClick={() => setAttempt(n => n + 1)}>重新读取成员</Button></div>;
  return <><table className={styles.table}><thead><tr><th>成员</th><th>范围</th></tr></thead><tbody>{reading.items.map(item => <tr key={item.id}><td>{item.name}</td><td>当前品类可见成员</td></tr>)}</tbody></table>{!reading.items.length && <p className={styles.note}>当前没有可展示的成员。</p>}<p className={styles.note}>具体工作由当前责任与授权决定。</p></>;
}

function ScopedSettings({ categoryId, principalId, tab, onOpenRun }: { categoryId: string; principalId: string; tab: string; onOpenRun: (runId: string, categoryId: string) => void }) {
  const api = useMemo(() => categoryTransport(categoryId, browserApi), [categoryId]);
  const [modelView, setModelView] = useState("model"), [integration, setIntegration] = useState("connections");
  const modelTabs = [["model", "模型配置"], ["skills", "技能与资格"], ["budgets", "预算与用量"], ["rules", "自动化规则"]];
  const integrationTabs = [["connections", "外部连接"], ["agreements", "服务商协议"]];
  return <>
    <Retained active={tab === "members"}><Members categoryId={categoryId}/></Retained>
    <Retained active={tab === "pai"}>
      <nav className={styles.subnav} aria-label="小Pai设置">{modelTabs.map(([id, label]) => <button type="button" key={id} aria-pressed={modelView === id} onClick={() => setModelView(id)}>{label}</button>)}</nav>
      <Retained active={tab === "pai" && modelView === "model"}><div className="space-y-4"><ConnectedModelSettings api={api}/><ConnectedEmbeddingSettings api={api} categoryId={categoryId} principalId={principalId}/></div></Retained>
      <Retained active={tab === "pai" && modelView === "skills"}><ConnectedAgentSkills api={api} principalId={principalId} categoryId={categoryId}/></Retained>
      <Retained active={tab === "pai" && modelView === "budgets"}><ConnectedAgentBudgets api={api} principalId={principalId} categoryId={categoryId}/></Retained>
      <Retained active={tab === "pai" && modelView === "rules"}><ConnectedAutomationRules api={browserApi} principalId={principalId} categoryId={categoryId} onOpenRun={onOpenRun}/></Retained>
    </Retained>
    <Retained active={tab === "integrations"}>
      <nav className={styles.subnav} aria-label="集成与治理设置">{integrationTabs.map(([id, label]) => <button type="button" key={id} aria-pressed={integration === id} onClick={() => setIntegration(id)}>{label}</button>)}</nav>
      <Retained active={tab === "integrations" && integration === "connections"}><ConnectedMcpManagement api={api} principalId={principalId} categoryId={categoryId}/></Retained>
      <Retained active={tab === "integrations" && integration === "agreements"}><ConnectedProviderAgreements api={api} principalId={principalId} categoryId={categoryId}/></Retained>
    </Retained>
  </>;
}

export function PlatformSettings({ categories, initialCategoryId, principalId, preferences, onOpenRun }: {
  categories: { id: string; name: string }[]; initialCategoryId: string; principalId: string; preferences: ReactNode; onOpenRun: (runId: string, categoryId: string) => void;
}) {
  const [tab, setTab] = useState<string>("preferences");
  const [selected, setSelected] = useState(initialCategoryId);
  const categoryId = categories.find(item => item.id === selected)?.id ?? categories[0]?.id ?? "";
  return <section className={styles.page} aria-label="设置">
    <div className="workspace-page-heading"><div><h1>设置</h1><p>低频配置集中管理，日常工作保持简洁。</p></div></div>
    <nav className={styles.tabs} aria-label="设置视图">{tabs.map(([id, label]) => <button type="button" key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}</nav>
    <div hidden={tab !== "preferences"} className={styles.retained}>{preferences}<PersonalPreferences key={principalId}/><DingTalkSettings key={`dingtalk:${principalId}`} principalId={principalId}/></div>
    {tab !== "preferences" && <div className={styles.scope}><label>品类范围<select value={categoryId} onChange={event => setSelected(event.target.value)}>{!categoryId && <option value="">暂无可用范围</option>}{categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>}
    {categoryId ? <ScopedSettings key={`${principalId}:${categoryId}`} principalId={principalId} categoryId={categoryId} tab={tab} onOpenRun={onOpenRun}/> : tab !== "preferences" && <p className={styles.note}>当前没有可用的品类范围。</p>}
  </section>;
}
