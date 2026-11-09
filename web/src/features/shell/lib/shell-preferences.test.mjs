import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const dir = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(dir, "../../../.."), dep = createRequire(path.join(web, "package.json")), ts = dep("typescript");
const cache = new Map();
function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = name => name === "react" ? dep("react") : name.startsWith("@/") ? load([".ts", ".tsx"].map(ext => path.join(web, "src", name.slice(2)) + ext).find(file => { try { readFileSync(file); return true; } catch { return false; } })) : dep(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return loaded.exports;
}
const { countText, defaultHomeArea, readPendingCount, shellPreferences } = load(path.join(dir, "shell-preferences.ts"));
const me = "11111111-1111-4111-8111-111111111111";

test("default home applies only to a bare entry and unknown values fall back to 我的工作", () => {
  const inbox = shellPreferences({ revision: 2, preferences: { default_home: "inbox", pending_reminders: false } });
  assert.deepEqual(inbox, { default_home: "inbox", pending_reminders: false });
  assert.equal(defaultHomeArea("", inbox), "inbox");
  for (const search of ["?area=work", "?category=c", "?project=p", "?bench=products"]) assert.equal(defaultHomeArea(search, inbox), null, search);
  assert.equal(defaultHomeArea("", shellPreferences({ preferences: { default_home: "settings", pending_reminders: "yes" } })), null);
  assert.deepEqual(shellPreferences(null), { default_home: "work", pending_reminders: true });
  assert.equal(countText(120), "99+");
});

test("pending count sums 要我决定、接收、验证 with GET reads only and refuses another person's queue", async () => {
  const calls = [];
  const page = (queue, total, principal = me) => ({ version: "personal-attention/v1", principal_id: principal, queue, items: [], total_records: total, next_cursor: null, as_of: "2026-11-08T00:00:00Z" });
  const totals = { decide: 2, receive: 1, verify: 4 };
  const count = await readPendingCount(async (route, body) => { calls.push([route, body]); const queue = new URLSearchParams(route.split("?")[1]).get("queue"); return page(queue, totals[queue]); }, me);
  assert.equal(count, 7);
  assert.deepEqual(calls.map(([route]) => route), ["decide", "receive", "verify"].map(queue => `v1/personal/attention?queue=${queue}&page_size=1`));
  assert.ok(calls.every(([, body]) => body === undefined));
  await assert.rejects(readPendingCount(async route => page(new URLSearchParams(route.split("?")[1]).get("queue"), 1, "22222222-2222-4222-8222-222222222222"), me));
});
