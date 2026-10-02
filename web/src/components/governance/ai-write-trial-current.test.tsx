import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiWriteTrialCurrent } from "./ai-write-trial-current";

const projects = [{ id: "one", code: "P1", name: "泵项目" }, { id: "two", code: "P2", name: "电机项目" }];
function check(state = "current", project = "one") {
  return { projects, selected_project_id: project, check: { state, checked_at: "2026-09-27T10:00:00Z", protocol_id: "later", qualification_granted: false, reasons: state === "current" ? [] : [{ code: "later_withdrawal", message: "原稿后续撤回，当前材料不再达标。" }], fresh_check: { raw_total: 20, verified_total: 20, unverified_total: 0 } } };
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("current trial material checks", () => {
  it("checks on demand and replaces an old success with current withdrawal reasons", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(check())).mockResolvedValueOnce(Response.json(check("blocked")));
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrialCurrent protocolId="original" />);
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "核对当前材料" }));
    expect(await screen.findByText(/当前材料满足候选条件/)).toBeVisible();
    expect(screen.getByText(/已采用同项目、同模型版本的后续试运行材料/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "核对当前材料" }));
    expect(screen.queryByText(/当前材料满足候选条件/)).not.toBeInTheDocument();
    expect(await screen.findByText(/原稿后续撤回/)).toBeVisible();
    expect(fetcher.mock.calls[1][0]).toContain("?project_id=one");
    expect(fetcher.mock.calls.every(([, init]) => !init?.method && init?.cache === "no-store")).toBe(true);
  });
  it("uses actual project choices and clears private material on permission loss", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(check())).mockResolvedValueOnce(new Response(null, { status: 403 }));
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrialCurrent protocolId="original" />);
    fireEvent.click(screen.getByRole("button", { name: "核对当前材料" }));
    await screen.findByRole("combobox", { name: "核对项目" });
    fireEvent.change(screen.getByRole("combobox", { name: "核对项目" }), { target: { value: "two" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("无权");
    expect(fetcher.mock.calls[1][0]).toContain("?project_id=two");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(/当前材料满足候选条件/)).not.toBeInTheDocument();
  });
  it("rejects malformed authority claims and ignores responses from an unmounted scope", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; })).mockResolvedValueOnce(Response.json({ ...check(), check: { ...check().check, qualification_granted: true } }));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<AiWriteTrialCurrent key="old" protocolId="old" />);
    fireEvent.click(screen.getByRole("button", { name: "核对当前材料" }));
    view.rerender(<AiWriteTrialCurrent key="new" protocolId="new" />);
    resolve(Response.json(check()));
    await waitFor(() => expect(screen.queryByText(/当前材料满足候选条件/)).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "核对当前材料" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("结果不完整");
  });
});
