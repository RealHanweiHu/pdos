import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "./project-types";
import type { ProjectTask, ProjectWorkItems } from "./project-work-item-types";
import { ProjectStageBoard } from "./project-stage-board";
import { ProjectTimeline } from "./project-timeline";
import { resolveTab } from "./project-workspace-view";

const stages = [1, 2, 3].map(n => ({ id: `stage-${n}`, code: `s${n}`, name: `阶段${n}`, sequence: n, description: null }));
const project = { id: "project-one", name: "项目一", status: "active", current_stage: stages[1], workflow: { name: "实际三阶段模板", version: 2, stages } } as Project;
function task(id: string, stage: string | null, status = "todo"): ProjectTask {
  return { id, title: id, stage_id: stage, status, kind: "task", readiness: "ready", due_date: null, dependency_task_ids: [] } as unknown as ProjectTask;
}
const empty: ProjectWorkItems = { tasks: [], issues: [], risks: [] };
afterEach(cleanup);
describe("项目阶段泳道与工作区布局", () => {
  it("uses the actual workflow and keeps unassigned/removed-stage work visible", () => {
    render(<ProjectStageBoard project={project} canViewWorkItems workItems={{ ...empty, tasks: [task("当前任务", "stage-2"), task("待归类任务", null), task("旧阶段任务", "retired-stage")] }} onPlan={vi.fn()}/>);
    expect(screen.getAllByRole("columnheader")).toHaveLength(5);
    expect(screen.getByRole("columnheader", { name: /阶段2.*当前阶段/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "未归阶段" })).toBeInTheDocument();
    const current = screen.getByRole("link", { name: "打开任务：当前任务" });
    expect(current).toHaveAttribute("href", "/projects?project=project-one&tab=work-items&entity_id=%E5%BD%93%E5%89%8D%E4%BB%BB%E5%8A%A1");
    expect(screen.getByRole("link", { name: "打开任务：待归类任务" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开任务：旧阶段任务" })).toBeInTheDocument();
  });
  it("filters completed work while preserving its unknown-stage column, and shows actual dependency titles on request", () => {
    const dependent = { ...task("联调", "stage-2"), dependency_task_ids: ["原前置"] };
    render(<ProjectStageBoard project={project} canViewWorkItems workItems={{ ...empty, tasks: [task("原前置", "stage-1", "done"), dependent, task("已完成未归阶段", null, "done")] }} onPlan={vi.fn()}/>);
    fireEvent.click(screen.getByRole("checkbox", { name: "仅未完成" }));
    expect(screen.queryByRole("link", { name: "打开任务：原前置" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "未归阶段" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "显示前置关系" }));
    expect(screen.getByText("前置：原前置")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "阶段列表" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("阶段2")).toBeVisible();
  });
  it("does not display false zero counts while source data is unavailable", () => {
    render(<ProjectStageBoard project={project} canViewWorkItems workItems={null} onPlan={vi.fn()}/>);
    expect(screen.getByText("工作项尚未读取，不能据此判断任务或问题数量。")).toBeVisible();
    expect(screen.queryByText("暂无事项")).not.toBeInTheDocument();
    expect(screen.queryByText("当前无开放风险")).not.toBeInTheDocument();
  });
  it("never exposes internal work supplied accidentally to an external overview", () => {
    render(<ProjectStageBoard project={project} canViewWorkItems={false} workItems={{ ...empty, tasks: [task("内部任务", "stage-2")] }} onPlan={vi.fn()}/>);
    expect(screen.queryByText("内部任务")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "办理计划与资源" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(3);
  });
  it("keeps a deep-linked older event visible without rendering the entire activity history", () => {
    const activities = Array.from({ length: 20 }, (_, i) => ({ id: 20 - i, event_type: "TEST_FAILED", entity: "test_report", entity_id: `report-${i}`, timestamp: "2026-09-30T01:00:00Z" }));
    render(<ProjectTimeline project={project} activities={activities} activityError={false} loading={false} highlightedEntityId={null} highlightedEventId={2} onRetry={vi.fn()}/>);
    const list = screen.getByRole("list", { name: "近期活动记录" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    expect(document.getElementById("event-2")).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "展开全部 20 条记录" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(20);
  });
  it("restores moved management and engineering links while letting another explicit domain win", () => {
    expect(resolveTab("overview", new URLSearchParams("completion_item=configuration"))).toBe("management");
    expect(resolveTab(null, new URLSearchParams("intake_proposal=original"))).toBe("management");
    expect(resolveTab("overview", new URLSearchParams("id_freeze_request=original&id_revision=revision"))).toBe("engineering");
    expect(resolveTab("quality", new URLSearchParams("completion_item=configuration"))).toBe("quality");
    expect(resolveTab("management")).toBe("management");
  });
});
