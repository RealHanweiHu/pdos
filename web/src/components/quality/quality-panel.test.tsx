import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QualityPanel } from "./quality-panel";
import type { Complaint } from "./quality-types";

const complaint: Complaint = {
  id: "complaint-1",
  project_id: "project-1",
  customer_id: null,
  reported_by_user_id: "user-1",
  owner_user_id: "user-1",
  closed_by_user_id: null,
  code: "CMP-001",
  title: "现场连接器间歇开路",
  description: "热循环后接触电阻超限。",
  source: "field",
  severity: "high",
  status: "open",
  occurred_at: "2026-08-12T08:00:00Z",
  reported_at: "2026-08-12T10:00:00Z",
  customer_reference: null,
  affected_scope: "Lot C4s",
  document_refs: [],
  resolution_summary: null,
  closed_at: null,
  created_at: "2026-08-12T10:00:00Z",
  updated_at: "2026-08-12T10:00:00Z",
};

const base = {
  busy: false,
  canCreate: true,
  canManage: true,
  detail: null,
  error: null,
  identityUserId: "user-1",
  loadState: "ready" as const,
  onCreate: vi.fn(async () => true),
  onRetry: vi.fn(),
  onSelect: vi.fn(),
  onTriage: vi.fn(async () => true),
};

describe("QualityPanel", () => {
  it("renders meaningful empty and loading states", () => {
    const { rerender } = render(<QualityPanel {...base} complaints={null} selectedComplaint={null} />);
    expect(screen.getByRole("heading", { name: "暂无质量反馈" })).toBeInTheDocument();

    rerender(
      <QualityPanel
        {...base}
        complaints={null}
        loadState="loading"
        selectedComplaint={null}
      />,
    );
    expect(screen.getByLabelText("正在加载质量记录")).toHaveAttribute("aria-busy", "true");
  });

  it("supports keyboard selection and exposes labeled triage fields", async () => {
    const user = userEvent.setup();
    render(<QualityPanel {...base} complaints={[complaint]} selectedComplaint={complaint} />);

    const item = screen.getByRole("button", { name: /CMP-001/ });
    await user.click(item);
    expect(base.onSelect).toHaveBeenCalledWith(complaint);
    expect(screen.getByRole("heading", { name: "现场连接器间歇开路" })).toBeInTheDocument();
    expect(screen.getByLabelText("不符合描述")).toBeInTheDocument();
    expect(screen.getByLabelText("违反要求")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认 Triage" })).toHaveClass("h-11");
  });
});
