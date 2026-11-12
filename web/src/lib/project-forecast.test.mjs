import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "project-forecast.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { refreshCommand, windowText, shiftText, floatText, checkView } = loaded.exports;

const view = { project: { id: "proj", revision: 4 }, current: null, unavailable: null, history: [], inputs: { plan: { id: "plan", revision: 2 }, input_sha256: "a".repeat(64), as_of_day: "2026-11-08", changed: true, facts: {} } };

test("refresh names the plan and the input digest it read, without sources or tokens", () => {
  const command = refreshCommand(view, { id: "prod", revision: 1 });
  assert.equal(command.operation, "work.forecast.refresh");
  assert.deepEqual(command.payload, { project_id: "proj", plan: { id: "plan", revision: 2 }, expected_input_sha256: "a".repeat(64) });
  assert.deepEqual(command.source_read_set, []);
  assert.throws(() => refreshCommand({ ...view, inputs: null }, { id: "prod", revision: 1 }), /没有应用的计划/);
});

test("windows, shifts and float read as ranges, unknowns and working days", () => {
  const id = value => value;
  assert.equal(windowText({ earliest: null, latest: null }, id), "未知");
  assert.equal(windowText({ earliest: "a", latest: "a" }, id), "a");
  assert.equal(windowText({ earliest: "a", latest: null }, id), "a — 未知");
  assert.equal(shiftText(null), "无法比较");
  assert.equal(shiftText(0), "与计划一致");
  assert.equal(shiftText(6 * 1440), "比计划晚 6 天");
  assert.equal(shiftText(-120), "比计划早 2 小时");
  assert.equal(floatText({ critical: true, working_float_minutes: 0 }), "关键路径");
  assert.equal(floatText({ critical: false, working_float_minutes: 1920 }), "浮时 4 个工作日");
  assert.equal(floatText({ critical: null, working_float_minutes: null }), "未计算");
  assert.throws(() => checkView({ project: { id: "other" }, history: [] }, "proj"));
});
