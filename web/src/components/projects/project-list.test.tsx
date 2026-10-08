import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectList } from "./project-list";
import type { Project } from "./project-types";

const stage = {
  id: "stage-evt", code: "evt", name: "EVT 工程验证", description: null, sequence: 1,
};
const projects: Project[] = [
  {
    id: "project-1", code: "PRJ-001", name: "户外泵项目", status: "active",
    current_stage: stage,
    workflow: {
      id: "workflow-1", code: "npd", name: "开发流程", description: null,
      version: 1, is_active: true, stages: [stage],
    },
    owner_user_id: "user-1", development_case_id: null, customer_id: null,
    description: null, start_date: null, target_date: null,
    created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  },
  {
    id: "project-2", code: "PRJ-002", name: "户外泵二代", status: "on_hold",
    current_stage: { ...stage, id: "stage-dvt", code: "dvt", name: "DVT 设计验证" },
    workflow: {
      id: "workflow-2", code: "npd", name: "开发流程", description: null,
      version: 1, is_active: true, stages: [stage],
    },
    owner_user_id: "user-1", development_case_id: null, customer_id: null,
    description: null, start_date: null, target_date: null,
    created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  },
];

function renderList(items = projects) {
  const onSelect = vi.fn();
  render(<ProjectList projects={items} selectedId={null} onSelect={onSelect} />);
  return onSelect;
}

describe("ProjectList directory search", () => {
  afterEach(cleanup);

  it("finds project identifiers and stages while retaining the original project action", async () => {
    const user = userEvent.setup();
    const onSelect = renderList();
    const search = screen.getByRole("searchbox", { name: "搜索项目" });
    expect(search).toHaveAttribute("autocomplete", "off");

    await user.type(search, "  prj-002  ");
    expect(screen.queryByRole("button", { name: "打开项目 PRJ-001" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开项目 PRJ-002" }));
    expect(onSelect).toHaveBeenCalledWith(projects[1]);

    await user.clear(search);
    await user.type(search, "evt");
    expect(screen.getByRole("button", { name: "打开项目 PRJ-001" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开项目 PRJ-002" })).not.toBeInTheDocument();
  });

  it("combines name search with the actual project status", async () => {
    const user = userEvent.setup();
    renderList();
    await user.type(screen.getByRole("searchbox", { name: "搜索项目" }), "户外泵");
    await user.selectOptions(screen.getByRole("combobox", { name: "项目状态" }), "on_hold");
    const list = within(screen.getByRole("region", { name: "项目列表" }));
    expect(list.getByText("1 / 2 条")).toBeInTheDocument();
    expect(list.getByRole("button", { name: "打开项目 PRJ-002" })).toHaveTextContent("已暂停");
    expect(list.queryByRole("button", { name: "打开项目 PRJ-001" })).not.toBeInTheDocument();
  });

  it("distinguishes no search results and clears both filters with focus restored", async () => {
    const user = userEvent.setup();
    renderList();
    await user.type(screen.getByRole("searchbox", { name: "搜索项目" }), "不存在的项目");
    await user.selectOptions(screen.getByRole("combobox", { name: "项目状态" }), "completed");
    expect(screen.getByText("没有符合条件的项目")).toBeInTheDocument();
    expect(screen.queryByText("还没有项目")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(screen.getByRole("searchbox", { name: "搜索项目" })).toHaveValue("");
    expect(screen.getByRole("searchbox", { name: "搜索项目" })).toHaveFocus();
    expect(screen.getByRole("combobox", { name: "项目状态" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: "打开项目 PRJ-001" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开项目 PRJ-002" })).toBeInTheDocument();
  });

  it("retains the approved-case entry guidance when there are no projects", () => {
    renderList([]);
    expect(screen.getByText("还没有项目")).toBeInTheDocument();
    expect(screen.getByText("从已批准的开发案例创建第一个项目。")).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });
});
