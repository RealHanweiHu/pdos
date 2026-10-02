"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import type { Project } from "./project-types";
import { ProjectMembers } from "./project-members";
import { ProjectIntake } from "./project-intake";
import { ProjectTemplatePanel } from "./project-template-panel";
import { ProjectCompletionPanel } from "./project-completion-panel";
import { ProjectReportExports } from "./project-report-exports";
import { CustomerReportPackages } from "./customer-report-packages";
import { AuditEvidenceExports } from "./audit-evidence-exports";
import { OpenApiAccess } from "./open-api-access";
import { ProjectWebhooks } from "./project-webhooks";
import { ValueMeasurement } from "./value-measurement";

const sections = [
  { key: "people", label: "成员与权限", description: "管理项目成员、负责人及项目内访问权限。" },
  { key: "workflow", label: "流程与资料导入", description: "维护项目流程，核对历史资料导入记录。" },
  { key: "reports", label: "报告与导出", description: "整理内部报告、客户报告与审核证据包。" },
  { key: "connections", label: "接口与测量", description: "管理受控接口、事件通知与活动测量。" },
  { key: "completion", label: "结项与交接", description: "核对配置、原件、残余问题与具名交接。" },
];
function Reports({ projectId }: { projectId: string }) {
  return <><ProjectReportExports projectId={projectId}/><CustomerReportPackages projectId={projectId}/><AuditEvidenceExports projectId={projectId}/></>;
}
export function ProjectManagementPanel({ project, userId, canManage, external = false }: { project: Project; userId: string; canManage: boolean; external?: boolean }) {
  const query = useSearchParams();
  // Old links to completion/intake keep the relevant group visible after
  // moving those tools out of the overview. Explicit section links win.
  const selected = query.get("section") ?? (query.has("completion_item") ? "completion" : query.has("intake_proposal") || query.has("intake_decision") ? "workflow" : "people");
  const available = external ? sections.filter(section => ["reports", "connections"].includes(section.key)) : sections;
  const current = available.find(section => section.key === selected) ?? available[0];
  return <section aria-label={external ? "项目服务" : "项目设置内容"} className="space-y-5">
    <nav aria-label={external ? "项目服务分类" : "项目设置分类"} className="flex flex-wrap gap-1 border-b pb-3">{available.map(section => <Link prefetch={false} key={section.key} aria-current={current.key === section.key ? "page" : undefined} className={cn("inline-flex min-h-11 items-center rounded-md px-3 text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", current.key === section.key ? "bg-muted font-medium text-foreground" : "text-muted-foreground")} href={`/projects?${new URLSearchParams({ project: project.id, tab: "management", section: section.key })}`}>{section.label}</Link>)}</nav>
    <div><h2 className="text-base font-semibold">{current.label}</h2><p className="mt-1 text-sm text-muted-foreground">{current.description}</p></div>
    <div className="space-y-4">
      {!external && current.key === "people" && <ProjectMembers projectId={project.id} userId={userId}/>}
      {!external && current.key === "workflow" && <><ProjectTemplatePanel projectId={project.id} stageCode={project.current_stage.code} canManage={canManage}/><ProjectIntake projectId={project.id}/></>}
      {current.key === "reports" && <Reports projectId={project.id}/>}
      {current.key === "connections" && <><OpenApiAccess projectId={project.id}/><ProjectWebhooks projectId={project.id}/>{!external && <ValueMeasurement projectId={project.id}/>}</>}
      {!external && current.key === "completion" && <ProjectCompletionPanel projectId={project.id} userId={userId} canManage={canManage}/>}
    </div>
  </section>;
}
