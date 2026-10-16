import test from "node:test";
import assert from "node:assert/strict";
import { globalHref, normalizeGlobalSearch, projectWorkbenchHref, resolveGlobalLocation } from "./global-navigation";

const category = "11111111-2222-4333-8444-555555555555";
const project = "66666666-7777-4888-8999-aaaaaaaaaaaa";

test("项目工作台直达保留具体项目和型号，直接进入计划", () => {
  const href = projectWorkbenchHref(category, "model-identity", project);
  const params = new URLSearchParams(href);
  assert.equal(params.get("area"), "category");
  assert.equal(params.get("bench"), "projects");
  assert.equal(params.get("view"), "plan");
  assert.equal(params.get("product"), "model-identity");
  assert.equal(resolveGlobalLocation(href).projectId, project);
  assert.equal(normalizeGlobalSearch(href).changed, false);
});

test("全局七入口解析与往返保持", () => {
  for (const area of ["work", "cockpit", "projects", "programs", "category", "knowledge", "settings"] as const) {
    const location = resolveGlobalLocation(`?area=${area}&category=${category}`);
    assert.equal(location.area, area);
    assert.equal(location.categoryId, category);
    const round = resolveGlobalLocation(globalHref(location));
    assert.deepEqual(round, location);
    assert.equal(normalizeGlobalSearch(globalHref(location)).changed, false);
  }
});

test("未知入口与无品类落空回我的工作", () => {
  assert.equal(resolveGlobalLocation("?area=admin").area, "work");
  assert.equal(resolveGlobalLocation("").area, "work");
  assert.equal(resolveGlobalLocation("?area=products").area, "work");
});

test("旧品类链接映射到品类工作区或知识，保留品类范围", () => {
  const products = resolveGlobalLocation(`?category=${category}&area=products&view=overview`);
  assert.equal(products.area, "category");
  assert.equal(products.categoryId, category);
  const knowledge = resolveGlobalLocation(`?category=${category}&area=knowledge&view=sources`);
  assert.equal(knowledge.area, "knowledge");
  const bare = resolveGlobalLocation(`?category=${category}`);
  assert.equal(bare.area, "category");
});

test("规范化旧 URL 一次到位且幂等", () => {
  const legacy = normalizeGlobalSearch(`?category=${category}&area=projects&view=builds&task=supply`);
  assert.equal(legacy.changed, true);
  const params = new URLSearchParams(legacy.search);
  assert.equal(params.get("area"), "category");
  assert.equal(params.get("bench"), "projects");
  assert.equal(params.get("view"), "builds");
  assert.equal(normalizeGlobalSearch(legacy.search).changed, false);
  const resources = normalizeGlobalSearch(`?category=${category}&area=resources`);
  assert.equal(new URLSearchParams(resources.search).get("area"), "programs");
  assert.equal(normalizeGlobalSearch(`?area=work`).changed, false);
});

test("带品类的项目列表刷新不被旧链接映射，知识旧链接只转换一次", () => {
  const current = `?area=projects&category=${category}`;
  assert.deepEqual(normalizeGlobalSearch(current), { search: current, changed: false });
  const legacy = normalizeGlobalSearch(`?area=knowledge&category=${category}&view=sources`);
  assert.equal(legacy.changed, true);
  assert.equal(new URLSearchParams(legacy.search).get("bench"), "knowledge");
  assert.equal(normalizeGlobalSearch(legacy.search).changed, false);
});

test("驾驶舱项目参数与跨区导航清理品类工作台参数", () => {
  const cockpit = resolveGlobalLocation(`?area=cockpit&category=${category}&project=${project}`);
  assert.equal(cockpit.projectId, project);
  const href = globalHref({ area: "projects", categoryId: "", projectId: "" }, `?area=category&category=${category}&bench=projects&view=builds&task=supply&product=abc`);
  const params = new URLSearchParams(href);
  assert.equal(params.get("area"), "projects");
  assert.equal(params.get("category"), null);
  assert.equal(params.get("bench"), null);
  assert.equal(params.get("view"), null);
});
