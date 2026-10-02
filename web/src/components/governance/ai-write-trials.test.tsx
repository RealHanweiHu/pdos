import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiWriteTrials } from "./ai-write-trials";

const base = "/api/ai/governance/write-policy/trials";
const first = "11111111-1111-4111-8111-111111111111";
const second = "22222222-2222-4222-8222-222222222222";
function protocol(id = first, end = "2020-09-02T00:00:00Z") {
  return { id, project_ids: ["project"], binding: { operation_key: "meeting.minutes.draft" }, evidence_kind: "synthetic", window_start: "2020-09-01T00:00:00Z", window_end: end, created_at: "2020-08-31T00:00:00Z", reason: id === first ? "首批固定观察" : "第二批固定观察", configuration: { minimum_handled_drafts: 20, minimum_followup_seconds: 3600, minimum_confirmation_basis_points: 9000, maximum_retraction_basis_points: 500, confirmation_basis: "retained_original" } };
}
function receipt(id = "receipt-1") {
  return { id, as_of: "2020-09-03T00:00:00Z", current_policy_matches: true, collection: { raw_total: 8, verified_total: 6, unverified_total: 2, raw_counts: { confirmed: 5, edited: 1, withdrawn: 2, pending: 1 }, blockers: [{ reasons: ["provider_call_unverified"] }] }, qualification: { reasons: ["evaluation_missing", "minimum_handled_drafts_not_met", "trial_not_real_evidence"], qualification_granted: false } };
}
function page(items: unknown[], next: string | null = null) { return { items, next_before_id: next }; }
function open() { fireEvent.click(screen.getAllByRole("button", { name: "查看采集回执" })[0]); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("fixed AI write trials", () => {
  it("paginates registrations and original receipts with readable counts and reasons", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
      if (url === base) return Response.json(page([protocol()], first));
      if (url === `${base}?before_id=${first}`) return Response.json(page([protocol(second)]));
      if (url === `${base}/${first}/receipts`) return Response.json(page([receipt()], "receipt-1"));
      if (url === `${base}/${first}/receipts?before_id=receipt-1`) return Response.json(page([receipt("receipt-2")]));
      throw new Error(`unexpected URL ${url}`);
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrials canManage={false} />);
    await screen.findByText("首批固定观察");
    expect(screen.getByText(/模拟场景 · 1 个项目/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "更多试运行登记" }));
    expect(await screen.findByText("第二批固定观察")).toBeVisible();
    open();
    expect(await screen.findByText("· 尚未接入独立真实模型评测")).toBeVisible();
    expect(screen.getByText("· 模型调用来源尚未核实")).toBeVisible();
    expect(screen.getByText("未核实").nextSibling).toHaveTextContent("2");
    expect(screen.queryByRole("button", { name: "采集当前记录" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "更多采集回执" }));
    await waitFor(() => expect(screen.getAllByText("范围内原稿")).toHaveLength(2));
    expect(screen.queryByText("evaluation_missing")).not.toBeInTheDocument();
  });

  it("reuses the request after a lost collection response and refreshes original history", async () => {
    let posts = 0, collected = false;
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
      if (url === base) return Response.json(page([protocol()]));
      if (init?.method === "POST") {
        if (++posts === 1) throw new TypeError("network down");
        collected = true;
        return Response.json({ receipt: receipt(), replayed: true });
      }
      return Response.json(page(collected ? [receipt()] : []));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrials canManage />);
    await screen.findByText("首批固定观察"); open();
    await screen.findByText(/尚无采集回执/);
    fireEvent.click(screen.getByRole("button", { name: "采集当前记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("沿用原请求");
    fireEvent.click(screen.getByRole("button", { name: "重试采集当前记录" }));
    expect(await screen.findByText("范围内原稿")).toBeVisible();
    expect(screen.getByText(/本次采集已保存/)).toBeVisible();
    const writes = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(writes).toHaveLength(2);
    expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
    expect(JSON.parse(String(writes[0][1]?.body))).toEqual({ request_id: expect.any(String) });
  });

  it("disables collection until the registered observation window ends", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => Response.json(url === base ? page([protocol(first, "2999-09-02T00:00:00Z")]) : page([])));
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrials canManage />);
    await screen.findByText("首批固定观察"); open();
    await screen.findByText(/尚无采集回执/);
    expect(screen.getByRole("button", { name: "采集当前记录" })).toBeDisabled();
    expect(screen.getByText(/观察窗口尚未结束/)).toBeVisible();
    expect(fetcher.mock.calls.every(([, init]) => init?.method === "GET")).toBe(true);
  });

  it("ignores late receipts after switching to another registration", async () => {
    let resolveOld!: (value: Response) => void;
    const deferred = new Promise<Response>(resolve => { resolveOld = resolve; });
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
      if (url === base) return Response.json(page([protocol(), protocol(second)]));
      return url === `${base}/${first}/receipts` ? deferred : Response.json(page([]));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrials canManage />);
    await screen.findByText("首批固定观察"); open();
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(`${base}/${first}/receipts`, expect.anything()));
    open();
    await screen.findByText(/尚无采集回执/);
    await act(async () => { resolveOld(Response.json(page([receipt()]))); await deferred; });
    expect(screen.queryByText("范围内原稿")).not.toBeInTheDocument();
    expect(screen.getByText(/尚无采集回执/)).toBeVisible();
  });

  it("opens registration preparation from empty history without inventing candidates", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation(async url => Response.json(
      url === base ? page([]) : { as_of: new Date().toISOString(), candidates: [], projects: [], policy_revision: 1, blockers: ["尚无受信的独立评测"] }
    )));
    render(<AiWriteTrials canManage />);
    expect(await screen.findByText(/尚无已登记的固定试运行/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "登记试运行" }));
    expect(await screen.findByText(/尚无受信的独立评测/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "登记本次试运行" })).not.toBeInTheDocument();
    expect(screen.getByText(/采集不授予自动写入资格/)).toBeVisible();
  });
});
