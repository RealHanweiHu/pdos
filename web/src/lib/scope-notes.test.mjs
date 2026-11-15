import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const loaded = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(path.join(web, "src/lib/scope-notes.ts"), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports, crypto: { randomUUID: () => "11111111-1111-4111-8111-111111111111" } });
const lib = loaded.exports;
const plain = value => JSON.parse(JSON.stringify(value));
const anchor = { kind: "project", id: "22222222-2222-4222-8222-222222222222" };

test("a draft sends only what the person chose; server-bound facts are never in the payload", () => {
  const draft = { ...lib.emptyDraft(), statement: "  给该客户的报告一律英文  ", pinned: true };
  assert.equal(lib.draftProblem(draft), null);
  assert.deepEqual(plain(lib.bodyPayload(draft)), { kind: "convention", statement: "给该客户的报告一律英文", epistemic: "stated", confirmation: "member_confirmed", pinned: true });
  const full = { ...draft, kind: "decision_context", discussion: true, customer: " 客户A ", valid_from: "2026-09-01", formal: lib.formalKey(anchor.kind, anchor.id) };
  assert.deepEqual(plain(lib.bodyPayload(full)), { kind: "decision_context", statement: "给该客户的报告一律英文", epistemic: "stated", confirmation: "discussion", pinned: true, customer: "客户A", valid_from: "2026-09-01T00:00:00Z", formal: anchor });
  // D509: any formal object the server listed, e.g. the G0 decision; only 决策背景 carries one.
  const decision = "44444444-4444-4444-8444-444444444444";
  assert.deepEqual(plain(lib.bodyPayload({ ...full, formal: lib.formalKey("proposal_decision", decision) })).formal, { kind: "proposal_decision", id: decision });
  assert.equal("formal" in lib.bodyPayload({ ...full, kind: "convention" }), false);
  assert.equal("formal" in lib.bodyPayload({ ...full, formal: "" }), false);
  for (const key of ["confirmed_by", "review_due_at", "source_authority", "generated_by", "tenant_id"]) assert.equal(key in lib.bodyPayload(full), false);
  assert.equal(lib.draftProblem({ ...draft, statement: "  " }), "请写下备忘内容。");
  assert.match(lib.draftProblem({ ...draft, statement: "字".repeat(301) }), /300/);
});

test("similar notes become relations or an explicit keep, never a silent overwrite", () => {
  const similar = [{ note_id: "a", revision: 2 }, { note_id: "b", revision: 1 }];
  assert.deepEqual(plain(lib.relationPayload("supersede", similar)), { relations: [{ type: "supersedes", note: { id: "a", revision: 2 } }, { type: "supersedes", note: { id: "b", revision: 1 } }], kept_similar: [] });
  assert.deepEqual(plain(lib.relationPayload("conflict", similar)).relations.map(item => item.type), ["conflicts", "conflicts"]);
  assert.deepEqual(plain(lib.relationPayload("keep", similar)), { relations: [], kept_similar: ["a", "b"] });
});

test("paths and the command envelope stay inside the category in the path", () => {
  const category = "33333333-3333-4333-8333-333333333333";
  assert.equal(lib.listPath(category, "project", anchor.id), `v1/categories/${category}/scope-notes/project/${anchor.id}`);
  assert.equal(lib.listPath(category, "category", category, true), `v1/categories/${category}/scope-notes/category/${category}/all`);
  assert.equal(lib.itemPath(category, "n"), `v1/categories/${category}/scope-note-items/n`);
  assert.equal(lib.commandPath(category, true), `v1/categories/${category}/commands/preview`);
  const command = lib.commandEnvelope("scope_note.save", { anchor }, { categoryId: category, productId: "p" }, { command: "c", key: "k" });
  assert.deepEqual(plain(command), { category_id: category, command_id: "c", idempotency_key: "k", operation: "scope_note.save", product_id: "p", expected_revision: 1, source_read_set: [], payload: { anchor } });
  assert.equal(lib.commandEnvelope("scope_note.retire", {}, { categoryId: category }, { command: "c", key: "k" }).product_id, null);
});

test("labels say who confirmed, what 小Pai wrote unverified, and when the author has left", () => {
  const base = { generated_by: "human", confirmed_by: { name: "张三" }, recorded_at: "2026-11-13T08:00:00+00:00", epistemic_label: "有人这样说", tags: { customer: null }, author: { departed: false }, review_owner: null };
  assert.equal(lib.noteMeta(base), "张三 确认 · 2026-11-13 · 有人这样说");
  assert.equal(lib.noteMeta({ ...base, generated_by: "xiaopai", confirmed_by: null }), "小Pai 记录，未核实 · 2026-11-13 · 有人这样说");
  assert.equal(lib.noteMeta({ ...base, generated_by: "xiaopai_drafted", tags: { customer: "客户A" }, author: { departed: true }, review_owner: { name: "李四" } }), "张三 确认（小Pai 起草） · 2026-11-13 · 有人这样说 · 客户 客户A · 作者已离开，复核人 李四");
  const split = lib.splitNotes([{ state: "active" }, { state: "expired" }, { state: "retired" }, { state: "superseded" }]);
  assert.equal(split.current.length, 2); assert.equal(split.past.length, 2);
  assert.equal(lib.isScopeNotesView({ version: "scope-notes/v1", notes: [] }), true);
  assert.equal(lib.isScopeNotesView({ version: "memory-notes/v1", notes: [] }), false);
});

test("evidence links carry only the chosen source, stance, place and quote; unknown choices are dropped", () => {
  const options = [
    { source_type: "run", source_kind: null, source_id: "r1", type_label: "小Pai 运行", title: "2026-11-15 整理样件约定", version: null },
    { source_type: "business_object", source_kind: "proposal_decision", source_id: "d1", type_label: "G0 决定", title: "提案 的 G0 决定", version: 1 },
  ];
  const payload = plain(lib.evidencePayload({ note_id: "n", revision: 3 }, [
    { key: lib.optionKey(options[0]), stance: "supports", where: " 第 2 轮 ", quote: "" },
    { key: lib.optionKey(options[1]), stance: "context", where: "", quote: " 摘一句 " },
    { key: "receipt::forged", stance: "supports", where: "", quote: "" },
  ], options));
  assert.deepEqual(payload, { mode: "evidence", note: { id: "n", revision: 3 }, evidence: [
    { source_type: "run", source_id: "r1", stance: "supports", locator: { where: "第 2 轮" } },
    { source_type: "business_object", source_id: "d1", source_kind: "proposal_decision", stance: "context", quote: "摘一句" },
  ] });
  for (const key of ["source_version", "root_source_id", "quote_sha256", "category_id"]) assert.equal(JSON.stringify(payload).includes(key), false);
  const line = lib.evidenceLine({ type_label: "资料原件", title: null, source_version: 2, stance_label: "支持", locator: { where: "第 3 页" }, has_quote: true, by_xiaopai: false, recorded_at: "2026-11-15T01:00:00+00:00" });
  assert.equal(line, "资料原件：当前不可读 · 第 2 版 · 支持 · 位置 第 3 页 · 有摘录（原文未保存，按读者权限重新读取） · 2026-11-15");
  assert.equal(lib.sourcesPath("c", "project", "p"), "v1/categories/c/scope-note-sources/project/p");
});
