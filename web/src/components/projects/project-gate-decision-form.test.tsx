import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectGateDecisionForm } from "./project-gate-decision-form";

const projectId = "11111111-aaaa-4bbb-8ccc-dddddddddddd";
const gateId = "22222222-aaaa-4bbb-8ccc-eeeeeeeeeeee";
const ownerId = "33333333-aaaa-4bbb-8ccc-ffffffffffff";

function mount(onRecorded = vi.fn()) {
  render(
    <ProjectGateDecisionForm
      gateId={gateId}
      gateLabel="EVT Gate"
      onRecorded={onRecorded}
      projectId={projectId}
    />,
  );
  return onRecorded;
}

describe("ProjectGateDecisionForm", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (url) => String(url).endsWith("/assignment-options") ? Response.json({ members: [{ user_id: ownerId, display_name: "模拟责任人" }] }) : Response.json({ id: "decision" }));
  });

  afterEach(cleanup);

  it("requires a rationale before anything can be recorded", () => {
    mount();
    expect(
      screen.getByRole("button", { name: "记录决策" }).hasAttribute("disabled"),
    ).toBe(true);

    fireEvent.change(screen.getByLabelText("决策理由"), {
      target: { value: "全部缺项已清零" },
    });
    expect(
      screen.getByRole("button", { name: "记录决策" }).hasAttribute("disabled"),
    ).toBe(false);
  });

  it("a plain pass sends no conditions key at all", async () => {
    const onRecorded = mount();
    fireEvent.change(screen.getByLabelText("决策理由"), {
      target: { value: "全部缺项已清零" },
    });
    fireEvent.click(screen.getByRole("button", { name: "记录决策" }));

    await waitFor(() => {
      const body = JSON.parse(String(fetchMock.mock.calls.find(call => call[1]?.method === "POST")?.[1]?.body));
      expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
        `/api/projects/${projectId}/gates/${gateId}/decisions`,
      );
      // The server refuses a non-conditional decision that carries conditions,
      // so an empty array would be wrong — the key must be absent.
      expect(body).toEqual({ status: "approved", rationale: "全部缺项已清零" });
      expect("conditions" in body).toBe(false);
    });
    expect(onRecorded).toHaveBeenCalled();
  });

  it("a conditional pass cannot be submitted until the condition is complete", async () => {
    mount();
    fireEvent.change(screen.getByLabelText("Gate 决策结论"), {
      target: { value: "conditional" },
    });
    fireEvent.change(screen.getByLabelText("决策理由"), {
      target: { value: "允许并行推进" },
    });

    // Rationale alone is not enough once the outcome is conditional.
    expect(
      screen.getByRole("button", { name: "记录决策" }).hasAttribute("disabled"),
    ).toBe(true);

    fireEvent.change(screen.getByLabelText("条件内容"), {
      target: { value: "补一次密封复测" },
    });
    await screen.findByRole("option", { name: "模拟责任人" });
    fireEvent.change(screen.getByLabelText("条件负责人"), {
      target: { value: ownerId },
    });
    fireEvent.change(screen.getByLabelText("条件截止日期"), {
      target: { value: "2026-10-01" },
    });
    fireEvent.change(screen.getByLabelText("条件关闭证据"), {
      target: { value: "TR-2026-014" },
    });

    fireEvent.click(screen.getByRole("button", { name: "记录决策" }));

    await waitFor(() => {
      const body = JSON.parse(String(fetchMock.mock.calls.find(call => call[1]?.method === "POST")?.[1]?.body));
      expect(body).toEqual({
        status: "conditional",
        rationale: "允许并行推进",
        conditions: [
          {
            title: "补一次密封复测",
            owner_user_id: ownerId,
            due_date: "2026-10-01",
            closure_evidence: "TR-2026-014",
          },
        ],
      });
    });
  });

  it("shows the server's refusal and does not report success", async () => {
    const onRecorded = mount();
    fetchMock.mockImplementation(async () =>
      Response.json(
        { detail: { code: "GATE_NOT_READY", message: "Gate readiness is incomplete" } },
        { status: 409 },
      ),
    );

    fireEvent.change(screen.getByLabelText("决策理由"), {
      target: { value: "先批了再说" },
    });
    fireEvent.click(screen.getByRole("button", { name: "记录决策" }));

    expect(await screen.findByText("Gate readiness is incomplete")).toBeTruthy();
    expect(onRecorded).not.toHaveBeenCalled();
  });
  it("allows a hold while readiness blocks both approval outcomes", async () => {
    render(<ProjectGateDecisionForm projectId={projectId} gateId={gateId} gateLabel="模拟 Gate" gateReady={false} onRecorded={vi.fn()} />);
    expect(screen.getByRole("option", { name: /^通过$/ })).toHaveProperty("disabled", true);
    expect(screen.getByRole("option", { name: /^有条件通过$/ })).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("决策理由"), { target: { value: "资料待补，暂缓本轮" } });
    fireEvent.click(screen.getByRole("button", { name: "记录决策" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ status: "hold", rationale: "资料待补，暂缓本轮" });
  });

});
