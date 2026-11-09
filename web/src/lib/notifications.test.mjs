import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "notifications.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { headline, snoozeOptions, notificationsPath, unreadTotal, liveDelivery, POLL_MS } = loaded.exports;

test("a merged notification reads as one line with its count", () => {
  assert.equal(headline({ actors: ["许晴"], reason_label: "发表了评论", event_count: 3 }), "许晴 发表了评论 · 3 条");
  assert.equal(headline({ actors: ["许晴", "陈舟"], reason_label: "提交了成果，等你验收", event_count: 1 }), "许晴 等 2 人 提交了成果，等你验收");
  assert.equal(unreadTotal({ unread: { mention: 2, assigned: 1, decide: 0, agent: 0, follow: 4 } }), 7);
  assert.equal(notificationsPath("inbox", "all"), "v1/personal/notifications");
  assert.equal(notificationsPath("snoozed", "mention", 9), "v1/personal/notifications?view=snoozed&category=mention&before=9");
});

test("snooze presets are all in the future and next Monday is a Monday", () => {
  const now = new Date(2026, 10, 8, 16, 30);
  const options = snoozeOptions(now);
  assert.deepEqual(options.map(option => option.id), ["hour", "tomorrow", "monday"]);
  assert.ok(options.every(option => new Date(option.until) > now));
  assert.equal(new Date(options[2].until).getDay(), 1);
  assert.deepEqual(snoozeOptions(new Date(2026, 10, 9, 10, 0)).map(option => option.id), ["hour", "afternoon", "tomorrow", "monday"]);
});

function harness({ polls = [] } = {}) {
  const intervals = [], timeouts = [], sources = [], changes = [], modes = [], polled = [];
  const timers = { setInterval: (fn, ms) => { intervals.push({ fn, ms, live: true }); return intervals.length - 1; }, clearInterval: id => { intervals[id].live = false; }, setTimeout: fn => { timeouts.push(fn); return timeouts.length - 1; }, clearTimeout: () => undefined };
  const open = url => { const listeners = {}; const source = { url, listeners, closed: false, onerror: null, addEventListener: (type, fn) => { listeners[type] = fn; }, close() { this.closed = true; }, emit(type, data) { listeners[type]?.({ data: JSON.stringify(data) }); } }; sources.push(source); return source; };
  const poll = async value => { polled.push(value); return polls.shift() ?? { cursor: "1.0", threads: {}, changed: false }; };
  const delivery = liveDelivery({ threads: () => ["t1"], onChange: state => changes.push(state), onMode: mode => modes.push(mode), open, poll, timers });
  return { delivery, intervals, timeouts, sources, changes, modes, polled };
}

test("SSE first; a dropped stream falls back to 30-second polling and the next ready stops it", async () => {
  const h = harness({ polls: [{ cursor: "5.0", threads: { t1: "9" }, changed: true }] });
  assert.equal(h.sources.length, 1);
  assert.match(h.sources[0].url, /^\/api\/v1\/personal\/notifications\/stream\?threads=t1$/);
  h.sources[0].emit("ready", { cursor: "4.0", threads: { t1: "8" } });
  assert.deepEqual(h.modes, ["connecting", "live"]);
  assert.equal(h.changes.length, 0, "the first state is a baseline, not a change");
  h.sources[0].emit("changed", { cursor: "4.1", threads: { t1: "8" } });
  assert.equal(h.changes.length, 1);
  h.sources[0].onerror({});
  assert.equal(h.sources[0].closed, true);
  assert.equal(h.modes.at(-1), "polling");
  assert.equal(h.intervals.length, 1);
  assert.equal(h.intervals[0].ms, POLL_MS);
  assert.equal(POLL_MS, 30000);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(h.polled[0], /changes\?since=4\.1&threads=t1$/);
  assert.equal(h.changes.at(-1).cursor, "5.0");
  assert.deepEqual(h.changes.at(-1).threads, { t1: "9" });
  // The 30-second beat also retries the stream; once it is ready, polling stops.
  h.intervals[0].fn();
  assert.equal(h.sources.length, 2);
  assert.match(h.sources[1].url, /since=5\.0/);
  h.sources[1].emit("ready", { cursor: "5.0", threads: { t1: "9" } });
  assert.equal(h.intervals[0].live, false);
  assert.equal(h.modes.at(-1), "live");
  h.delivery.stop();
  assert.equal(h.sources[1].closed, true);
});

test("a closed stream (session ended) polls; a lifetime reconnect reopens immediately", () => {
  const h = harness();
  h.sources[0].emit("ready", { cursor: "1.0", threads: {} });
  h.sources[0].listeners.reconnect({ data: "{}" });
  assert.equal(h.timeouts.length, 1);
  h.timeouts[0]();
  assert.equal(h.sources.length, 2);
  h.sources[1].listeners.closed({ data: "{}" });
  assert.equal(h.modes.at(-1), "polling");
  h.delivery.stop();
});
