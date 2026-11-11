import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const source = ts.transpileModule(readFileSync(path.join(web, "src/lib/server/work-calendar-proxy.ts"), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const uuid = "11111111-1111-4111-8111-111111111111";
const key = "22222222-2222-4222-8222-222222222222";

function harness(options = {}) {
  const route = { exports: {} }, calls = [];
  runInNewContext(source, {
    module: route, exports: route.exports, Response, AbortSignal, URLSearchParams, Date, JSON, Number, Object, Array,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "next/headers") return { cookies: async () => ({ get: k => options.cookie === false || k !== "pdos-next-session" ? undefined : { value: "existing-session" } }) };
      if (name === "@/lib/server/request-origin") return { sameOrigin: () => options.sameOrigin !== false };
      throw new Error(`unexpected import ${name}`);
    },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.failure) throw new Error("synthetic transport failure");
      return Response.json(options.body ?? {}, { status: options.status ?? 200 });
    },
  });
  const request = (url, init = {}) => { const value = new Request(`http://localhost:3000${url}`, init); Object.defineProperty(value, "nextUrl", { value: new URL(value.url) }); return value; };
  return { exports: route.exports, calls, request };
}
const post = body => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: typeof body === "string" ? body : JSON.stringify(body) });
const params = calendarId => ({ params: Promise.resolve({ calendarId }) });
const definition = {
  timezone: "Asia/Shanghai",
  working_weekdays: [1, 2, 3, 4, 5],
  entries: [{ kind: "shutdown", start: "2027-01-30", end: "2027-02-21", label: "2027 春节停线" }],
  reason: "登记春节停线",
  request_key: key,
};

test("reads forward the caller's session and refuse extra query parameters", async () => {
  const h = harness({ body: { calendars: [] } });
  assert.equal((await h.exports.listCalendars(h.request("/api/v1/work-calendars"))).status, 200);
  assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/work-calendars");
  assert.equal(h.calls[0].init.headers.Authorization, "Bearer existing-session");
  assert.equal((await h.exports.listCalendars(h.request("/api/v1/work-calendars?tenant_id=x"))).status, 422);
  assert.equal((await h.exports.calendarVersions(h.request(`/api/v1/work-calendars/${uuid}/versions`), params(uuid))).status, 200);
  assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/v1/work-calendars/${uuid}/versions`);
  assert.equal((await h.exports.calendarVersions(h.request("/api/v1/work-calendars/x/versions"), params("x"))).status, 404);
  const anonymous = harness({ cookie: false });
  assert.equal((await anonymous.exports.listCalendars(anonymous.request("/api/v1/work-calendars"))).status, 401);
  assert.equal(anonymous.calls.length, 0);
});

test("create and save pass exact bodies only", async () => {
  const h = harness({ status: 201, body: {} });
  assert.equal((await h.exports.createCalendar(h.request("/api/v1/work-calendars", post({ kind: "factory", ...definition })))).status, 201);
  assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), { kind: "factory", ...definition });
  assert.equal((await h.exports.createCalendar(h.request("/api/v1/work-calendars", post({ kind: "supplier", name: "合成电芯厂", ...definition })))).status, 201);
  assert.equal((await h.exports.saveCalendar(h.request(`/api/v1/work-calendars/${uuid}/versions`, post({ expected_revision: 2, ...definition })), params(uuid))).status, 201);
  assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/v1/work-calendars/${uuid}/versions`);
  const before = h.calls.length;
  for (const body of [
    { kind: "supplier", ...definition },
    { kind: "factory", name: "x", ...definition },
    { kind: "factory", ...definition, author_id: uuid },
    { kind: "factory", ...definition, request_key: "not-a-uuid" },
    { kind: "factory", ...definition, working_weekdays: [0] },
    { kind: "factory", ...definition, reason: " " },
    { kind: "factory", ...definition, entries: [{ ...definition.entries[0], kind: "closure" }] },
    { kind: "factory", ...definition, entries: [{ ...definition.entries[0], start: "2027-1-30" }] },
    { kind: "factory", ...definition, entries: [{ ...definition.entries[0], tenant_id: uuid }] },
    "not json",
  ]) assert.equal((await h.exports.createCalendar(h.request("/api/v1/work-calendars", post(body)))).status, 422, JSON.stringify(body));
  for (const body of [definition, { expected_revision: 0, ...definition }, { expected_revision: 1, ...definition, kind: "factory" }]) {
    assert.equal((await h.exports.saveCalendar(h.request(`/api/v1/work-calendars/${uuid}/versions`, post(body)), params(uuid))).status, 422);
  }
  assert.equal(h.calls.length, before);
  const cross = harness({ sameOrigin: false });
  assert.equal((await cross.exports.createCalendar(cross.request("/api/v1/work-calendars", post({ kind: "factory", ...definition })))).status, 403);
  assert.equal((await cross.exports.saveCalendar(cross.request(`/api/v1/work-calendars/${uuid}/versions`, post({ expected_revision: 1, ...definition })), params(uuid))).status, 403);
  assert.equal(cross.calls.length, 0);
  const down = harness({ failure: true });
  const unknown = await down.exports.saveCalendar(down.request(`/api/v1/work-calendars/${uuid}/versions`, post({ expected_revision: 1, ...definition })), params(uuid));
  assert.equal(unknown.status, 503);
  assert.equal((await unknown.json()).code, "EXTERNAL_OUTCOME_UNKNOWN");
});

test("the working-day trial needs an aware instant and a bounded day count", async () => {
  const h = harness({ body: { result: "x" } });
  const at = "2027-01-29T02:00:00.000Z";
  assert.equal((await h.exports.workingDays(h.request(`/api/v1/work-calendars/working-days?at=${encodeURIComponent(at)}&days=1&calendar_id=${uuid}`))).status, 200);
  const forwarded = new URL(h.calls[0].url);
  assert.equal(forwarded.pathname, "/v1/work-calendars/working-days");
  assert.deepEqual(Object.fromEntries(forwarded.searchParams), { at, days: "1", calendar_id: uuid });
  for (const query of [`at=2027-01-29T10:00&days=1`, `at=${encodeURIComponent(at)}&days=367`, `at=${encodeURIComponent(at)}&days=-1`, `at=${encodeURIComponent(at)}&days=1&calendar_id=x`, `at=${encodeURIComponent(at)}&days=1&tenant_id=${uuid}`, "days=1"]) {
    assert.equal((await h.exports.workingDays(h.request(`/api/v1/work-calendars/working-days?${query}`))).status, 422, query);
  }
  assert.equal(h.calls.length, 1);
});
