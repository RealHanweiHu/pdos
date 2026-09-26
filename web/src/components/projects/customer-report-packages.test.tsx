import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CustomerReportPackages } from "./customer-report-packages";
const routing = vi.hoisted(() => ({ id: "report-1" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams({customer_report:routing.id}) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("opens a requested report and removes its old body when a new location cannot be read", async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body));
    if (String(input).endsWith("/options")) return new Response(JSON.stringify({customers:[],replies:[],nodes:[]}));
    if (body.package_id === "missing") return new Response(JSON.stringify({detail:{message:"原报告不可读取"}}),{status:403});
    return new Response(JSON.stringify({record:{id:"report-1",created_by_user_id:"owner",snapshot:{projection:{template_version:"customer-audit-evidence.v1",title:"固定客户内容",customer_name:"模拟客户",audit_clauses:[{standard:"模拟条款",edition:"v1",clause:"1",applicability:"unconfirmed",gap:"待补",signature_summaries:[{type:"Gate",reference:"G-1",status:"hold",round:1,signoffs:[{specialty:"quality",status:"rejected",signed_at:null,note:"不得显示内部意见"}]}]}]}}},current_user_id:"owner",decisions:[],files:[],sources_current:true}));
  });
  vi.stubGlobal("fetch",fetcher);routing.id="report-1";
  const view = render(<CustomerReportPackages projectId="project" />);
  expect(await screen.findByText("固定客户内容")).toBeVisible();
  expect(screen.getByText("原状态：暂缓")).toBeVisible();
  expect(screen.queryByText("不得显示内部意见")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"核准客户可见内容"})).toBeDisabled();
  routing.id="missing";view.rerender(<CustomerReportPackages projectId="project" />);
  await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("原报告不可读取"));
  expect(screen.queryByText("固定客户内容")).not.toBeInTheDocument();
});
