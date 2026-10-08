import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectTaskWorkspace, type ProjectTaskSection } from "./project-task-workspace";

function Draft({ onMount }: { onMount?: () => void }) {
  const [value, setValue] = useState(() => {
    onMount?.();
    return "";
  });
  return <label>办理草稿<input value={value} onChange={event => setValue(event.target.value)} /></label>;
}

const sections = (): ProjectTaskSection[] => [
  { id: "plan", title: "安排当前任务", description: "落实本期负责人和交付日期。", queryKeys: ["task_id"], children: <p>计划办理内容</p> },
  { id: "resources", title: "协调资源预约", queryKeys: ["reservation_id"], hashPrefixes: ["#reservation-"], children: <Draft /> },
  { id: "commitments", title: "处理交付承诺", queryKeys: ["commitment_id"], hashPrefixes: ["commitment-"], children: <p>承诺办理内容</p> },
];
const task = (name: string) => screen.getByRole("tab", { name });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/projects");
});

describe("项目任务办理空间", () => {
  it("shows the first task by default and respects the first explicit default", () => {
    const view = render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    expect(task("安排当前任务")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "安排当前任务" })).toBeVisible();
    expect(screen.getByText("落实本期负责人和交付日期。")).toBeVisible();
    expect(document.getElementById("resources")).not.toBeVisible();
    view.unmount();
    render(<ProjectTaskWorkspace label="项目执行" sections={sections()} defaultOpen={["commitments", "resources"]} />);
    expect(task("处理交付承诺")).toHaveAttribute("aria-selected", "true");
  });

  it("keeps a draft mounted when moving between tasks and refreshing the content", async () => {
    const user = userEvent.setup();
    const onMount = vi.fn();
    const items = sections();
    items[1].children = <Draft onMount={onMount} />;
    const view = render(<ProjectTaskWorkspace label="项目执行" sections={items} />);
    await user.click(task("协调资源预约"));
    const input = screen.getByLabelText("办理草稿");
    await user.type(input, "下周需要验证工装");
    await user.click(task("安排当前任务"));
    expect(input).not.toBeVisible();
    const refreshed = sections();
    refreshed[1].children = <Draft onMount={onMount} />;
    view.rerender(<ProjectTaskWorkspace label="项目执行" sections={refreshed} />);
    await user.click(task("协调资源预约"));
    expect(screen.getByLabelText("办理草稿")).toBe(input);
    expect(input).toHaveValue("下周需要验证工装");
    expect(onMount).toHaveBeenCalledTimes(1);
  });

  it("opens the first matching query task, including an empty receipt selector", () => {
    window.history.replaceState(null, "", "/projects?task_id=first&reservation_id=");
    render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    expect(task("安排当前任务")).toHaveAttribute("aria-selected", "true");
    cleanup();
    window.history.replaceState(null, "", "/projects?reservation_id=");
    render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    expect(task("协调资源预约")).toHaveAttribute("aria-selected", "true");
  });

  it("prioritizes the concrete fragment target over another matching query task", async () => {
    window.history.replaceState(null, "", "/projects?task_id=first&reservation_id=second#actual-commitment");
    const items = sections();
    items[2].children = <details><summary>承诺原记录</summary><p id="actual-commitment">具名承诺回执</p></details>;
    render(<ProjectTaskWorkspace label="项目执行" sections={items} />);
    await waitFor(() => expect(task("处理交付承诺")).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByText("承诺原记录").closest("details")!.open).toBe(true);
    expect(screen.getByText("具名承诺回执")).toBeVisible();
    expect(window.location.search).toBe("?task_id=first&reservation_id=second");
  });

  it("uses prefix and root fragment links and responds to browser history", () => {
    window.history.replaceState(null, "", "/projects#reservation-original");
    render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    expect(task("协调资源预约")).toHaveAttribute("aria-selected", "true");
    act(() => {
      window.history.replaceState(null, "", "/projects?commitment_id=old");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(task("处理交付承诺")).toHaveAttribute("aria-selected", "true");
    act(() => {
      window.history.replaceState(null, "", "/projects#plan");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(task("安排当前任务")).toHaveAttribute("aria-selected", "true");
  });

  it("reveals a deferred encoded fragment inside nested disclosures", async () => {
    window.history.replaceState(null, "", "/projects?task_id=current#%E5%8E%9F%E5%9B%9E%E6%89%A7");
    const view = render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    const refreshed = sections();
    refreshed[1].children = <details><summary>预约原记录</summary><details><summary>回执详情</summary><p id="原回执">实际预约回执</p></details></details>;
    view.rerender(<ProjectTaskWorkspace label="项目执行" sections={refreshed} />);
    await waitFor(() => expect(task("协调资源预约")).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByText("预约原记录").closest("details")!.open).toBe(true);
    expect(screen.getByText("回执详情").closest("details")!.open).toBe(true);
    expect(screen.getByText("实际预约回执")).toBeVisible();
  });

  it("retains a chosen task across refreshes and preserves all named query selectors", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/projects?task_id=current&reservation_id=old&view=plan");
    const view = render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    await user.click(task("处理交付承诺"));
    expect(window.location.search).toBe("?task_id=current&reservation_id=old&view=plan");
    expect(window.location.hash).toBe("#commitments");
    const refreshed = sections();
    refreshed[0].queryKeys = ["task_id", "new_receipt"];
    view.rerender(<ProjectTaskWorkspace label="项目执行" sections={refreshed} />);
    expect(task("处理交付承诺")).toHaveAttribute("aria-selected", "true");
    expect(task("处理交付承诺")).toHaveAttribute("tabindex", "0");
  });

  it("moves selection and focus with arrows, Home and End", async () => {
    const user = userEvent.setup();
    render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    task("安排当前任务").focus();
    await user.keyboard("{ArrowRight}");
    expect(task("协调资源预约")).toHaveFocus();
    expect(task("协调资源预约")).toHaveAttribute("aria-selected", "true");
    expect(task("安排当前任务")).toHaveAttribute("tabindex", "-1");
    await user.keyboard("{End}");
    expect(task("处理交付承诺")).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(task("安排当前任务")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(task("处理交付承诺")).toHaveFocus();
    await user.keyboard("{Home}");
    expect(task("安排当前任务")).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(task("处理交付承诺")).toHaveFocus();
    expect(window.location.hash).toBe("#commitments");
  });

  it("does not reveal an unrelated fragment outside its workspace", () => {
    window.history.replaceState(null, "", "/projects#external-receipt");
    render(<><p id="external-receipt">其他工作区的回执</p><ProjectTaskWorkspace label="项目执行" sections={sections()} /></>);
    expect(task("安排当前任务")).toHaveAttribute("aria-selected", "true");
    expect(document.getElementById("resources")).not.toBeVisible();
  });

  it("cancels a pending old receipt when the person deliberately switches tasks", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/projects#late-reservation");
    const view = render(<ProjectTaskWorkspace label="项目执行" sections={sections()} />);
    await user.click(task("处理交付承诺"));
    const refreshed = sections();
    refreshed[1].children = <p id="late-reservation">后来载入的旧回执</p>;
    view.rerender(<ProjectTaskWorkspace label="项目执行" sections={refreshed} />);
    await waitFor(() => expect(task("处理交付承诺")).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByText("后来载入的旧回执")).not.toBeVisible();
  });
});
