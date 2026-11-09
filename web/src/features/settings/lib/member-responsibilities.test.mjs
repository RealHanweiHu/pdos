import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const dir = path.dirname(fileURLToPath(import.meta.url)), dep = createRequire(path.join(dir, "../../../../package.json")), ts = dep("typescript");
function load(name) { const filename = path.join(dir, name), loaded = new Module(filename); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename); return loaded.exports; }
const { memberRows, parseTeam, readTeams, responsibilityText } = load("member-responsibilities.ts");
const team = (id, members) => ({ project: { id, name: `项目${id}`, owner_id: "lead", visibility: "private" }, members, revision: 1 });
const member = (principal_id, name, roles, is_owner = false) => ({ principal_id, name, is_owner, roles });

test("category members keep server order and gain each visible project's roles; team-only people are marked", () => {
  const rows = memberRows([{ id: "lead", name: "负责人" }, { id: "eng", name: "工程师" }, { id: "idle", name: "未分配" }], [
    team("p1", [member("lead", "负责人", [], true), member("eng", "工程师", [{ key: "structure", name: "结构工程", lead: true }, { key: "test", name: "测试", lead: false }])]),
    team("p2", [member("eng", "工程师", [{ key: "test", name: "测试", lead: false }]), member("ext", "外协", [])]),
  ]);
  assert.deepEqual(rows.map(row => row.id), ["lead", "eng", "idle", "ext"]);
  assert.equal(responsibilityText(rows[0].assignments[0]), "项目负责人");
  assert.equal(responsibilityText(rows[1].assignments[0]), "结构工程（主责）、测试");
  assert.deepEqual(rows[1].assignments.map(item => item.projectName), ["项目p1", "项目p2"]);
  assert.equal(rows[2].assignments.length, 0);
  assert.equal(rows[3].categoryMember, false);
  assert.equal(responsibilityText(rows[3].assignments[0]), "成员（角色待补充）");
});

test("team reads are GET-only, bounded, ordered, and an unreadable team is counted instead of shown as no role", async () => {
  const calls = []; let inFlight = 0, peak = 0;
  const projects = Array.from({ length: 6 }, (_, index) => ({ id: `p${index}`, name: `P${index}`, categoryId: "c", productId: "m" }));
  const api = async (route, body) => {
    calls.push([route, body]); inFlight += 1; peak = Math.max(peak, inFlight);
    await new Promise(resolve => setTimeout(resolve, 6 - calls.length));
    inFlight -= 1;
    const id = route.split("/projects/")[1].split("/")[0];
    if (id === "p3") throw new Error("403");
    if (id === "p4") return { project: { id: "other", name: "x" }, members: [] };
    return team(id, [member("eng", "工程师", [])]);
  };
  const result = await readTeams(api, projects, 2);
  assert.equal(peak <= 2, true); assert.equal(result.unavailable, 2);
  assert.deepEqual(result.teams.map(item => item.project.id), ["p0", "p1", "p2", "p5"]);
  assert.ok(calls.every(([route, body]) => body === undefined && route === `v1/categories/c/products/m/projects/${route.split("/projects/")[1].split("/")[0]}/team`));
  assert.throws(() => parseTeam({ project: { id: "p", name: "P" }, members: [{ principal_id: "x", name: "X", is_owner: false, roles: [{ key: "k" }] }] }, "p"));
});
