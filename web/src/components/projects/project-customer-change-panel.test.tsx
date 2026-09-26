import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectCustomerChangePanel } from "./project-customer-change-panel";

const projectId = "aaaaaaaa-1111-4222-8333-444444444444";
const ccrId = "bbbbbbbb-5555-4666-8777-888888888888";
const drafterId = "cccccccc-9999-4aaa-8bbb-cccccccccccc";
const otherUserId = "dddddddd-9999-4aaa-8bbb-dddddddddddd";

function ccr(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: ccrId,
    code: "CCR-001",
    title: "客户要求提高气压至 9 bar",
    status,
    description: null,
    quote_note: null,
    lead_time_days: null,
    customer_decision_note: null,
    impact_analysis: null,
    reply_drafted_by_user_id: null,
    engineering_change_request_id: null,
    ...extra,
  };
}

function mount(
  items: unknown[],
  overrides: { canApprove?: boolean; userId?: string } = {},
) {
  return render(
    <ProjectCustomerChangePanel
      canApprove={overrides.canApprove ?? true}
      canEdit
      currentUserId={overrides.userId ?? otherUserId}
      projectId={projectId}
    />,
  );
}

describe("ProjectCustomerChangePanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(cleanup);

  it("shows the deterministic impact counts rather than a summary sentence", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({
        items: [
          ccr("impact_analyzed", {
            impact_analysis: {
              counts: { requirements: 2, specifications: 5, test_cases: 9 },
              retest_required: 4,
            },
          }),
        ],
      }),
    );

    mount([]);

    expect(await screen.findByText("CCR-001")).toBeTruthy();
    expect(screen.getByText(/需求 2/)).toBeTruthy();
    expect(screen.getByText(/需复测 4/)).toBeTruthy();
  });

  it("the quote drafter is told to find a second pair of eyes, not shown approve", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({
        items: [ccr("reply_drafted", { reply_drafted_by_user_id: drafterId })],
      }),
    );

    mount([], { canApprove: true, userId: drafterId });
    await screen.findByText("CCR-001");

    expect(screen.queryByRole("button", { name: "批准对外答复" })).toBeNull();
    expect(screen.getByText(/四眼原则/)).toBeTruthy();
  });

  it("a different approver can approve the same reply", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({
        items: [ccr("reply_drafted", { reply_drafted_by_user_id: drafterId })],
      }),
    );

    mount([], { canApprove: true, userId: otherUserId });
    await screen.findByText("CCR-001");

    expect(screen.getByRole("button", { name: "批准对外答复" })).toBeTruthy();
  });

  it("drafting a reply sends the quote and lead time the server requires", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({ items: [ccr("impact_analyzed")] }),
    );
    mount([]);
    await screen.findByText("CCR-001");

    fireEvent.change(screen.getByLabelText("CCR-001 报价说明"), {
      target: { value: "增加 12 元/台" },
    });
    fireEvent.change(screen.getByLabelText("CCR-001 交期天数"), {
      target: { value: "21" },
    });
    fireEvent.click(screen.getByRole("button", { name: "起草答复" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/reply"));
      expect(String(write?.[0])).toBe(
        `/api/projects/${projectId}/customer-changes/${ccrId}/reply`,
      );
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        quote_note: "增加 12 元/台",
        lead_time_days: 21,
      });
    });
  });

  it("a non-numeric lead time cannot be submitted", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({ items: [ccr("impact_analyzed")] }),
    );
    mount([]);
    await screen.findByText("CCR-001");

    fireEvent.change(screen.getByLabelText("CCR-001 报价说明"), {
      target: { value: "增加 12 元/台" },
    });
    fireEvent.change(screen.getByLabelText("CCR-001 交期天数"), {
      target: { value: "三周" },
    });

    expect(
      screen.getByRole("button", { name: "起草答复" }).hasAttribute("disabled"),
    ).toBe(true);
  });
});
