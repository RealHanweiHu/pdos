import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const dir = path.dirname(fileURLToPath(import.meta.url)), dep = createRequire(path.join(dir, "../../../../package.json")), ts = dep("typescript");
function load(name) { const filename = path.join(dir, name), loaded = new Module(filename); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename); return loaded.exports; }
const { weekdayText, rangeText, draftProblems, definitionBody, yearSummary, isoWeekday, isDay, draftOf, zonedInstant } = load("work-calendar.ts");

const spring = [
  { kind: "shutdown", start: "2027-01-30", end: "2027-02-21", label: "2027 春节停线" },
  { kind: "holiday", start: "2027-02-05", end: "2027-02-13", label: "春节" },
  { kind: "makeup_workday", start: "2027-02-28", end: "2027-02-28", label: "春节调休" },
];

test("weekday and date ranges read like the page", () => {
  assert.equal(weekdayText([5, 1, 2, 3, 4]), "周一至周五");
  assert.equal(weekdayText([1, 2, 3, 4, 5, 6]), "周一至周六");
  assert.equal(weekdayText([1, 3, 5]), "周一、周三、周五");
  assert.equal(weekdayText([6, 7]), "周六、周日");
  assert.equal(rangeText(spring[0]), "2027-01-30 至 2027-02-21（23 天）");
  assert.equal(rangeText(spring[2]), "2027-02-28");
  assert.equal(isoWeekday("2027-02-28"), 7);
  assert.equal(isoWeekday("2027-02-22"), 1);
  assert.ok(isDay("2028-02-29") && !isDay("2027-02-29") && !isDay("2027-2-1"));
});

test("draft checks mirror the server's rules in plain words", () => {
  const draft = { timezone: "Asia/Shanghai", working_weekdays: [1, 2, 3, 4, 5], entries: spring };
  assert.deepEqual(draftProblems(draft), []);
  assert.deepEqual(draftProblems({ ...draft, entries: [{ kind: "makeup_workday", start: "2027-02-22", end: "2027-02-22", label: "调休" }] }), ["2027-02-22 本来就是工作日，不能登记为调休上班。"]);
  assert.deepEqual(draftProblems({ ...draft, entries: [{ kind: "holiday", start: "2027-02-27", end: "2027-02-28", label: "假" }, { kind: "makeup_workday", start: "2027-02-28", end: "2027-02-28", label: "调" }] }), ["2027-02-28 同时登记了法定假日和调休上班。"]);
  assert.deepEqual(draftProblems({ ...draft, entries: [{ kind: "shutdown", start: "2027-03-02", end: "2027-03-01", label: "检修" }] }), ["检修：结束日期早于开始日期。"]);
  assert.deepEqual(draftProblems({ ...draft, entries: [{ kind: "shutdown", start: "2027-03-02", end: "", label: " " }] }), ["每条登记都要写说明。", "未写说明的登记：日期不完整。"]);
  assert.deepEqual(draftProblems({ ...draft, entries: [spring[1], { ...spring[1] }] }), ["春节：重复登记。"]);
  assert.deepEqual(draftProblems({ ...draft, working_weekdays: [] }), ["至少选一个工作日。"]);
});

test("save bodies carry sorted, trimmed entries and the request key, nothing else", () => {
  const body = definitionBody({ timezone: "Asia/Shanghai", working_weekdays: [5, 1, 3], entries: [{ ...spring[2], label: "  春节调休 " }, spring[0]] }, " 登记春节 ", "key-1");
  assert.deepEqual(body, {
    timezone: "Asia/Shanghai",
    working_weekdays: [1, 3, 5],
    entries: [{ kind: "shutdown", start: "2027-01-30", end: "2027-02-21", label: "2027 春节停线" }, { kind: "makeup_workday", start: "2027-02-28", end: "2027-02-28", label: "春节调休" }],
    reason: "登记春节",
    request_key: "key-1",
  });
  const draft = draftOf({ timezone: "Asia/Shanghai", working_weekdays: [1, 2, 3, 4, 5], entries: [{ ...spring[0], kind_label: "停线", days: 23 }] });
  assert.deepEqual(draft.entries, [spring[0]]);
  assert.deepEqual(draftOf(null), { timezone: "Asia/Shanghai", working_weekdays: [1, 2, 3, 4, 5], entries: [] });
});

test("the year summary counts lost working days once and worked weekends", () => {
  // Sat 30 Jan–Sun 21 Feb 2027 holds 15 weekdays; the holiday inside the stop is not counted twice.
  assert.deepEqual(yearSummary({ working_weekdays: [1, 2, 3, 4, 5], entries: spring }, 2027), { off: 15, makeup: 1 });
  assert.deepEqual(yearSummary({ working_weekdays: [1, 2, 3, 4, 5], entries: spring }, 2026), { off: 0, makeup: 0 });
});

test("a trial start is read in the calendar's time zone, whatever the browser's", () => {
  assert.equal(zonedInstant("2027-01-29T10:00", "Asia/Shanghai"), "2027-01-29T02:00:00.000Z");
  assert.equal(zonedInstant("2027-07-01T09:30", "Europe/Berlin"), "2027-07-01T07:30:00.000Z");
  assert.equal(zonedInstant("2027-01-04T09:30", "Europe/Berlin"), "2027-01-04T08:30:00.000Z");
  assert.equal(zonedInstant("2027-03-14T12:00", "America/Los_Angeles"), "2027-03-14T19:00:00.000Z");
  assert.throws(() => zonedInstant("2027-01-29", "Asia/Shanghai"));
});
