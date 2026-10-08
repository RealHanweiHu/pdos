import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import type { MyWork } from "./my-work-types";
import { collectionForWorkAnchor, preferredWorkScenario, scenarioCount, scenarioHasCollection } from "./my-work-scenario";
import { MyWorkView } from "./my-work-view";
import { WorkPriorityIndex } from "./work-priority-index";

vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/components/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("@/components/product-work/preproject-work", () => ({ PreProjectWork: () => <section aria-label="立项前工作"><label>专业协审说明<input defaultValue="" /></label></section> }));
vi.mock("@/components/ai/conversation-finding", () => ({ ConversationFinding: () => <label>候选修订<input defaultValue="原结论" /></label> }));
vi.mock("@/components/ai/finding-review-undo", () => ({ FindingReviewUndo: () => null }));
vi.mock("@/components/ai/finding-batch-review", () => ({ FindingBatchReview: () => <p>批量工具</p> }));
vi.mock("@/components/ai/finding-proposal", () => ({ FindingAppliedReceipt: () => null }));
vi.mock("./work-card-conversation", () => ({ WorkCardConversation: () => null }));
vi.mock("./work-search", () => ({ WorkSearch: () => <label>工具检索<input defaultValue="" /></label> }));
vi.mock("./reminder-preferences", () => ({ ReminderPreferences: () => null }));
vi.mock("./use-my-work-queue", () => ({ useMyWorkQueue: (work: MyWork) => ({ work, busy: null, error: null, refresh: vi.fn(), loadMore: vi.fn() }) }));

const project = { id: "project-one", code: "P-01", name: "泵类开发" };
const identity = { tenant: { id: "tenant", slug: "company", name: "公司" }, user: { id: "person", tenant_id: "tenant", username: "person", display_name: "小李", role: "engineer", email: null, is_active: true } } as WorkspaceIdentity;
const empty = (): MyWork => ({ tasks: [], issues: [], risks: [], capa_actions: [], gate_signoffs: [], findings: [], counts: { tasks: 0, issues: 0, risks: 0, capa_actions: 0, gate_signoffs: 0, findings: 0 } });
const populated = (): MyWork => ({
  ...empty(),
  tasks: [{ id: "task-one", project, title: "样机整改", status: "todo", priority: "high", due_date: "2020-01-01" }],
  issues: [{ id: "issue-one", project, title: "密封问题", status: "verification", severity: "high", target_date: null }],
  gate_signoffs: [{ id: "gate-one", project, gate_id: "gate", gate_code: "evt", gate_name: "EVT", slot: "engineering", requirement: "required", round_number: 2, review_due_at: null }],
  findings: [{ id: "finding-one", project, title: "AI 研究建议", finding_type: "research", created_at: "2026-10-01T08:00:00Z" }],
  counts: { tasks: 50, issues: 1, risks: 0, capa_actions: 0, gate_signoffs: 2, findings: 3 },
});

function renderWork(work = populated(), currentIdentity = identity) {
  return render(<MyWorkView identity={currentIdentity} loggingOut={false} notifications={{ items: [], unread_count: 0, digest: [] }} notificationState="ready" onAcknowledge={vi.fn()} onRetryNotifications={vi.fn()} onLogout={vi.fn()} today="2026-10-01" work={work} />);
}
const scenarioButton = (label: string) => within(screen.getByRole("group", { name: "办理场景" })).getByRole("button", { name: new RegExp(`^${label}`) });

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/my-work");
});

describe("My Work 场景与责任数据", () => {
  it("counts full server totals and never invents a zero for pre-project work", () => {
    const work = empty();
    work.counts = { tasks: 50, issues: 4, risks: 9, capa_actions: 2, gate_signoffs: 6, findings: 12, cross_schedule_approvals: 10, id_design_actions: 7, change_execution_confirmations: 3, risk_followup_actions: 5, task_takeover_actions: 8, cost_freeze_approvals: 11 };
    expect(scenarioCount("all", work.counts)).toBe(127);
    expect(scenarioCount("execution", work.counts)).toBe(64);
    expect(scenarioCount("reception", work.counts)).toBe(25);
    expect(scenarioCount("coordination", work.counts)).toBe(30);
    expect(scenarioCount("preproject", work.counts)).toBeNull();
    expect(scenarioHasCollection("execution", "issues")).toBe(true);
    expect(scenarioHasCollection("reception", "issues")).toBe(true);
  });

  it("chooses actual urgency and recognizes every existing receipt anchor", () => {
    expect(preferredWorkScenario(populated(), "2026-10-01")).toBe("execution");
    const work = populated();
    work.tasks = [];
    work.gate_signoffs[0].review_due_at = "2020-01-01T01:00:00+08:00";
    expect(preferredWorkScenario(work, "2026-10-01")).toBe("reception");
    expect(collectionForWorkAnchor("work-risk-result-original")).toBe("risk_followup_actions");
    expect(collectionForWorkAnchor("work-cross-project-original")).toBe("cross_schedule_approvals");
    expect(collectionForWorkAnchor("work-id-handoff-original")).toBe("id_design_actions");
    expect(collectionForWorkAnchor("unrelated-anchor")).toBeNull();
  });

  it.each([
    ["product_manager", "产品工作台", "进入产品主题", "/product-work"],
    ["project_manager", "项目工作台", "推进项目计划", "/projects"],
    ["engineer", "工程工作台", "进入工程与变更", "/projects"],
    ["quality", "品质工作台", "进入试制测试与质量", "/projects"],
    ["owner", "管理工作台", "处理组合与重大例外", "/portfolio"],
    ["admin", "系统工作台", "管理成员与角色", "/governance/users"],
  ])("shows %s their name, role actions and actual assigned work", (role, title, action, href) => {
    renderWork(populated(), { ...identity, user: { ...identity.user, role } });
    expect(screen.getByRole("heading", { name: `小李的${title}` })).toBeInTheDocument();
    const shortcuts = within(screen.getByRole("navigation", { name: "我的常用工作" }));
    expect(shortcuts.getByRole("link", { name: action })).toHaveAttribute("href", href);
    expect(screen.getByRole("region", { name: "任务" })).toHaveTextContent("样机整改");
  });

  it("keeps a product manager's research work visible alongside urgent project tasks on arrival", () => {
    renderWork(populated(), { ...identity, user: { ...identity.user, role: "product_manager" } });
    expect(scenarioButton("执行与整改")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "立项前工作" })).toBeVisible();
    expect(screen.getByRole("region", { name: "任务" })).toBeVisible();
  });

  it("opens the personal assistant from the work home", () => {
    const open = vi.fn();
    window.addEventListener("pdos:open-xiaopai", open);
    renderWork();
    fireEvent.click(screen.getByRole("button", { name: "交给小Pai" }));
    expect(open).toHaveBeenCalledOnce();
    window.removeEventListener("pdos:open-xiaopai", open);
  });

  it("shows full scene counts while preserving hidden domain drafts", () => {
    renderWork();
    expect(scenarioButton("执行与整改")).toHaveAttribute("aria-pressed", "true");
    expect(scenarioButton("全部办理")).toHaveTextContent("56");
    expect(scenarioButton("执行与整改")).toHaveTextContent("51");
    expect(scenarioButton("验证与接收")).toHaveTextContent("3");
    fireEvent.click(scenarioButton("AI 建议"));
    const input = screen.getByLabelText("候选修订") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "正在核对的真实来源" } });
    fireEvent.click(scenarioButton("执行与整改"));
    expect(input).toBeInTheDocument();
    expect(input).not.toBeVisible();
    fireEvent.click(scenarioButton("AI 建议"));
    expect(screen.getByLabelText("候选修订")).toBe(input);
    expect(input.value).toBe("正在核对的真实来源");
    expect(input).toBeVisible();
  });

  it("opens the correct scenario before priority navigation and retains query context", async () => {
    window.history.replaceState(null, "", "/my-work?source=original");
    renderWork();
    fireEvent.click(within(screen.getByRole("region", { name: "工作优先事项" })).getByRole("link", { name: /AI 研究建议/ }));
    await waitFor(() => expect(screen.getByLabelText("候选修订")).toBeVisible());
    expect(scenarioButton("AI 建议")).toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).toBe("?source=original");
    expect(window.location.hash).toBe("#work-finding-finding-one");
    fireEvent.click(scenarioButton("执行与整改"));
    window.history.replaceState(null, "", "/my-work?source=original#work-gate-gate-one");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(scenarioButton("验证与接收")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("region", { name: "Gate 待我签核" })).toBeVisible();
  });

  it("keeps pre-project work and secondary tools mounted through scenario switches", () => {
    renderWork();
    fireEvent.click(scenarioButton("立项前工作"));
    const review = screen.getByLabelText("专业协审说明") as HTMLInputElement;
    fireEvent.change(review, { target: { value: "需要品质协审" } });
    const tools = screen.getByText("查找、提醒与批量办理").closest("details")!;
    tools.open = true;
    const search = screen.getByLabelText("工具检索") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "未加载的历史事项" } });
    fireEvent.click(scenarioButton("执行与整改"));
    expect(review).not.toBeVisible();
    expect(search).toBeVisible();
    expect(search.value).toBe("未加载的历史事项");
    fireEvent.click(scenarioButton("立项前工作"));
    expect(review).toBeVisible();
    expect(review.value).toBe("需要品质协审");
  });

  it("retains an explicitly opened receiving panel when another scenario is selected", () => {
    const work = populated();
    work.id_design_actions = [{ id: "handoff-one", project, kind: "handoff", revision_id: "revision", freeze_id: null, title: "结构输入", created_at: "2026-10-01T08:00:00Z" }];
    work.counts.id_design_actions = 1;
    renderWork(work);
    fireEvent.click(scenarioButton("验证与接收"));
    fireEvent.click(screen.getByRole("button", { name: /逐项接收 · 结构输入/ }));
    const panel = screen.getByRole("region", { name: "ID设计待办办理" });
    fireEvent.click(scenarioButton("执行与整改"));
    expect(panel).toBeVisible();
    expect(screen.getByRole("region", { name: "ID设计待办办理" })).toBe(panel);
  });

  it("keeps priority links usable independently and reports their exact collection", () => {
    const navigate = vi.fn();
    render(<WorkPriorityIndex today="2026-10-01" work={populated()} onNavigate={navigate} />);
    const link = screen.getByRole("link", { name: /AI 研究建议/ });
    expect(link).toHaveAttribute("href", "#work-finding-finding-one");
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith("findings", "work-finding-finding-one");
    navigate.mockClear();
    fireEvent.click(link, { ctrlKey: true });
    expect(navigate).not.toHaveBeenCalled();
  });
});
