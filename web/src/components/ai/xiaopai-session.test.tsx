import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { consumeReplyStream, XiaopaiSession } from "./xiaopai-session";

const cid = "20000000-0000-4000-8000-000000000001", mid = "20000000-0000-4000-8000-000000000002";
const row = { id: cid, scope_kind: "personal", visibility: "private", context_version: 1, archived_at: null };
const ready = vi.fn(), pending = vi.fn(), denied = vi.fn();
function app() { return <XiaopaiSession scope={{ scope_kind: "personal" }} identityKey="test:user" onConversationReady={ready} onPendingChange={pending} onAuthorityLost={denied} renderTools={() => <p>专业资料入口</p>}/>; }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); ready.mockClear(); pending.mockClear(); denied.mockClear(); });
it("shows search progress and retains read activity and citations", async () => {
  const fetcher = setup(); render(app()); await screen.findByText("有什么想一起处理？");
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  fetcher.mockImplementation(async (url, init) => {
    if (String(url).endsWith("/messages")) return Response.json({ id: mid, sequence: 1, ...JSON.parse(String(init?.body)) });
    return new Response(new ReadableStream({ start(value) { controller = value; } }), { headers: { "Content-Type": "text/event-stream" } });
  });
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "帮我搜索气泵规格" } });
  fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  await waitFor(() => expect(controller).toBeDefined());
  controller.enqueue(new TextEncoder().encode(event({ type: "status", message: "正在搜索：气泵规格", run_id: "original-run" })));
  expect(await screen.findByText("正在搜索：气泵规格")).toBeVisible();
  expect(screen.getByRole("button", { name: "停止小Pai回复" })).toBeEnabled();
  controller.enqueue(new TextEncoder().encode(event({ type: "result", reply: {
    status: "answered", answer: "规格注明峰值压力120kPa。",
    citations: [{ reference_id: "snapshot:1", label: "公开规格", href: "https://example.com/spec" }],
    research: { remaining: 0, observations: [{ tool: "search", target: "气泵规格", status: "completed" }, { tool: "read", target: "https://example.com/spec", status: "completed" }] },
  } }) + event({ type: "done" }))); controller.close();
  expect(await screen.findByText("规格注明峰值压力120kPa。")).toBeVisible();
  fireEvent.click(screen.getByText("已检索资料 · 搜索 1 次 · 线索 0 条 · 读取 1 份"));
  expect(screen.getByText("搜索：气泵规格 · 已完成")).toBeVisible();
  fireEvent.click(screen.getByText("参考资料 · 1"));
  expect(screen.getByRole("link", { name: "公开规格" })).toHaveAttribute("href", "https://example.com/spec");
});
it.each([
  ["APPLICATION_RESEARCH_BUDGET_REQUIRED", "自动研究尚未启用：本地运行计量与预算配置未完成。消息已保存，可以继续讨论需求。"],
  ["BUDGET_TENANT_CALL_BUSY", "当前回复名额已占满，有正在处理或等待用量核对的请求。你的消息已保存，需要先完成或核对已有请求。"],
  ["BUDGET_LINEAGE_CALL_BUSY", "这次研究还有未完成或待核对用量的调用，暂时无法继续。你的消息已保存，请先核对原请求。"],
])("shows the saved %s failure and leaves conversation usable", async (error_code, reason) => {
  const fetcher = setup(); render(app()); await screen.findByText("有什么想一起处理？");
  const defaultFetch = fetcher.getMockImplementation()!;
  const reply = { status: "unavailable", answer: null, error_code, citations: [] };
  fetcher.mockImplementation(async (url, init) => {
    if (String(url).endsWith("/reply")) return init?.method === "POST"
      ? new Response(event({ type: "result", reply }) + event({ type: "done" }), { headers: { "Content-Type": "text/event-stream" } })
      : Response.json({ reply });
    return defaultFetch(url, init);
  });
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "研究欧美桨板泵" } });
  fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  expect(await screen.findByText(reason)).toBeVisible();
  expect(screen.getByText("研究欧美桨板泵")).toBeVisible();
  expect(screen.queryByRole("button", { name: "继续原请求" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("小Pai正在回复")).not.toBeInTheDocument();
  expect(pending).toHaveBeenLastCalledWith(false);
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "先澄清使用场景" } });
  expect(screen.getByRole("button", { name: "发送给小Pai" })).toBeEnabled();
  cleanup(); render(app());
  expect(await screen.findByText(reason)).toBeVisible();
  expect(screen.queryByRole("button", { name: "继续原请求" })).not.toBeInTheDocument();
});
function event(value: object) { return `data: ${JSON.stringify(value)}\n\n`; }
function setup() {
  const messages: object[] = [];
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    if (path.endsWith("/reply") && init?.method !== "POST") return Response.json({ reply: null });
    if (path.endsWith("/reply") && init?.method === "POST") return new Response(event({ type: "result", reply: { status: "answered", answer: "我们接着聊。", citations: [] } }) + event({ type: "done" }), { headers: { "Content-Type": "text/event-stream" } });
    if (path.endsWith("/messages")) { const body = JSON.parse(String(init?.body)); const message = { ...body, id: messages.length ? crypto.randomUUID() : mid, sequence: messages.length + 1 }; messages.push(message); return Response.json(message); }
    if (path === "/api/conversations" && init?.method === "POST") return Response.json(row);
    if (path.includes("?")) return Response.json({ items: [row] });
    return Response.json({ conversation: row, items: messages });
  });
  vi.stubGlobal("fetch", fetcher); return fetcher;
}
it("shows provider text before the reply completes, then continues in the same conversation", async () => {
  const fetcher = setup(); let controller!: ReadableStreamDefaultController<Uint8Array>;
  render(app()); await waitFor(() => expect(screen.getByRole("button", { name: "发送给小Pai" })).toBeDisabled());
  await screen.findByText("有什么想一起处理？");
  fetcher.mockReset(); let number = 0;
  fetcher.mockImplementation(async (url, init) => {
    if (String(url).endsWith("/messages")) return Response.json({ id: number++ ? "second" : mid, sequence: number, ...JSON.parse(String(init?.body)) });
    if (number === 1) return new Response(new ReadableStream({ start(value) { controller = value; } }), { headers: { "Content-Type": "text/event-stream" } });
    return new Response(event({ type: "result", reply: { status: "answered", answer: "第二轮也接上了", citations: [] } }) + event({ type: "done" }), { headers: { "Content-Type": "text/event-stream" } });
  });
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "你好，陪我想想" } });
  fireEvent.keyDown(screen.getByLabelText("给小Pai的消息"), { key: "Enter" });
  await waitFor(() => expect(controller).toBeDefined());
  expect(screen.getByRole("button", { name: "停止小Pai回复" })).toBeDisabled();
  controller.enqueue(new TextEncoder().encode(event({ type: "status", message: "正在回复", run_id: "original-run" }) + event({ type: "text", text: "你好，可以一起想。", provisional: true })));
  expect(await screen.findByText("你好，可以一起想。")).toBeVisible();
  expect(screen.getByText("你好，陪我想想")).toBeVisible();
  expect(screen.getByRole("button", { name: "停止小Pai回复" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "继续刚才的思路" } });
  controller.enqueue(new TextEncoder().encode(event({ type: "result", reply: { status: "answered", answer: "你好，可以一起想。", citations: [] } }) + event({ type: "done" }))); controller.close();
  await waitFor(() => expect(screen.queryByRole("button", { name: "停止小Pai回复" })).not.toBeInTheDocument());
  expect(screen.getByLabelText("给小Pai的消息")).toHaveValue("继续刚才的思路");
  fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  expect(await screen.findByText("第二轮也接上了")).toBeVisible();
  const saves = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/messages"));
  expect(saves.every(([url, init]) => url === `/api/conversations/${cid}/messages` && JSON.parse(String(init?.body)).reply_only === true)).toBe(true);
});
it("opens the existing attachment workflow before the first message", async () => {
  const fetcher = setup();
  fetcher.mockImplementation(async (url, init) => {
    if (String(url).includes("?")) return Response.json({ items: [] });
    if (String(url) === "/api/conversations" && init?.method === "POST") return Response.json(row);
    throw new Error("Unexpected request");
  });
  render(app()); await screen.findByText("有什么想一起处理？");
  fireEvent.click(screen.getByRole("button", { name: "资料与办理" }));
  expect(await screen.findByText("专业资料入口")).toBeVisible();
  expect(ready).toHaveBeenCalledWith(cid);
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/messages"))).toBe(false);
});
it("keeps a newly created conversation in history when starting the next one", async () => {
  const fetcher = setup(); fetcher.mockResolvedValueOnce(Response.json({ items: [] }));
  render(app()); await screen.findByText("有什么想一起处理？");
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "第一轮问题" } });
  fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  await screen.findByText("我们接着聊。");
  fireEvent.click(screen.getByRole("button", { name: "新建小Pai会话" }));
  expect(screen.queryByText("第一轮问题")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "历史会话" }), { target: { value: cid } });
  expect(await screen.findByText("第一轮问题")).toBeVisible();
});
it("reuses the exact original request after an uncertain message save", async () => {
  const fetcher = setup(); render(app()); await screen.findByText("有什么想一起处理？");
  fetcher.mockResolvedValueOnce(Response.json({ detail: { message: "回执未知" } }, { status: 503 }));
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "接着讨论" } }); fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  await screen.findByText("回执未知"); const first = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
  fireEvent.click(screen.getByRole("button", { name: "继续原请求" })); await screen.findByText("我们接着聊。");
  const saves = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/messages")); expect(saves[1][1]?.body).toBe(first[1]?.body);
});
it("hides private output after authority is lost", async () => {
  const fetcher = setup(); render(app()); await screen.findByText("有什么想一起处理？");
  fetcher.mockResolvedValueOnce(Response.json({ detail: { message: "范围已撤回" } }, { status: 403 }));
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "私人内容" } }); fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  await screen.findByText("范围已撤回"); expect(screen.queryByText("私人内容")).not.toBeInTheDocument(); expect(denied).toHaveBeenCalled(); expect(sessionStorage.length).toBe(0);
});
it("decodes split UTF-8 SSE frames and detects a truncated connection", async () => {
  const encoded = new TextEncoder().encode(event({ type: "text", text: "中文" }) + event({ type: "done" })); const got: object[] = [];
  const response = new Response(new ReadableStream({ start(c) { for (const byte of encoded) c.enqueue(new Uint8Array([byte])); c.close(); } }), { headers: { "Content-Type": "text/event-stream" } });
  await consumeReplyStream(response, value => got.push(value)); expect(got[0]).toEqual({ type: "text", text: "中文" });
  await expect(consumeReplyStream(new Response(event({ type: "text", text: "半条回复" }), { headers: { "Content-Type": "text/event-stream" } }), () => {})).rejects.toThrow("连接中断");
  await expect(consumeReplyStream(new Response("Internal Server Error", { status: 500 }), () => {})).rejects.toThrow("回复暂不可用，请查询原请求");
});

it("category launch starts a fresh intake and keeps the goal on clarification answers", async () => {
  const fetcher=setup();
  render(<XiaopaiSession preprojectGoal="category" scope={{scope_kind:"personal"}} identityKey="test:user" onConversationReady={ready} onPendingChange={pending} onAuthorityLost={denied} renderTools={()=>null}/>);
  await screen.findByText("一起建立一个品类");
  expect(fetcher.mock.calls.some(([url])=>String(url)===`/api/conversations/${cid}`)).toBe(false);
  const defaultFetch=fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async(url, init)=>{
    if(String(url).endsWith("/reply")&&init?.method==="POST")return new Response(event({type:"result",reply:{status:"answered",answer:"先确认市场",preproject:{goal:"category",stage:"clarify",candidate_digest:"a".repeat(64),category:null,proposal:null,questions:[{id:"region",question:"目标地区？",options:["EU","US"],recommendation:"EU"}]}}})+event({type:"done"}),{headers:{"Content-Type":"text/event-stream"}});
    return defaultFetch(url,init);
  });
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), {target:{value:"研究桨板泵"}});
  fireEvent.click(screen.getByRole("button",{name:"发送给小Pai"}));
  await screen.findByRole("dialog");
  await waitFor(()=>expect(screen.getByRole("button",{name:"回答并继续"})).toBeEnabled());
  fireEvent.click(screen.getByRole("radio",{name:"EU"}));fireEvent.click(screen.getByRole("button",{name:"回答并继续"}));
  await waitFor(()=>expect(fetcher.mock.calls.filter(([url])=>String(url).endsWith("/messages"))).toHaveLength(2));
  const calls=fetcher.mock.calls.filter(([url])=>String(url).endsWith("/messages"));
  expect(JSON.parse(String(calls[0][1]?.body)).preproject_goal).toBe("category");
  expect(JSON.parse(String(calls[1][1]?.body))).toMatchObject({body:"region：EU",preproject_goal:"category"});
});

it("streams a public approach before the answer and restores the completed process after reload", async () => {
  const fetcher = setup(); render(app()); await screen.findByText("有什么想一起处理？");
  const normal = fetcher.getMockImplementation()!;
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  let saved: object | null = null;
  fetcher.mockImplementation(async (url, init) => {
    if (String(url).endsWith("/reply")) return init?.method === "POST"
      ? new Response(new ReadableStream({ start(value) { controller = value; } }), { headers: { "Content-Type": "text/event-stream" } })
      : Response.json({ reply: saved });
    return normal(url, init);
  });
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "比较两款气泵" } });
  fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  await waitFor(() => expect(controller).toBeDefined());
  const steps = [{ key: "understand", label: "正在思考", detail: "先核对压力和供电条件，再比较使用场景。", state: "running", at_ms: 0 }];
  controller.enqueue(new TextEncoder().encode(event({ type: "status", message: "正在思考", run_id: "run", process: { state: "running", elapsed_ms: 1300, steps } })));
  expect(await screen.findByText(steps[0].detail)).toBeVisible();
  expect(screen.getByText("进行中 · 1 秒")).toBeVisible();
  expect(screen.queryByText("比较结果如下。")).not.toBeInTheDocument();
  const process = { state: "completed", elapsed_ms: 3200, steps: [{ ...steps[0], state: "completed" }] };
  saved = { status: "answered", answer: "比较结果如下。", process };
  controller.enqueue(new TextEncoder().encode(event({ type: "result", reply: saved }) + event({ type: "done" }))); controller.close();
  expect(await screen.findByText("比较结果如下。")).toBeVisible();
  fireEvent.click(screen.getByText("思考与处理过程"));
  expect(screen.getByText(steps[0].detail)).toBeVisible();
  cleanup(); render(app());
  await screen.findByText("比较结果如下。");
  expect(screen.getByText("已完成 · 3 秒")).toBeVisible();
  fireEvent.click(screen.getByText("思考与处理过程"));
  expect(screen.getByText(steps[0].detail)).toBeVisible();
});

it("clears streamed process details when authorization is withdrawn", async () => {
  const fetcher = setup(); render(app()); await screen.findByText("有什么想一起处理？");
  const normal = fetcher.getMockImplementation()!;
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  fetcher.mockImplementation(async (url, init) => String(url).endsWith("/reply") && init?.method === "POST"
    ? new Response(new ReadableStream({ start(value) { controller = value; } }), { headers: { "Content-Type": "text/event-stream" } })
    : normal(url, init));
  fireEvent.change(screen.getByLabelText("给小Pai的消息"), { target: { value: "核对当前资料" } });
  fireEvent.click(screen.getByRole("button", { name: "发送给小Pai" }));
  await waitFor(() => expect(controller).toBeDefined());
  controller.enqueue(new TextEncoder().encode(event({ type: "status", message: "正在思考", run_id: "run", process: { state: "running", elapsed_ms: 0, steps: [{ key: "understand", label: "正在思考", detail: "本轮受限资料摘要", state: "running", at_ms: 0 }] } })));
  expect(await screen.findByText("本轮受限资料摘要")).toBeVisible();
  controller.enqueue(new TextEncoder().encode(event({ type: "error", status: 403, message: "范围已撤回" })));
  controller.close();
  await screen.findByText("范围已撤回");
  expect(screen.queryByText("本轮受限资料摘要")).not.toBeInTheDocument();
  expect(screen.queryByText("思考与处理过程")).not.toBeInTheDocument();
});
