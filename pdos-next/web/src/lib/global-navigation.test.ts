import test from "node:test";
import assert from "node:assert/strict";
import { defaultGlobalLocation, globalAreas, globalHref, normalizeGlobalSearch, productManagementCategories, productManagementHref, projectWorkbenchHref, resolveGlobalLocation, type NavigationCategory } from "./global-navigation";

const category = "11111111-2222-4333-8444-555555555555";
const project = "66666666-7777-4888-8999-aaaaaaaaaaaa";

test("P15 四个全局主干按项目优先排列，默认仍是我的工作", () => {
  assert.deepEqual(globalAreas.filter(entry => entry.group === "main").map(entry => [entry.id, entry.label]), [["work", "我的工作"], ["projects", "项目"], ["programs", "组合与资源"], ["knowledge", "知识"]]);
  assert.equal(globalAreas.find(entry => entry.id === "category")?.group, "product_management");
  assert.equal(globalAreas.find(entry => entry.id === "cockpit")?.group, undefined);
  assert.equal(defaultGlobalLocation.area, "work");
});

test("产品管理组只使用当前品类的明确服务器能力，不从可读、写入或岗位补授", () => {
  const granted = { id: "pm", capabilities: { product_management: true } };
  const readable = { id: "reader" };
  const ordinaryWriter = { id: "writer", can_write: true };
  const roleName = { id: "role", role: "product_manager", product_manager: true };
  const revoked = { id: "revoked", capabilities: { product_management: false } };
  const malformed = { id: "malformed", capabilities: { product_management: "true" } } as unknown as NavigationCategory;
  const categories = [readable, granted, ordinaryWriter, roleName, revoked, malformed];
  assert.deepEqual(productManagementCategories(categories), [granted]);
  assert.deepEqual(productManagementCategories([]), []);
  assert.equal(categories.length, 6);
});

test("产品管理入口定位现有品类提案，不继承项目工作台范围", () => {
  assert.equal(productManagementHref(), "?area=category");
  const params = new URLSearchParams(productManagementHref(category, "proposals"));
  assert.equal(params.get("area"), "category");
  assert.equal(params.get("category"), category);
  assert.equal(params.get("focus"), "proposals");
  assert.equal(params.get("bench"), null);
  assert.equal(params.get("project"), null);
  assert.equal(resolveGlobalLocation(`?${params}`).area, "category");
  assert.equal(new URLSearchParams(globalHref({ area: "projects", categoryId: category, projectId: "" }, `?${params}`)).get("focus"), null);
});

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

test("全局及旧项目工作区七种位置解析与往返保持", () => {
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
