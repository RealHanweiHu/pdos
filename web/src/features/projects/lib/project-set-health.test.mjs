import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const dir = path.dirname(fileURLToPath(import.meta.url)), dep = createRequire(path.join(dir, "../../../../package.json")), ts = dep("typescript");
const filename = path.join(dir, "project-set-health.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { setLane, setProgress, memberStage, memberHealth, memberNeedsAttention, setLaneOrder, setLaneNames } = loaded.exports;

const member = (state, label = state, extra = {}) => ({ project: { governance: { health: { state, label, reason: `${label} 的规则原因` }, current_stage: { name: "EVT" }, completed: false, ...extra } } });

test("set lanes come only from member rule health; no set-level business state", () => {
  assert.deepEqual(setLaneOrder.map(lane => setLaneNames[lane]), ["需关注", "进展正常", "暂无可见项目"]);
  assert.equal(setLane([]), "empty");
  assert.equal(setLane([member("normal", "正常"), member("normal", "正常")]), "normal");
  for (const state of ["blocked", "unknown", "risk", "pending_approval"]) assert.equal(setLane([member("normal", "正常"), member(state)]), "attention");
});

test("unread health never looks healthy", () => {
  const unread = { project: {} };
  assert.equal(memberNeedsAttention(unread), true);
  assert.equal(setLane([unread]), "attention");
  assert.deepEqual(memberHealth(unread), { label: "未读取", reason: "健康度暂不可读", tone: "neutral" });
  assert.equal(memberStage(unread), "阶段未读取");
});

test("progress text counts whole projects, never a ratio or percentage", () => {
  assert.equal(setProgress([]), "暂无可见项目");
  assert.equal(setProgress([member("normal", "正常")]), "全部正常");
  const text = setProgress([member("normal", "正常"), member("risk", "有风险"), member("blocked", "有阻塞")]);
  assert.equal(text, "2 个需关注");
  assert.doesNotMatch(text, /%|\//);
});

test("stage column shows position from the adopted template, or says it is missing", () => {
  assert.equal(memberStage(member("normal")), "EVT");
  assert.equal(memberStage(member("unknown", "待核对", { current_stage: null })), "未采用阶段模板");
  assert.equal(memberStage(member("normal", "正常", { current_stage: null, completed: true })), "阶段已完成");
  assert.equal(memberHealth(member("blocked", "有阻塞")).tone, "danger");
  assert.equal(memberHealth(member("risk", "有风险")).reason, "有风险 的规则原因");
});
