import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { XiaopaiIdentity, XiaopaiProvider } from "./xiaopai-provider";

const a = "10000000-0000-4000-8000-000000000001", b = "10000000-0000-4000-8000-000000000002";
const route = vi.hoisted(() => ({ path: "/projects", query: "project=10000000-0000-4000-8000-000000000001", push: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => route.path, useSearchParams: () => new URLSearchParams(route.query), useRouter: () => ({ push: route.push }) }));
vi.mock("@/components/projects/project-api", () => ({ requestProjectList: async () => [{ id: a, name: "项目A" }, { id: b, name: "项目B" }] }));
vi.mock("./project-conversation", () => ({ ProjectConversation: ({ projectId }: { projectId: string }) => { const [value, setValue] = useState(""); return <textarea aria-label={`draft-${projectId}`} value={value} onChange={e => setValue(e.target.value)}/>; } }));
vi.mock("./xiaopai-followup", () => ({ XiaopaiFollowup: () => <p>持续跟进</p> }));
const identity = { tenant: { id: "tenant", name: "测试" }, user: { id: "user", role: "engineer" } } as WorkspaceIdentity;
function App({ user = identity }: { user?: WorkspaceIdentity }) { return <XiaopaiProvider><XiaopaiIdentity identity={user}/></XiaopaiProvider>; }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); route.path = "/projects"; route.query = `project=${a}`; route.push.mockClear(); });
describe("小Pai跨入口连续性", () => {
  it("automatically follows project B and preserves project A's unsent draft across collapse and expansion", async () => {
    const view = render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "打开小Pai" }));
    const draft = await screen.findByLabelText(`draft-${a}`);
    fireEvent.change(draft, { target: { value: "A中尚未提交的内容" } });
    route.query = `project=${b}`;
    view.rerender(<App/>);
    await waitFor(() => expect(screen.getByText("项目B")).toBeVisible());
    expect(screen.queryByRole("combobox", { name: "小Pai当前项目" })).not.toBeInTheDocument();
    expect(draft).toHaveValue("A中尚未提交的内容");
    fireEvent.click(screen.getByRole("button", { name: "收起小Pai" }));
    fireEvent.click(screen.getByRole("button", { name: "打开小Pai" }));
    route.path = "/ask";
    view.rerender(<App/>);
    expect(draft).toHaveValue("A中尚未提交的内容");
    expect(screen.queryByRole("button", { name: "打开小Pai" })).not.toBeInTheDocument();
  });
  it("opens from a non-project page without a project picker, never keeps the old project active, and carries its origin into the full page", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url, options) => options?.method === "POST" ? Response.json({ detail: { message: "保存回执尚未确认" } }, { status: 503 }) : Response.json({ items: [] })));
    const view = render(<App/>);
    fireEvent.click(await screen.findByRole("button", { name: "打开小Pai" }));
    await screen.findByLabelText(`draft-${a}`);
    route.path = "/product-work";
    route.query = "space=20000000-0000-4000-8000-000000000001&line=30000000-0000-4000-8000-000000000001";
    view.rerender(<App/>);
    expect(await screen.findByLabelText("给小Pai的消息")).toBeVisible();
    expect(screen.getByLabelText(`draft-${a}`)).not.toBeVisible();
    expect(screen.queryByRole("combobox", { name: "小Pai当前项目" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("给小Pai的消息")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "帮我看这个市场空间" } });
    fireEvent.click(screen.getByRole("button", { name: "展开小Pai完整页面" }));
    const destination = route.push.mock.calls.at(-1)?.[0] as string;
    expect(new URL(destination, "https://pdos.invalid").searchParams.get("source")).toBe(`/product-work?${route.query}`);
    route.path = "/ask";
    route.query = destination.split("?")[1];
    view.rerender(<App/>);
    expect(screen.getByLabelText("给小Pai的消息")).toHaveValue("帮我看这个市场空间");
    expect(screen.getByText("产品工作", { exact: true })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("保存回执尚未确认");
  });
  it("restores a full-page source link after a refresh without selecting another project", async () => {
    route.path = "/ask";
    route.query = new URLSearchParams({ source: `/projects?project=${b}&task=30000000-0000-4000-8000-000000000001` }).toString();
    render(<App/>);
    expect(await screen.findByLabelText(`draft-${b}`)).toBeVisible();
    expect(screen.getByText("项目B")).toBeVisible();
    expect(screen.queryByLabelText(`draft-${a}`)).not.toBeInTheDocument();
  });
  it("does not expose the internal conversation surface to external roles or on login", async () => {
    const view = render(<App user={{ ...identity, user: { ...identity.user, role: "customer" } }}/>);
    expect(screen.queryByRole("button", { name: "打开小Pai" })).not.toBeInTheDocument();
    route.path = "/login";
    view.rerender(<App/>);
    expect(screen.queryByRole("button", { name: "打开小Pai" })).not.toBeInTheDocument();
  });
});
