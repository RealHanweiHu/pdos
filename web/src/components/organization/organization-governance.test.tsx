import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OrganizationGovernance } from "./organization-governance";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
  usePathname: () => "/governance/organization",
}));

const userApi = vi.hoisted(() => ({ requestUserManagementBootstrap: vi.fn() }));
vi.mock("@/components/users/user-management-api", () => userApi);

const api = vi.hoisted(() => ({
  createDepartment: vi.fn(),
  grantDelegation: vi.fn(),
  handOver: vi.fn(),
  previewHandover: vi.fn(),
  requestDelegations: vi.fn(),
  requestDepartments: vi.fn(),
  revokeDelegation: vi.fn(),
  setPlacement: vi.fn(),
}));
vi.mock("./organization-api", () => api);

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-owner",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Owner",
    role: "owner",
    email: null,
    is_active: true,
  },
};

const managedUser = (id: string, displayName: string) => ({
  id,
  tenant_id: "tenant-1",
  username: displayName.toLowerCase(),
  display_name: displayName,
  email: null,
  role: "engineer" as const,
  is_active: true,
  last_signed_in_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
});

const hourFromNow = (hours: number) => new Date(Date.now() + hours * 3_600_000).toISOString();

function bootstrapReady() {
  userApi.requestUserManagementBootstrap.mockResolvedValue({
    kind: "ready",
    identity,
    users: [managedUser("user-a", "李工"), managedUser("user-b", "王工")],
  });
}

describe("OrganizationGovernance", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders departments and delegation states", async () => {
    bootstrapReady();
    api.requestDepartments.mockResolvedValue([
      {
        id: "dept-1",
        name: "硬件部",
        parent_department_id: null,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      },
    ]);
    api.requestDelegations.mockResolvedValue([
      {
        id: "deleg-active",
        principal_user_id: "user-a",
        delegate_user_id: "user-b",
        starts_at: hourFromNow(-1),
        ends_at: hourFromNow(48),
        reason: "年假代班",
        created_by_user_id: "user-owner",
        revoked_at: null,
        revoked_by_user_id: null,
        created_at: hourFromNow(-2),
      },
      {
        id: "deleg-future",
        principal_user_id: "user-b",
        delegate_user_id: "user-a",
        starts_at: hourFromNow(48),
        ends_at: hourFromNow(96),
        reason: "下周出差",
        created_by_user_id: "user-owner",
        revoked_at: null,
        revoked_by_user_id: null,
        created_at: hourFromNow(-1),
      },
    ]);

    render(<OrganizationGovernance />);
    await waitFor(() => expect(screen.getByText("组织、代理与交接")).toBeInTheDocument());

    // The department name also appears as a <select> option, hence getAllByText.
    expect(screen.getAllByText("硬件部").length).toBeGreaterThan(0);
    expect(screen.getByText("生效中")).toBeInTheDocument();
    expect(screen.getByText("未开始")).toBeInTheDocument();
    expect(screen.getByText("李工 → 王工")).toBeInTheDocument();
    // A scheduled delegation is still revocable, an active one too.
    expect(screen.getAllByRole("button", { name: "撤销" })).toHaveLength(2);
  });

  it.each([0, 1])("confirms the preview before handover and preserves %i manual responsibilities", async (manualCount) => {
    bootstrapReady();
    api.requestDepartments.mockResolvedValue([]);
    api.requestDelegations.mockResolvedValue([]);
    api.previewHandover.mockResolvedValue({
      from_user_id: "user-a",
      to_user_id: "user-b",
      basis_digest: "a".repeat(64),
      transfer_count: 3,
      manual_count: manualCount,
      delegations_to_revoke: 1,
      project_access_count: 1,
      groups: [
        { key: "issue_owner", label: "问题负责人", count: 2, can_transfer: true, reasons: [], items: [] },
        { key: "issue_verifier", label: "问题验证人", count: 1, can_transfer: true, reasons: [], items: [] },
        ...(manualCount ? [{ key: "gate_signer", label: "固定轮次签核", count: 1, can_transfer: false, reasons: ["须从原签核流程处理"], items: [] }] : []),
      ],
    });
    api.handOver.mockResolvedValue({
      from_user_id: "user-a",
      to_user_id: "user-b",
      transferred_counts: {
        issue_owner: 2,
        issue_verifier: 1,
        task_assignee: 0,
        delegations_revoked: 1,
      },
      deactivated: manualCount === 0,
    });
    const user = userEvent.setup();

    render(<OrganizationGovernance />);
    await waitFor(() => expect(screen.getByText("离职交接")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("离职成员"), "user-a");
    await user.selectOptions(screen.getByLabelText("接手成员"), "user-b");
    await user.click(screen.getByRole("button", { name: "准备交接" }));

    const dialog = await screen.findByRole("dialog", { name: "交接确认" });
    expect(api.previewHandover).toHaveBeenCalledWith({ from_user_id: "user-a", to_user_id: "user-b" });
    expect(dialog).toHaveTextContent("3 项可办理责任");
    const deactivate = within(dialog).getByRole("checkbox", { name: /本次移交后停用原账号/ });
    if (manualCount) {
      expect(deactivate).toBeDisabled();
      expect(deactivate).not.toBeChecked();
      expect(dialog).toHaveTextContent("1 项须在原流程处理");
    } else {
      expect(deactivate).toBeEnabled();
      expect(deactivate).toBeChecked();
    }
    expect(within(dialog).getByText("李工")).toBeInTheDocument();
    expect(api.handOver).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "确认交接" }));
    await waitFor(() =>
      expect(api.handOver).toHaveBeenCalledWith({
        from_user_id: "user-a",
        to_user_id: "user-b",
        deactivate_source: manualCount === 0,
        expected_digest: "a".repeat(64),
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "本批已办理：问题负责人 2、问题验证人 1、撤销的代理 1",
      ),
    );
    expect(screen.getByRole("status")).toHaveTextContent(manualCount ? "原账号保留，未转移责任请继续从原流程办理" : "原账号已停用");
  });

  it("surfaces a rejected reporting cycle instead of failing silently", async () => {
    bootstrapReady();
    api.requestDepartments.mockResolvedValue([]);
    api.requestDelegations.mockResolvedValue([]);
    api.setPlacement.mockRejectedValue(new Error("Reporting line would form a cycle"));
    const user = userEvent.setup();

    render(<OrganizationGovernance />);
    await waitFor(() => expect(screen.getByText("部门与汇报线")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("成员"), "user-a");
    await user.selectOptions(screen.getByLabelText("汇报给"), "user-b");
    await user.click(screen.getByRole("button", { name: "保存归属" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Reporting line would form a cycle"),
    );
  });

  it("locks non-admin roles out without loading org data", async () => {
    userApi.requestUserManagementBootstrap.mockResolvedValue({ kind: "forbidden", identity });
    render(<OrganizationGovernance />);
    await waitFor(() => expect(screen.getByText("仅管理员可管理组织")).toBeInTheDocument());
    expect(api.requestDepartments).not.toHaveBeenCalled();
    expect(api.requestDelegations).not.toHaveBeenCalled();
  });
});
