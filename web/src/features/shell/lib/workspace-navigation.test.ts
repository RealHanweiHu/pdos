import test from "node:test";
import assert from "node:assert/strict";
import { resolveWorkspaceLocation, workspaceEntry, workspaceHref, workspaceSections } from "./workspace-navigation";

test("未知入口及跨领域步骤不会激活专业办理面板", () => {
  assert.equal(workspaceEntry(resolveWorkspaceLocation("?bench=admin&view=release&task=results")).panel, undefined);
  assert.equal(resolveWorkspaceLocation("?bench=admin").area, "products");
  const definition = resolveWorkspaceLocation("?bench=products&view=definition&task=results");
  assert.equal(definition.task, "");
  assert.equal(workspaceEntry(definition).panel, "definition");
});

test("分享地址往返保持产品范围与实际测试步骤", () => {
  const location = resolveWorkspaceLocation("?product=0136a133-5ac8-455a-a2ee-bfba4c2c0f05&bench=projects&view=verification&task=results");
  assert.deepEqual(resolveWorkspaceLocation(workspaceHref(location)), location);
  assert.equal(workspaceEntry(location).panel, "results");
});

test("切换到无子步骤的视图会删除旧步骤并保留既有定位参数", () => {
  const target = resolveWorkspaceLocation("?bench=knowledge&view=files&product=one");
  const url = workspaceHref(target, "?task=launch&record=retained");
  assert.equal(new URLSearchParams(url).has("task"), false);
  assert.equal(new URLSearchParams(url).get("record"), "retained");
  assert.equal(workspaceEntry(resolveWorkspaceLocation(url)).panel, "originals");
});

test("未接入竞品和评审入口不会触发写入或映射成已实现工作", () => {
  for (const search of ["?bench=products&view=research&task=competitors", "?bench=projects&view=reviews"]) {
    const entry = workspaceEntry(resolveWorkspaceLocation(search));
    assert.equal(entry.planned, true);
    assert.equal(entry.panel, undefined);
  }
});

test("研究、机会、实验、策略不再设为独立页面（C3）", () => {
  const ids = workspaceSections.products.map(entry => entry.id);
  for (const removed of ["opportunities", "roadmap", "feedback"]) assert.equal(ids.includes(removed), false);
  assert.deepEqual(ids, ["overview", "research", "definition", "variants", "activity"]);
});

test("活动面板归入型号区段，工作与组合区不再出现在品类工作台", () => {
  const activity = workspaceSections.products.find(entry => entry.id === "activity");
  assert.equal(activity?.panel, "activity");
  for (const removed of ["work", "resources"]) {
    assert.equal(resolveWorkspaceLocation(`?bench=${removed}`).area, "products");
  }
});
