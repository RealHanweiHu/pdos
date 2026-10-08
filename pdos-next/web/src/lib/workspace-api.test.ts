import test from "node:test";
import assert from "node:assert/strict";
import { createWorkspaceApi, WorkspaceReadError, type WorkspaceTransport } from "./workspace-api";

function harness() {
  const calls: { path: string; body: unknown; resolve: (value: unknown) => void; reject: (error: unknown) => void }[] = [];
  const transport: WorkspaceTransport = <T>(path: string, body?: unknown) => new Promise<T>((resolve, reject) => calls.push({ path, body, resolve: value => resolve(value as T), reject }));
  return { calls, transport };
}
const turn = () => new Promise<void>(resolve => setImmediate(resolve));
function failed(promise: Promise<unknown>) { return promise.then(() => null, error => error); }

test("八面板重复读取仅共享在途GET，完成后立即重新读取不保留旧结果", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product");
  const a = client.api("workspace"), copies = Array.from({ length: 7 }, () => client.api("workspace")), b = client.api("builds"), other = Array.from({ length: 7 }, () => client.api("builds"));
  assert.ok(copies.every(value => value === a)); assert.ok(other.every(value => value === b)); await turn(); assert.equal(h.calls.length, 2);
  h.calls[0].resolve({ version: 1 }); h.calls[1].resolve({ items: [] }); await a; await b;
  const fresh = client.api("workspace"); assert.notEqual(fresh, a); await turn(); assert.equal(h.calls.length, 3); h.calls[2].resolve({ version: 2 }); assert.deepEqual(await fresh, { version: 2 });
});
test("完整路径和用途查询分别固定身份，不同query不能合并", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product");
  const a = client.api("sample-handoff?purpose=A&build_id=one"), b = client.api("sample-handoff?purpose=B&build_id=one"), c = client.api("sample-handoff?purpose=A&build_id=two");
  assert.notEqual(a, b); assert.notEqual(a, c); await turn(); assert.equal(h.calls.length, 2); h.calls[0].resolve("A1"); await turn(); assert.equal(h.calls.length, 3); h.calls[1].resolve("B1"); h.calls[2].resolve("A2"); assert.deepEqual(await Promise.all([a, b, c]), ["A1", "B1", "A2"]);
});
test("不同GET仅两项并发，队列在发送BFF之前等待", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product", 2), reads = ["a", "b", "c", "d"].map(path => client.api(path));
  await turn(); assert.deepEqual(h.calls.map(value => value.path), ["a", "b"]); h.calls[0].resolve("A"); await turn(); assert.deepEqual(h.calls.map(value => value.path), ["a", "b", "c"]); h.calls[1].resolve("B"); await turn(); assert.equal(h.calls[3].path, "d"); h.calls[2].resolve("C"); h.calls[3].resolve("D"); assert.deepEqual(await Promise.all(reads), ["A", "B", "C", "D"]);
});
test("POST不等在途读、不合并相同载荷，期间新GET暂停派发", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product"), oldA = failed(client.api("a")), oldB = failed(client.api("b"));
  await turn(); const body = { command_id: "same-original", idempotency_key: "same-key" }, postA = client.api("commands", body), postB = client.api("commands", body), next = client.api("after");
  await turn(); assert.deepEqual(h.calls.map(value => value.path), ["a", "b", "commands", "commands"]); assert.equal(h.calls[2].body, body); assert.equal(h.calls[3].body, body);
  assert.equal((await oldA as WorkspaceReadError).code, "READ_SUPERSEDED"); assert.equal((await oldB as WorkspaceReadError).code, "READ_SUPERSEDED");
  h.calls[0].resolve("obsolete-a"); h.calls[1].resolve("obsolete-b"); h.calls[2].resolve("receipt-a"); await postA; await turn(); assert.equal(h.calls.length, 4);
  h.calls[3].resolve("receipt-b"); await postB; await turn(); assert.equal(h.calls[4].path, "after"); h.calls[4].resolve("new-current"); assert.equal(await next, "new-current");
});
test("写入前旧读和旧排队都失效，提交后GET只采用新epoch", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product"), old = failed(client.api("workspace")), other = failed(client.api("other")), queued = failed(client.api("queued"));
  await turn(); const post = client.api("commands", { id: "original" }), during = client.api("workspace"); await turn();
  assert.equal((await old as WorkspaceReadError).code, "READ_SUPERSEDED"); assert.equal((await other as WorkspaceReadError).code, "READ_SUPERSEDED"); assert.equal((await queued as WorkspaceReadError).code, "READ_SUPERSEDED"); assert.equal(h.calls.some(call => call.path === "queued"), false);
  h.calls[0].resolve({ revision: "old" }); h.calls[1].resolve(null); h.calls[2].resolve({ receipt: "fixed" }); await post; await turn(); assert.equal(h.calls[3].path, "workspace"); h.calls[3].resolve({ revision: "new" }); assert.deepEqual(await during, { revision: "new" });
});
test("未知POST失败仍失效旧读，不重发命令并释放新epoch读取", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product"), old = failed(client.api("workspace")); await turn();
  const original = { command_id: "fixed", idempotency_key: "fixed-key" }, post = failed(client.api("commands", original)), after = client.api("workspace"); await turn(); h.calls[1].reject(new Error("unknown transport outcome")); assert.match((await post as Error).message, /unknown/); assert.equal((await old as WorkspaceReadError).code, "READ_SUPERSEDED");
  h.calls[0].resolve("old"); await turn(); assert.equal(h.calls.filter(call => call.path === "commands").length, 1); h.calls[2].resolve("fresh"); assert.equal(await after, "fresh");
});
test("显式取消尚未派发的排队读取不会请求服务器，也不影响其他读", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product"), a = client.api("a"), b = client.api("b"), queued = failed(client.api("queued")); client.cancelRead("queued");
  assert.equal((await queued as WorkspaceReadError).code, "READ_CANCELLED"); await turn(); h.calls[0].resolve("A"); h.calls[1].resolve("B"); assert.deepEqual(await Promise.all([a, b]), ["A", "B"]); await turn(); assert.equal(h.calls.some(call => call.path === "queued"), false);
});
test("作用域销毁拒绝在途和排队结果，旧身份API不能继续读取", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "old-user:product"), a = failed(client.api("a")), b = failed(client.api("b")), c = failed(client.api("c")); await turn(); client.dispose();
  for (const pending of [a, b, c]) assert.equal((await pending as WorkspaceReadError).code, "READ_SCOPE_DISPOSED"); assert.equal((await failed(client.api("new")) as WorkspaceReadError).code, "READ_SCOPE_DISPOSED"); h.calls[0].resolve("private-old"); h.calls[1].resolve("private-old"); await turn(); assert.equal(h.calls.length, 2);
});
test("不同页面或用户实例不共享在途Promise或任何结果", async () => {
  const h = harness(), old = createWorkspaceApi(h.transport, "one:product"), next = createWorkspaceApi(h.transport, "two:product"), a = old.api("workspace"), b = next.api("workspace"); assert.notEqual(a, b); await turn(); assert.equal(h.calls.length, 2); h.calls[0].resolve("private-one"); h.calls[1].resolve("private-two"); assert.equal(await a, "private-one"); assert.equal(await b, "private-two");
});
test("旧read finally不能删除同路径新epoch在途项", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product"), old = failed(client.api("workspace")); await turn(); const post = client.api("commands", {}); await turn(); h.calls[1].resolve("saved"); await post;
  const fresh = client.api("workspace"); await turn(); h.calls[0].resolve("old"); await old; await turn(); assert.equal(client.api("workspace"), fresh); h.calls[2].resolve("new"); assert.equal(await fresh, "new");
});
test("失败读取不会缓存，下一次显式刷新实际重新请求", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "user:product"), first = failed(client.api("workspace")); await turn(); h.calls[0].reject({ status: 403, code: "FORBIDDEN" }); assert.deepEqual(await first, { status: 403, code: "FORBIDDEN" }); const retry = client.api("workspace"); await turn(); assert.equal(h.calls.length, 2); h.calls[1].resolve("now-readable"); assert.equal(await retry, "now-readable");
});
test("开发模式effect重新激活仅恢复空新epoch，不复活销毁的旧读", async () => {
  const h = harness(), client = createWorkspaceApi(h.transport, "same-scope"), old = failed(client.api("workspace")); await turn(); client.dispose(); client.activate(); const fresh = client.api("workspace"); await turn(); assert.equal((await old as WorkspaceReadError).code, "READ_SCOPE_DISPOSED"); h.calls[0].resolve("old-private"); h.calls[1].resolve("fresh"); assert.equal(await fresh, "fresh");
});
