"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { ConnectedModelSettings } from "./model-configuration/connected-settings";
import { ConnectedEmbeddingSettings } from "./model-configuration/embedding-settings";
import { ConnectedAgentSkills } from "./model-configuration/agent-skills";
import { useQualityHolds } from "./model-configuration/skill-quality";
import { ConnectedAgentBudgets } from "./model-configuration/agent-budgets";
import { ConnectedMcpManagement } from "./model-configuration/mcp-management";
import { ConnectedProviderAgreements } from "./model-configuration/provider-agreements";
import { ConnectedAutomationRules } from "./automation-rules";
import { DingTalkSettings } from "./dingtalk-settings";
import { PersonalPreferences } from "./personal-preferences";
import { PersonalMemory } from "./personal-memory";
import { MemoryPolicySettings } from "./memory-policy-settings";
import { SkillRevisions } from "./skill-revisions";
import { AccountManagement } from "./accounts";
import { WorkCalendarSettings } from "./work-calendar";
import { RoleCatalogSettings } from "./role-catalog";
import { Button } from "@/components/ui/button";
import { readPortfolio } from "@/lib/portfolio-reads";
import { memberRows, readTeams, responsibilityText, type MemberRow, type Participant, type ProjectRef } from "./lib/member-responsibilities";
import styles from "./platform-settings.module.css";

const tabs = [["preferences", "个人偏好"], ["members", "成员与范围"], ["pai", "小Pai与模型"], ["integrations", "集成与治理"]] as const;
// Tenant-wide pages: no category scope selector (D214 accounts, D221 working calendar).
const tenantTabs = new Set(["preferences", "accounts", "calendar", "roles"]);
function Retained({ active, children }: { active: boolean; children: ReactNode }) {
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  return active || visited ? <div hidden={!active} className={styles.retained}>{children}</div> : null;
}
function Members({ categoryId }: { categoryId: string }) {
  const [attempt, setAttempt] = useState(0);
  const [reading, setReading] = useState<{ rows: MemberRow[]; projects: number; unavailable: number; error: string } | null>(null);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        // Grant holders are the category scope; responsibilities come from the
        // project teams (D33) of the projects this person can currently read.
        const [participants, portfolio] = await Promise.all([
          browserApi<{ items: Participant[] }>(`v1/categories/${categoryId}/participants`),
          readPortfolio(browserApi).catch(() => null),
        ]);
        const projects: ProjectRef[] = (portfolio?.projects ?? []).filter(entry => entry.category.id === categoryId)
          .map(entry => ({ id: entry.project.id, name: entry.project.name, categoryId, productId: entry.product.id }));
        const { teams, unavailable } = await readTeams(browserApi, projects);
        if (active) setReading({ rows: memberRows(participants.items, teams), projects: projects.length, unavailable: unavailable + (portfolio ? portfolio.readErrors.length : 1), error: "" });
      } catch (error) {
        if (active) setReading({ rows: [], projects: 0, unavailable: 0, error: error instanceof Error ? error.message : "成员暂不可读。" });
      }
    })();
    return () => { active = false; };
  }, [categoryId, attempt]);
  if (!reading) return <p role="status">正在读取当前品类成员与项目责任…</p>;
  if (reading.error) return <div role="alert"><p>{reading.error}</p><Button size="sm" variant="outline" onClick={() => setAttempt(n => n + 1)}>重新读取成员</Button></div>;
  return <>
    <div className={styles.tableScroll}><table className={styles.table}><thead><tr><th>成员</th><th>责任</th><th>范围</th></tr></thead><tbody>{reading.rows.map(row => <tr key={row.id}>
      <td>{row.name}</td>
      <td>{row.assignments.length ? <ul className={styles.assignments}>{row.assignments.map(assignment => <li key={assignment.projectId}>{responsibilityText(assignment)}<small>{assignment.projectName}</small></li>)}</ul> : <span className={styles.muted}>暂无项目责任</span>}</td>
      <td>{row.categoryMember ? "当前品类" : "仅项目成员 · 需要品类授权"}{row.assignments.length > 0 && <small className={styles.cellNote}>参与 {row.assignments.length} 个项目</small>}</td>
    </tr>)}</tbody></table></div>
    {!reading.rows.length && <p className={styles.note}>当前没有可展示的成员。</p>}
    {reading.unavailable > 0 && <p className={styles.note} role="status">有 {reading.unavailable} 处项目团队暂不可读，以上责任可能不完整。<Button size="xs" variant="ghost" onClick={() => setAttempt(n => n + 1)}>重新读取</Button></p>}
    <p className={styles.note}>责任来自你当前可读的 {reading.projects} 个项目的团队与角色目录；角色名称不授予权限，具体办理按当前授权。成员与角色在项目“更多 → 团队”中调整。</p>
  </>;
}

function ScopedSettings({ categoryId, principalId, tab, onOpenRun, administrator }: { categoryId: string; principalId: string; tab: string; onOpenRun: (runId: string, categoryId: string) => void; administrator: boolean }) {
  const api = useMemo(() => categoryTransport(categoryId, browserApi), [categoryId]);
  const [modelView, setModelView] = useState("model"), [integration, setIntegration] = useState("connections");
  // Open quality holds pinned for administrators (P110 Q4).
  const holds = useQualityHolds(api, administrator);
  const modelTabs = [["model", "模型配置"], ["skills", holds?.length ? `技能与资格 · ${holds.length} 待复审` : "技能与资格"], ["budgets", "预算与用量"], ["rules", "自动化规则"], ...(administrator ? [["memory", "记忆策略"]] : [])];
  const integrationTabs = [["connections", "外部连接"], ["agreements", "服务商协议"]];
  return <>
    <Retained active={tab === "members"}><Members categoryId={categoryId}/></Retained>
    <Retained active={tab === "pai"}>
      <nav className={styles.subnav} aria-label="小Pai设置">{modelTabs.map(([id, label]) => <button type="button" key={id} aria-pressed={modelView === id} onClick={() => setModelView(id)}>{label}</button>)}</nav>
      <Retained active={tab === "pai" && modelView === "model"}><div className="space-y-4"><ConnectedModelSettings api={api}/><ConnectedEmbeddingSettings api={api} categoryId={categoryId} principalId={principalId}/></div></Retained>
      <Retained active={tab === "pai" && modelView === "skills"}><ConnectedAgentSkills api={api} principalId={principalId} categoryId={categoryId}/></Retained>
      <Retained active={tab === "pai" && modelView === "budgets"}><ConnectedAgentBudgets api={api} principalId={principalId} categoryId={categoryId}/></Retained>
      <Retained active={tab === "pai" && modelView === "rules"}><ConnectedAutomationRules api={browserApi} principalId={principalId} categoryId={categoryId} onOpenRun={onOpenRun}/></Retained>
      {administrator && <Retained active={tab === "pai" && modelView === "memory"}><div className="space-y-4"><MemoryPolicySettings key={`memory-policy:${principalId}`}/><SkillRevisions key={`skill-revisions:${principalId}`}/></div></Retained>}
    </Retained>
    <Retained active={tab === "integrations"}>
      <nav className={styles.subnav} aria-label="集成与治理设置">{integrationTabs.map(([id, label]) => <button type="button" key={id} aria-pressed={integration === id} onClick={() => setIntegration(id)}>{label}</button>)}</nav>
      <Retained active={tab === "integrations" && integration === "connections"}><ConnectedMcpManagement api={api} principalId={principalId} categoryId={categoryId}/></Retained>
      <Retained active={tab === "integrations" && integration === "agreements"}><ConnectedProviderAgreements api={api} principalId={principalId} categoryId={categoryId}/></Retained>
    </Retained>
  </>;
}

export function PlatformSettings({ categories, initialCategoryId, principalId, preferences, onOpenRun, administrator = false }: {
  categories: { id: string; name: string }[]; initialCategoryId: string; principalId: string; preferences: ReactNode; onOpenRun: (runId: string, categoryId: string) => void; administrator?: boolean;
}) {
  const [tab, setTab] = useState<string>("preferences");
  const [selected, setSelected] = useState(initialCategoryId);
  const categoryId = categories.find(item => item.id === selected)?.id ?? categories[0]?.id ?? "";
  return <section className={styles.page} aria-label="设置">
    <div className="workspace-page-heading"><div><h1>设置</h1><p>低频配置集中管理，日常工作保持简洁。</p></div></div>
    <nav className={styles.tabs} aria-label="设置视图">{[tabs[0], ...(administrator ? [["accounts", "账户与邀请"] as const] : []), ["calendar", "工作日历"] as const, ["roles", "项目角色"] as const, ...tabs.slice(1)].map(([id, label]) => <button type="button" key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}</nav>
    <div hidden={tab !== "preferences"} className={styles.retained}>{preferences}<PersonalPreferences key={principalId}/><PersonalMemory key={`memory:${principalId}`}/><DingTalkSettings key={`dingtalk:${principalId}`} principalId={principalId}/></div>
    {administrator && <Retained active={tab === "accounts"}><AccountManagement key={`accounts:${principalId}`}/></Retained>}
    <Retained active={tab === "calendar"}><WorkCalendarSettings key={`calendar:${principalId}`}/></Retained>
    <Retained active={tab === "roles"}><RoleCatalogSettings key={`roles:${principalId}`}/></Retained>
    {!tenantTabs.has(tab) && <div className={styles.scope}><label>品类范围<select value={categoryId} onChange={event => setSelected(event.target.value)}>{!categoryId && <option value="">暂无可用范围</option>}{categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>}
    {categoryId ? <ScopedSettings key={`${principalId}:${categoryId}`} principalId={principalId} categoryId={categoryId} tab={tab} onOpenRun={onOpenRun} administrator={administrator}/> : !tenantTabs.has(tab) && <p className={styles.note}>当前没有可用的品类范围。</p>}
  </section>;
}
