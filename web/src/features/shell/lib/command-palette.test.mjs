import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
const require = createRequire(import.meta.url), ts = require("typescript");
const compiled = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./command-palette.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiled, exports: compiled.exports, URLSearchParams });
const exported = compiled.exports;
// 编译模块在独立上下文中运行，返回值先转成本上下文的普通值再比较。
const plain = value => JSON.parse(JSON.stringify(value));
const { paletteOperations, createIntents, commandHref, memberCanWrite, noSignals } = exported;
const paletteCommands = signals => plain(exported.paletteCommands(signals));
const filterCommands = (commands, query) => plain(exported.filterCommands(commands, query));
const takeCreateIntent = (search, intent) => plain(exported.takeCreateIntent(search, intent));
const managedCategories = raw => plain(exported.managedCategories(raw));

const registry = new Map();
for (const name of ["operations.json", "auxiliary-operations.json"]) {
  for (const entry of JSON.parse(readFileSync(new URL(`../../../../../contracts/${name}`, import.meta.url), "utf8")).items) registry.set(entry.operation, entry);
}
const categoryA = "11111111-1111-4111-8111-111111111111", categoryB = "22222222-2222-4222-8222-222222222222";
const project = "33333333-3333-4333-8333-333333333333", principal = "44444444-4444-4444-8444-444444444444";
const pm = (...ids) => ids.map((id, index) => ({ id, name: `品类${index + 1}` }));
const member = canWrite => ({ categoryId: categoryA, projectId: project, name: "P1 项目", canWrite });
const creates = signals => paletteCommands(signals).filter(command => command.group === "create");
const ops = signals => creates(signals).map(command => command.operation).sort();
const nav = signals => paletteCommands(signals).filter(command => command.group === "navigate").map(command => command.label);

test("每条命令都来自登记表：已实现、档位一致，且不含具名决定", () => {
  for (const [operation, tier] of Object.entries(paletteOperations)) {
    const entry = registry.get(operation);
    assert.ok(entry, `${operation} 未登记`);
    assert.equal(entry.write_tier, tier, `${operation} 档位与登记表不一致`);
    assert.match(entry.implementation, /^implemented_local_/, `${operation} 尚未实现`);
    assert.notEqual(tier, "T2", `${operation} 是具名决定，不能进入面板`);
  }
  assert.deepEqual(Object.values(createIntents).sort(), Object.keys(paletteOperations).sort());
  const everything = paletteCommands({ productManagement: pm(categoryA, categoryB), project: member(true) });
  for (const command of everything) {
    if (command.group === "create") assert.ok(command.operation in paletteOperations, command.id);
    else assert.equal(command.operation, undefined, command.id);
    assert.doesNotMatch(`${command.label}${command.hint}`, /\bT[012]\b/, "界面不出现档位枚举");
  }
});

test("普通成员：没有产品管理权、不在项目里，就没有任何快速创建，也看不到产品管理入口", () => {
  assert.deepEqual(creates(noSignals), []);
  assert.deepEqual(nav(noSignals), ["我的工作", "收件箱", "小Pai", "项目", "项目集", "知识", "设置"]);
});

test("产品经理：只在本人有产品管理权的品类里出现新建立项提案", () => {
  const signals = { productManagement: pm(categoryA), project: null };
  assert.deepEqual(ops(signals), ["category.create", "proposal.create"]);
  const proposals = creates(signals).filter(command => command.operation === "proposal.create");
  assert.equal(proposals.length, 1);
  const target = new URLSearchParams(proposals[0].href);
  assert.equal(target.get("category"), categoryA);
  assert.equal(target.get("focus"), "proposals");
  assert.equal(target.get("create"), "proposal");
  assert.ok(!paletteCommands(signals).some(command => command.href.includes(categoryB)));
  assert.ok(nav(signals).includes("品类") && nav(signals).includes("立项提案"));
});

test("项目成员：只有服务器读回本人可写时才出现新建任务与写状态更新", () => {
  assert.deepEqual(ops({ productManagement: [], project: member(false) }), []);
  const writable = { productManagement: [], project: member(true) };
  assert.deepEqual(ops(writable), ["work.status_update.create", "work.task.create"]);
  for (const command of creates(writable)) {
    const target = new URLSearchParams(command.href);
    assert.equal(target.get("area"), "cockpit");
    assert.equal(target.get("project"), project);
    assert.equal(target.get("category"), categoryA);
  }
  assert.deepEqual(ops({ productManagement: [], project: { ...member(true), projectId: "../other" } }), []);
});

test("权限只认服务器明确给出的 true", () => {
  const raw = [
    { id: categoryA, name: "可管理", capabilities: { product_management: true } },
    { id: categoryB, name: "字符串", capabilities: { product_management: "true" } },
    { id: project, name: "缺字段" },
    { id: "not-a-uuid", name: "坏标识", capabilities: { product_management: true } },
  ];
  assert.deepEqual(managedCategories(raw).map(item => item.id), [categoryA]);
  assert.deepEqual(managedCategories(null), []);
  assert.equal(memberCanWrite([{ id: principal, can_write: true }], principal), true);
  assert.equal(memberCanWrite([{ id: principal, can_write: "true" }], principal), false);
  assert.equal(memberCanWrite([{ id: categoryA, can_write: true }], principal), false);
  assert.equal(memberCanWrite(undefined, principal), false);
});

test("输入完整编号只做定位，不附带任何命令；其余按关键词收窄", () => {
  const all = paletteCommands({ productManagement: pm(categoryA), project: member(true) });
  assert.deepEqual(filterCommands(all, project), []);
  assert.deepEqual(filterCommands(all, project.toUpperCase()), []);
  assert.equal(filterCommands(all, "  ").length, all.length);
  assert.deepEqual(filterCommands(all, "提案").map(command => command.label), ["新建立项提案 · 品类1", "立项提案"]);
  assert.deepEqual(filterCommands(all, "新建 任务").map(command => command.operation), ["work.task.create"]);
});

test("命令目标只能是站内相对地址；新建意图读取一次即移除", () => {
  assert.equal(commandHref({ href: "?area=work" }), "?area=work");
  for (const href of ["https://example.com", "//example.com", "/?area=work", "javascript:alert(1)"]) assert.equal(commandHref({ href }), null);
  assert.deepEqual(takeCreateIntent("?area=category&create=category", "category"), { matched: true, search: "?area=category" });
  assert.deepEqual(takeCreateIntent("?create=task", "task"), { matched: true, search: "" });
  assert.equal(takeCreateIntent("?area=category&create=category", "proposal").matched, false);
  assert.equal(takeCreateIntent("?area=category", "category").matched, false);
});
