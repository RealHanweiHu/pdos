import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = file => ts.transpileModule(readFileSync(path.join(web, file), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const sources = { signIn: compile("src/lib/server/sign-in-proxy.ts"), accounts: compile("src/lib/server/accounts-proxy.ts") };
const sessionToken = "s".repeat(43);
const linkToken = "L".repeat(43);
const uuid = "11111111-1111-4111-8111-111111111111";

function harness(source, options = {}) {
  const route = { exports: {} }, calls = [], jar = new Map(options.cookie === false ? [] : [["pdos-next-session", "existing-session"]]), sets = [], deletes = [];
  runInNewContext(source, {
    module: route, exports: route.exports, Response, AbortSignal, URLSearchParams, Date, JSON, Math, Number,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "next/headers") return { cookies: async () => ({ get: key => jar.has(key) ? { value: jar.get(key) } : undefined, set: (key, value, init) => { jar.set(key, value); sets.push({ key, value, init }); }, delete: key => { jar.delete(key); deletes.push(key); } }) };
      if (name === "@/lib/server/request-origin") return { sameOrigin: () => options.sameOrigin !== false };
      throw new Error(`unexpected import ${name}`);
    },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.failure) throw new Error("synthetic transport failure");
      const reply = typeof options.reply === "function" ? options.reply(url, init) : options.reply;
      return Response.json(reply?.body ?? {}, { status: reply?.status ?? 200 });
    },
  });
  const request = (url, init = {}) => { const value = new Request(`http://localhost:3000${url}`, init); Object.defineProperty(value, "nextUrl", { value: new URL(value.url) }); return value; };
  return { exports: route.exports, calls, jar, sets, deletes, request };
}
const post = (body, headers = {}) => ({ method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: typeof body === "string" ? body : JSON.stringify(body) });
const issued = () => ({ body: { session_token: sessionToken, expires_at: new Date(Date.now() + 7 * 86400e3).toISOString(), idle_timeout_seconds: 43200 } });

test("sign-in keeps the session token in an HttpOnly strict cookie and out of the body", async () => {
  const h = harness(sources.signIn, { reply: issued() });
  const response = await h.exports.signIn(h.request("/api/auth/sign-in", post({ login_name: "walk-admin", password: "synthetic-password" }, { "x-forwarded-for": "198.51.100.7, 203.0.113.9" })));
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.ok(!text.includes(sessionToken));
  assert.equal(JSON.parse(text).status, "signed_in");
  assert.equal(h.sets.length, 1);
  const { key, value, init } = h.sets[0];
  assert.equal(key, "pdos-next-session"); assert.equal(value, sessionToken);
  assert.equal(init.httpOnly, true); assert.equal(init.sameSite, "strict"); assert.equal(init.path, "/"); assert.equal(init.secure, false);
  assert.ok(init.maxAge > 0 && init.maxAge <= 7 * 86400);
  assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/auth/sign-in");
  assert.equal(h.calls[0].init.headers["X-PDOS-Client-Address"], "203.0.113.9");
  assert.deepEqual(JSON.parse(h.calls[0].init.body), { login_name: "walk-admin", password: "synthetic-password" });
  assert.equal(h.calls[0].init.redirect, "error");
});

test("sign-in prefers X-Real-IP and falls back to unknown", async () => {
  for (const [headers, expected] of [[{ "x-real-ip": "192.0.2.4", "x-forwarded-for": "203.0.113.9" }, "192.0.2.4"], [{}, "unknown"]]) {
    const h = harness(sources.signIn, { reply: issued() });
    await h.exports.signIn(h.request("/api/auth/sign-in", post({ login_name: "a", password: "b" }, headers)));
    assert.equal(h.calls[0].init.headers["X-PDOS-Client-Address"], expected);
  }
});

test("cross-origin or malformed sign-in never reaches the API", async () => {
  const cross = harness(sources.signIn, { sameOrigin: false });
  assert.equal((await cross.exports.signIn(cross.request("/api/auth/sign-in", post({ login_name: "a", password: "b" })))).status, 403);
  for (const body of ["not json", { login_name: "a" }, { login_name: "a", password: "b", tenant_id: uuid }, { login_name: "a".repeat(65), password: "b" }, { login_name: "a", password: 5 }, { login_name: "", password: "b" }]) {
    const h = harness(sources.signIn);
    assert.equal((await h.exports.signIn(h.request("/api/auth/sign-in", post(body)))).status, 422);
    assert.equal(h.calls.length, 0);
  }
  assert.equal(cross.calls.length, 0);
});

test("rejections and throttling keep their status and set no cookie", async () => {
  for (const status of [401, 429]) {
    const body = { code: status === 401 ? "FORBIDDEN_SCOPE" : "RATE_LIMITED", message: "synthetic", detail: { reason: "SIGN_IN_REJECTED" }, session_token: sessionToken };
    const h = harness(sources.signIn, { reply: { status, body } });
    const response = await h.exports.signIn(h.request("/api/auth/sign-in", post({ login_name: "a", password: "b" })));
    assert.equal(response.status, status);
    const value = await response.json();
    assert.deepEqual(Object.keys(value).sort(), ["code", "detail", "message"]);
    assert.equal(h.sets.length, 0);
  }
  const broken = harness(sources.signIn, { reply: { body: { expires_at: new Date().toISOString() } } });
  assert.equal((await broken.exports.signIn(broken.request("/api/auth/sign-in", post({ login_name: "a", password: "b" })))).status, 502);
  assert.equal(broken.sets.length, 0);
  const down = harness(sources.signIn, { failure: true });
  assert.equal((await down.exports.signIn(down.request("/api/auth/sign-in", post({ login_name: "a", password: "b" })))).status, 503);
});

test("sign-out ends the server session and always clears the cookie", async () => {
  const h = harness(sources.signIn, { reply: { body: { status: "signed_out" } } });
  const response = await h.exports.signOut(h.request("/api/auth/sign-out", post({})));
  assert.deepEqual(await response.json(), { status: "signed_out", server: "ended" });
  assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/auth/sign-out");
  assert.equal(h.calls[0].init.headers.Authorization, "Bearer existing-session");
  assert.deepEqual(h.deletes, ["pdos-next-session"]);
  const down = harness(sources.signIn, { failure: true });
  assert.equal((await (await down.exports.signOut(down.request("/api/auth/sign-out", post({})))).json()).server, "unconfirmed");
  assert.deepEqual(down.deletes, ["pdos-next-session"]);
  const none = harness(sources.signIn, { cookie: false });
  await none.exports.signOut(none.request("/api/auth/sign-out", post({})));
  assert.equal(none.calls.length, 0);
});

test("invitation inspect forwards only a well-formed token and returns four fields", async () => {
  const h = harness(sources.signIn, { reply: { body: { purpose: "invite", display_name: "合成成员", login_name: "member-1", expires_at: "2026-11-10T00:00:00+00:00", tenant_id: uuid } } });
  const response = await h.exports.inspectInvitation(h.request("/api/auth/invitation", post({ token: linkToken })));
  assert.deepEqual(Object.keys(await response.json()).sort(), ["display_name", "expires_at", "login_name", "purpose"]);
  assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/auth/invitations/inspect");
  for (const token of ["short", "x".repeat(129), "has space ".repeat(5)]) {
    const bad = harness(sources.signIn);
    assert.equal((await bad.exports.inspectInvitation(bad.request("/api/auth/invitation", post({ token })))).status, 404);
    assert.equal(bad.calls.length, 0);
  }
});

test("accepting a link signs in through the cookie; a used link stays refused", async () => {
  const h = harness(sources.signIn, { reply: issued() });
  const response = await h.exports.acceptInvitation(h.request("/api/auth/invitation/accept", post({ token: linkToken, password: "synthetic-password" })));
  assert.equal(response.status, 200); assert.ok(!(await response.text()).includes(sessionToken));
  assert.equal(h.sets[0].value, sessionToken);
  const used = harness(sources.signIn, { reply: { status: 409, body: { code: "SOURCE_STALE", message: "used", detail: { reason: "INVITATION_USED" } } } });
  const refused = await used.exports.acceptInvitation(used.request("/api/auth/invitation/accept", post({ token: linkToken, password: "synthetic-password" })));
  assert.equal(refused.status, 409); assert.equal((await refused.json()).detail.reason, "INVITATION_USED");
  assert.equal(used.sets.length, 0);
});

test("account BFF forwards the caller's session, exact bodies and allow-listed actions only", async () => {
  const h = harness(sources.accounts, { reply: { body: { items: [] } } });
  assert.equal((await h.exports.listAccounts(h.request("/api/v1/accounts"))).status, 200);
  assert.equal(h.calls[0].init.headers.Authorization, "Bearer existing-session");
  assert.equal((await h.exports.listAccounts(h.request("/api/v1/accounts?tenant_id=x"))).status, 422);
  assert.equal((await h.exports.createAccount(h.request("/api/v1/accounts", post({ display_name: "王工", login_name: "wang", administrator: true })))).status, 422);
  await h.exports.createAccount(h.request("/api/v1/accounts", post({ display_name: "王工", login_name: "wang" })));
  assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), { display_name: "王工", login_name: "wang" });
  const params = (principalId, action) => ({ params: Promise.resolve({ principalId, action }) });
  const act = (id, action, body = {}) => h.exports.accountAction(h.request(`/api/v1/accounts/${id}/${action.join("/")}`, post(body)), params(id, action));
  for (const action of [["invitation"], ["password-reset"], ["deactivate"], ["reactivate"], ["sessions", "revoke"]]) {
    assert.equal((await act(uuid, action)).status, 200);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/v1/accounts/${uuid}/${action.join("/")}`);
    assert.equal((await act(uuid, action, { reason: "x" })).status, 422);
  }
  assert.equal((await act(uuid, ["administrator"], { administrator: true })).status, 200);
  assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), { administrator: true });
  for (const body of [{}, { administrator: "yes" }, { administrator: true, principal_id: uuid }]) assert.equal((await act(uuid, ["administrator"], body)).status, 422);
  const before = h.calls.length;
  assert.equal((await act("not-a-uuid", ["deactivate"])).status, 404);
  assert.equal((await act(uuid, ["delete"])).status, 404);
  assert.equal((await act(uuid, ["sessions"])).status, 404);
  assert.equal(h.calls.length, before);
  const anonymous = harness(sources.accounts, { cookie: false });
  assert.equal((await anonymous.exports.listAccounts(anonymous.request("/api/v1/accounts"))).status, 401);
  const cross = harness(sources.accounts, { sameOrigin: false });
  assert.equal((await cross.exports.createAccount(cross.request("/api/v1/accounts", post({ display_name: "x", login_name: "x" })))).status, 403);
  assert.equal(anonymous.calls.length + cross.calls.length, 0);
  const down = harness(sources.accounts, { failure: true });
  assert.equal((await (await down.exports.accountAction(down.request(`/api/v1/accounts/${uuid}/deactivate`, post({})), params(uuid, ["deactivate"]))).json()).code, "EXTERNAL_OUTCOME_UNKNOWN");
});
