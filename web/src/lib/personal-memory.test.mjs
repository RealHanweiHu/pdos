import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import test from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript");
const filename = path.join(web, "src/lib/personal-memory.ts"), loaded = new Module(filename);
loaded.require = dependency;
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const memory = loaded.exports;
const id = "11111111-1111-4111-8111-111111111111";

test("a draft sends only the owner's explicit fields; nothing is guessed", () => {
  assert.deepEqual(memory.draftPayload({ kind: "convention", text: "  回答  先给结论 ", scope: { kind: "global", id: id }, valid_until: "" }),
    { kind: "convention", text: "回答 先给结论", scope: { kind: "global", id: null } });
  const alias = memory.draftPayload({ kind: "alias", text: "", scope: { kind: "category", id }, alias_term: " 气嘴 ", alias_canonical: "气门嘴" });
  assert.deepEqual(alias, { kind: "alias", text: "", scope: { kind: "category", id }, alias_term: "气嘴", alias_canonical: "气门嘴" });
  assert.match(memory.draftPayload({ kind: "background", text: "x", scope: { kind: "global", id: null }, valid_until: "2026-12-31" }).valid_until, /^2026-12-31T|^2027-01-01T/);
});

test("drafts are checked before any request", () => {
  assert.equal(memory.draftProblem({ kind: "convention", text: " ", scope: { kind: "global", id: null } }), "请写下要记住的内容。");
  assert.equal(memory.draftProblem({ kind: "alias", text: "", scope: { kind: "global", id: null }, alias_term: "气嘴" }), "请写下它指的标准词。");
  assert.equal(memory.draftProblem({ kind: "convention", text: "长".repeat(201), scope: { kind: "global", id: null } }), "内容最多 200 个字。");
  assert.equal(memory.draftProblem({ kind: "convention", text: "按欧标", scope: { kind: "project", id: null } }), "请选择作用范围。");
  assert.equal(memory.draftProblem({ kind: "convention", text: "按欧标", scope: { kind: "project", id } }), "");
});

test("conflict choices name every old note's revision; merge targets one", () => {
  const conflicts = [{ note_id: "a", revision: 2 }, { note_id: "b", revision: 1 }];
  assert.deepEqual(memory.choicePayload("keep_both", conflicts, null, ""), { resolution: "keep_both", note_ids: [], expected_revisions: [] });
  assert.deepEqual(memory.choicePayload("replace", conflicts, null, ""), { resolution: "replace", note_ids: ["a", "b"], expected_revisions: [2, 1] });
  assert.deepEqual(memory.choicePayload("merge", conflicts, "b", " 中文 附英文摘要 "), { resolution: "merge", note_ids: ["b"], expected_revisions: [1], merged_text: "中文 附英文摘要" });
  assert.equal(memory.mergedDefault("报告用中文", "附英文摘要"), "报告用中文；附英文摘要");
  assert.equal(memory.mergedDefault("报告用中文，附英文摘要", "附英文摘要"), "报告用中文，附英文摘要");
  assert.equal(memory.mergedDefault("长".repeat(150), "短".repeat(80)).length, 200);
});

test("labels never reveal an unreadable scope or object", () => {
  assert.equal(memory.scopeLabel({ kind: "global", title: "全局", readable: true }), "全局");
  assert.equal(memory.scopeLabel({ kind: "project", title: "P1", readable: true }), "项目 · P1");
  assert.equal(memory.scopeLabel({ kind: "category", title: null, readable: false }), "品类（当前不可读）");
  assert.equal(memory.aliasMeaning({ alias: { term: "老王那个泵", means: { kind: "project", text: null, readable: false } } }), "所指对象当前不可读");
  assert.equal(memory.aliasMeaning({ alias: { term: "F64", means: { kind: "product", text: "F64000", readable: true, updated: true } } }), "F64000（对象已更新）");
  const groups = memory.groupNotes([{ kind: "convention", state: "active" }, { kind: "alias", state: "stale" }, { kind: "background", state: "replaced" }, { kind: "convention", state: "expired" }]);
  assert.deepEqual([groups.convention.length, groups.alias.length, groups.background.length, groups.past.length], [1, 1, 0, 2]);
  assert.equal(memory.isNotesView({ version: "memory-notes/v1", notes: [] }), true);
  assert.equal(memory.isNotesView({ version: "memory-notes/v2", notes: [] }), false);
});
