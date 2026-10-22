import assert from "node:assert/strict";
import test from "node:test";
import type { KnowledgeScope } from "./knowledge-experience";
import {
  knowledgeNativeAvailable, knowledgeNativeConfigurationKey, knowledgeNativeDraftPatch,
  knowledgeNativeSourceKey, parseKnowledgeNativeContext, selectKnowledgeNative,
  type KnowledgeNativeContext, type KnowledgeNativeKeys,
} from "./knowledge-experience-native";

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: KnowledgeScope = { categoryId: id(1), productId: id(2), projectId: "", principalId: id(3) };
function context(): KnowledgeNativeContext {
  return {
    scope: { category_id: scope.categoryId, product_id: scope.productId, project_id: null, principal_id: scope.principalId },
    as_of: "2026-10-19T12:30:00Z",
    result_options: [{ receipt_id: id(4), family: "change", title: "已保存的变更结果", operation: "change.implementation.record", subject: { kind: "change_request", id: id(5), revision: 8 }, recorded_at: "2026-10-19T11:30:00Z", visibility: "audience", selectable: true, reason: null }],
    source_options: [{ ref: { kind: "artifact", id: id(6), revision: 2, position: "line:3;quote_sha256:" + "a".repeat(64) }, title: "现场报告原件", excerpt: "保留实际原文，不据此推定已验证。", visibility: "private", selectable: true, reason: null }],
    configuration_options: [{ ref: { kind: "engineering_configuration", id: id(7), revision: 3 }, name: "实际配置", selectable: true, reason: null }],
    next_cursor: null,
  };
}
function keys(value = context()): KnowledgeNativeKeys {
  return { results: [value.result_options[0].receipt_id], sources: [knowledgeNativeSourceKey(value.source_options[0].ref)], configurations: [knowledgeNativeConfigurationKey(value.configuration_options[0].ref)] };
}

test("explicit actual selection preserves fixed receipt, original position and configuration references", () => {
  const value = context(), before = structuredClone(value);
  const selected = selectKnowledgeNative(value, scope, keys(value));
  assert.deepEqual(selected.result_receipts, [{ receipt_id: id(4) }]);
  assert.deepEqual(selected.sources, [value.source_options[0].ref]);
  assert.deepEqual(selected.configurations, [value.configuration_options[0].ref]);
  assert.deepEqual(value, before);
  const patch = knowledgeNativeDraftPatch(selected, value, scope);
  assert.deepEqual(JSON.parse(patch.sources), selected.sources);
  assert.deepEqual(JSON.parse(patch.result_receipts), selected.result_receipts);
  assert.deepEqual(Object.keys(patch).sort(), ["result_receipts", "sources"]);
  assert.equal("visibility" in patch || "applicability" in patch || "configuration" in patch, false);
});

test("unscoped candidate may use only an actual original without a result or selected configuration", () => {
  const value = context(); value.result_options = []; value.configuration_options = [];
  const selected = selectKnowledgeNative(value, scope, { results: [], sources: [knowledgeNativeSourceKey(value.source_options[0].ref)], configurations: [] });
  assert.deepEqual(selected.result_receipts, []); assert.deepEqual(selected.configurations, []);
  assert.equal(JSON.parse(knowledgeNativeDraftPatch(selected, value, scope).sources).length, 1);
});

test("a legitimate unfinished Change or another supported result is not made dependent on closed state", () => {
  for (const [family, operation] of [["change", "change.request.create"], ["other", "test.result.compute"]] as const) {
    const value = context(); Object.assign(value.result_options[0], { family, operation });
    assert.deepEqual(selectKnowledgeNative(value, scope, keys(value)).result_receipts, [{ receipt_id: id(4) }]);
  }
});

test("all current caller and project bindings must match before private directory contents are used", () => {
  for (const field of ["categoryId", "productId", "principalId", "projectId"] as const) {
    assert.throws(() => parseKnowledgeNativeContext(context(), { ...scope, [field]: id(99) }), /当前本人/);
  }
  const value = context(); value.scope.project_id = id(8);
  assert.equal(parseKnowledgeNativeContext(value, { ...scope, projectId: id(8) }).scope.project_id, id(8));
});

test("unavailable options and an explicit failure reason are not selectable even with a contradictory flag", () => {
  for (const group of ["result_options", "source_options", "configuration_options"] as const) {
    for (const flags of [{ selectable: false, reason: null }, { selectable: true, reason: "实际来源需要重核" }]) {
      const value = context(); Object.assign(value[group][0], flags);
      assert.equal(knowledgeNativeAvailable(value[group][0]), false);
      assert.throws(() => selectKnowledgeNative(value, scope, keys(value)), /可用目录/);
    }
  }
});

test("absent references, duplicate choices and conflicting versions never retarget or silently deduplicate", () => {
  const value = context();
  for (const group of ["results", "sources", "configurations"] as const) {
    assert.throws(() => selectKnowledgeNative(value, scope, { ...keys(value), [group]: ["unlisted"] }));
    const fixed = keys(value)[group][0];
    assert.throws(() => selectKnowledgeNative(value, scope, { ...keys(value), [group]: [fixed, fixed] }), /重复/);
  }
  const other = structuredClone(value.source_options[0]); other.ref.revision = 3;
  value.source_options.push(other);
  assert.throws(() => selectKnowledgeNative(value, scope, { ...keys(value), sources: value.source_options.map(row => knowledgeNativeSourceKey(row.ref)) }), /不同版本/);
});

test("no actual original means no candidate-source patch, including a configuration-only selection", () => {
  assert.throws(() => selectKnowledgeNative(context(), scope, { results: [], sources: [], configurations: keys().configurations }), /至少一条/);
});

test("refreshed pages, source corrections and scope changes invalidate old selection without a new TTL", () => {
  const value = context(), selection = selectKnowledgeNative(value, scope, keys(value));
  for (const change of [
    (v: KnowledgeNativeContext) => { v.as_of = "2026-10-19T12:31:00Z"; },
    (v: KnowledgeNativeContext) => { v.next_cursor = "another-page"; },
    (v: KnowledgeNativeContext) => { v.source_options[0].ref.revision++; },
    (v: KnowledgeNativeContext) => { v.source_options[0].selectable = false; },
    (v: KnowledgeNativeContext) => { v.result_options = []; },
  ]) {
    const updated = structuredClone(value); change(updated);
    assert.throws(() => knowledgeNativeDraftPatch(selection, updated, scope), /目录已刷新/);
  }
  assert.throws(() => knowledgeNativeDraftPatch(selection, value, { ...scope, principalId: id(99) }));
});

test("selected references are rederived from current options and cannot carry caller-proposed fact flags", () => {
  const value = context(), selection = selectKnowledgeNative(value, scope, keys(value));
  for (const mutate of [
    (s: Record<string, unknown>) => { s.authorized = true; },
    (s: typeof selection) => { Object.assign(s.sources[0], { qualified: true }); },
    (s: typeof selection) => { s.sources[0].position = "changed source position"; },
    (s: typeof selection) => { Object.assign(s.configurations[0], { applicable: true }); },
  ]) {
    const forged = structuredClone(selection); mutate(forged);
    assert.throws(() => knowledgeNativeDraftPatch(forged, value, scope));
  }
});

test("malformed, duplicate and authority-bearing server rows fail as unknown instead of an empty list", () => {
  const mutations = [
    (v: Record<string, unknown>) => { v.authorized = true; },
    (v: KnowledgeNativeContext) => { v.result_options[0].subject.revision = true as unknown as number; },
    (v: KnowledgeNativeContext) => { v.source_options[0].ref.kind = "domain" as "artifact"; },
    (v: KnowledgeNativeContext) => { Object.assign(v.source_options[0].ref, { owner_id: id(99) }); },
    (v: KnowledgeNativeContext) => { v.configuration_options[0].ref.kind = "manufacturing_configuration" as "process_revision"; },
    (v: KnowledgeNativeContext) => { v.result_options.push(structuredClone(v.result_options[0])); },
    (v: KnowledgeNativeContext) => { v.source_options.push(structuredClone(v.source_options[0])); },
    (v: KnowledgeNativeContext) => { v.configuration_options.push(structuredClone(v.configuration_options[0])); },
    (v: KnowledgeNativeContext) => { v.as_of = "2026-10-19T12:30:00"; },
  ];
  for (const mutate of mutations) { const value = context(); mutate(value); assert.throws(() => parseKnowledgeNativeContext(value, scope)); }
  const empty = context(); empty.result_options = []; empty.source_options = []; empty.configuration_options = [];
  assert.equal(parseKnowledgeNativeContext(empty, scope).source_options.length, 0);
});
