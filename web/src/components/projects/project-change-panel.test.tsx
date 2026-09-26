import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectChangePanel } from "./project-change-panel";

const projectId = "11111111-2222-4333-8444-555555555555";
const ecrId = "66666666-7777-4888-8999-aaaaaaaaaaaa";

function ecr(status: string) {
  return {
    id: ecrId,
    code: "ECR-001",
    title: "泵体壁厚由 2.0 改为 2.4",
    reason: "耐压测试不通过",
    status,
  };
}

function mount(overrides: { canEdit?: boolean; canApprove?: boolean } = {}) {
  return render(
    <ProjectChangePanel
      canApprove={overrides.canApprove ?? false}
      canEdit={overrides.canEdit ?? true}
      projectId={projectId}
    />,
  );
}

describe("ProjectChangePanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(cleanup);

  it("lists change requests with their state", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({ ecrs: [ecr("impact_analysis")], ecns: [] }),
    );

    mount();

    expect(await screen.findByText("泵体壁厚由 2.0 改为 2.4")).toBeTruthy();
    expect(screen.getByText("影响分析中")).toBeTruthy();
    expect(screen.getByText("耐压测试不通过")).toBeTruthy();
  });

  it("offers only the transition the current status allows", async () => {
    fetchMock.mockImplementation(async () => Response.json({ ecrs: [ecr("request")], ecns: [] }));

    mount({ canApprove: true });
    await screen.findByText("ECR-001");

    expect(screen.getByRole("button", { name: "开始影响分析" })).toBeTruthy();
    // Approval is not reachable from `request`; the panel must not offer it.
    expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
    expect(screen.queryByRole("button", { name: "提交影响分析" })).toBeNull();
  });

  it("an editor cannot approve, only an approver can", async () => {
    fetchMock.mockImplementation(async () => Response.json({ ecrs: [ecr("approval")], ecns: [] }));

    const editorOnly = mount({ canEdit: true, canApprove: false });
    await screen.findByText("ECR-001");
    expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
    editorOnly.unmount();

    mount({ canEdit: true, canApprove: true });
    await screen.findByText("ECR-001");
    expect(screen.getByRole("button", { name: "批准" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "驳回" })).toBeTruthy();
  });

  it("raising an ECR posts exactly the three fields the server accepts", async () => {
    fetchMock.mockImplementation(async () => Response.json({ ecrs: [], ecns: [] }));
    mount();
    await screen.findByText("尚无工程变更。");

    fireEvent.change(screen.getByLabelText("ECR 编号"), { target: { value: "ECR-002" } });
    fireEvent.change(screen.getByLabelText("ECR 标题"), { target: { value: "改密封圈材质" } });
    fireEvent.change(screen.getByLabelText("变更原因"), { target: { value: "高温老化" } });
    fireEvent.click(screen.getByRole("button", { name: "提出变更" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => call[1]?.method === "POST");
      expect(String(write?.[0])).toBe(`/api/projects/${projectId}/changes/ecrs`);
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        code: "ECR-002",
        title: "改密封圈材质",
        reason: "高温老化",
      });
    });
  });

  it("deciding sends the outcome the server expects", async () => {
    fetchMock.mockImplementation(async () => Response.json({ ecrs: [ecr("approval")], ecns: [] }));
    mount({ canApprove: true });
    await screen.findByText("ECR-001");

    fireEvent.click(screen.getByRole("button", { name: "驳回" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => String(call[0]).includes("/decide"));
      expect(String(write?.[0])).toBe(
        `/api/projects/${projectId}/changes/ecrs/${ecrId}/decide`,
      );
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({ outcome: "rejected" });
    });
  });

  it("surfaces a refusal rather than an empty change list", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json(
        { detail: { code: "PROJECT_ACCESS_DENIED", message: "Project access denied" } },
        { status: 403 },
      ),
    );

    mount();

    expect(await screen.findByText("Project access denied")).toBeTruthy();
    expect(screen.queryByText("尚无工程变更。")).toBeNull();
  });
});
