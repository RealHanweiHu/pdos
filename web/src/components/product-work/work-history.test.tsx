import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { WorkHistory } from "./work-history";
const ref = { tenant_id: "tenant", kind: "evidence_snapshot", ref_id: "snapshot", as_of: "2026-09-21T10:00:00Z", digest: "original-digest" };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("retains the returned submission and verifies its original source before showing content", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response({current_version:4, next_before_id:8, items:[{id:9,event_id:"event",action:"return",timestamp:ref.as_of,actor_user_id:"receiver",actor_display_name:"接收人",before:{version:3,state:"submitted",result_note:"第一次提交",evidence:[ref]},after:{version:4,state:"in_progress",result_note:"补充边界",evidence:[]}}]}))
    .mockResolvedValueOnce(response({snapshot_id:"snapshot",content_digest:"changed",content:"不得显示的正文"}))
    .mockResolvedValueOnce(response({snapshot_id:"snapshot",content_digest:ref.digest,content:"原版模拟依据",taint:"untrusted"}))
    .mockResolvedValueOnce(response({current_version:4,next_before_id:null,items:[]}))
    .mockResolvedValueOnce(response({detail:{message:"权限已变化"}},403));
  vi.stubGlobal("fetch",fetcher);
  render(<WorkHistory base="spaces/space" workId="work" version={4} evidence={[]} />);
  expect(fetcher).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"查看办理历史"}));
  expect(await screen.findByText("本次记录：补充边界")).toBeInTheDocument();
  await userEvent.click(screen.getByText("办理前的结果与依据"));
  expect(screen.getByText("第一次提交")).toBeVisible();
  await userEvent.click(screen.getByRole("button",{name:"查看此版原文"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("原依据摘要不匹配");
  expect(screen.queryByText("不得显示的正文")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"查看此版原文"}));
  expect(await screen.findByText("原版模拟依据")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"继续读取更早办理"}));
  expect(fetcher).toHaveBeenLastCalledWith("/api/product-work/spaces/space/work-items/work/history?before_id=8",expect.any(Object));
  expect(screen.queryByRole("button",{name:"继续读取更早办理"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"刷新办理历史"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("权限已变化");
  expect(screen.queryByText("第一次提交")).not.toBeInTheDocument();
  expect(screen.queryByText("原版模拟依据")).not.toBeInTheDocument();
});
