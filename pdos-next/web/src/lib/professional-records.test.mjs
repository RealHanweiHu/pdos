import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url), ts = require("typescript");
function load(file, react) {
  const mod = new Module(file);
  mod.require = name => name === "react" ? react : name.startsWith(".") ? load(path.resolve(path.dirname(file), `${name}.ts`)) : require(name);
  mod._compile(ts.transpileModule(readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, file);
  return mod.exports;
}
const { readProfessionalBuilds, readProfessionalRecords } = load(path.join(directory, "professional-records.ts"));

test("project Build lookup rejects a foreign project, never falling back to a product-wide list", async () => {
  const paths = [];
  await assert.rejects(readProfessionalBuilds(async route => { paths.push(route); return { items: [{ id: "foreign", name: "Other project", project_id: "other" }] }; }, "p", "project"), /范围不完整/);
  assert.deepEqual(paths, ["v1/products/p/builds?project_id=project"]);
});
test("professional projections narrow product-wide data to the selected project and Build", async () => {
  const reading = await readProfessionalRecords(async () => ({ inputs: [
    { id: "ours", build_id: "b", project_id: "project", title: "Exact cost", revision: 2 },
    { id: "other-build", build_id: "other", project_id: "project" },
    { id: "other-project", build_id: "b", project_id: "other" },
    { id: "unbound" },
  ], estimates: [] }), "p", "project", "cost", "b");
  assert.deepEqual(reading.rows.map(row => row.id), ["ours"]);
  assert.equal(reading.rows[0].title, "Exact cost");
});
test("changes use actual nested titles and explicit current pointers; paging retains scope", async () => {
  const paths = [];
  const reading = await readProfessionalRecords(async route => { paths.push(route); return {
    changes: [{ id: "v1", change_id: "change", revision: 1, project_id: "project", current: false, request: { title: "Real change", reason: "Measured failure" }, status: "draft" }],
    history_page: { next_cursor: "next" }, has_more: true,
  }; }, "p", "project", "changes", "", "cursor&opaque");
  assert.equal(reading.rows[0].title, "Real change");
  assert.equal(reading.rows[0].historical, true);
  assert.equal(reading.rows[0].target.change, "change");
  assert.equal(reading.nextCursor, "next");
  assert.match(paths[0], /project_id=project&history_cursor=cursor%26opaque/);
});
test("malformed reads and failed reads cannot become an empty successful list", async () => {
  await assert.rejects(readProfessionalRecords(async () => ({ changes: [{}] }), "p", "project", "changes"), /身份不完整/);
  await assert.rejects(readProfessionalRecords(async () => ({}), "p", "project", "changes"), /缺少必要/);
  await assert.rejects(readProfessionalRecords(async () => { throw new Error("Forbidden"); }, "p", "project", "changes"), /Forbidden/);
  await assert.rejects(readProfessionalRecords(async () => ({ changes: [], history_page: { next_cursor: "same" } }), "p", "project", "changes", "", "same"), /未能继续/);
});
test("results preserve exact Run/request targets and fixed result, without approval inference", async () => {
  const reading = await readProfessionalRecords(async () => ({ runs: [{ id: "version", run_id: "run", request_id: "request", request_revision: 1, build: { id: "build", project_id: "project" }, status: "disposed", result: "pass", is_current: true }], requests: [{ request_id: "request", revision: 1, title: "Fixed request" }] }), "p", "project", "results", "build");
  assert.deepEqual(reading.rows[0].target, { build: "build", request: "request", run: "run" });
  assert.deepEqual(reading.rows[0].facts, [["固定范围结果", "固定范围通过"]]);
  assert.equal(reading.rows[0].title, "Fixed request");
});
test("selection intents wait for readable options and pending work, consume once, and never submit", () => {
  let intent = null, index = 0;
  const refs = [], effects = [], choices = [];
  const react = { createContext: () => ({}), useContext: () => intent, useRef: value => refs[index++] ??= { current: value }, useEffect: effect => effects.push(effect) };
  const { useProfessionalSelection } = load(path.resolve(directory, "../components/projects/professional-target.tsx"), react);
  const RenderSelection = (options, selected, blocked) => { index = 0; useProfessionalSelection("build", options, selected, blocked, id => choices.push(id)); effects.splice(0).forEach(effect => effect()); };
  intent = { target: { build: "b" }, serial: 1 };
  RenderSelection([], "", false); RenderSelection(["foreign"], "", false); RenderSelection(["b"], "", true);
  assert.deepEqual(choices, []);
  RenderSelection(["b"], "", false); RenderSelection(["b"], "", false);
  assert.deepEqual(choices, ["b"]);
  intent = null; RenderSelection(["b"], "", false);
  intent = { target: { build: "b" }, serial: 2 }; RenderSelection(["b"], "b", false);
  assert.deepEqual(choices, ["b"]);
});

test("field continuation uses the public logical feedback id, with no optional alias required", async () => {
  const reading=await readProfessionalRecords(async()=>({feedbacks:[{id:"feedback",version_id:"version",project_id:"project",title:"Customer feedback"}]}),"p","project","field");
  assert.equal(reading.rows[0].target.feedback,"feedback");
});

test("supply and cost history use freshness and captured_at, preserving recalculation state", async () => {
  for(const [panel,group] of [["supply","snapshots"],["cost","inputs"]]) {
    const reading=await readProfessionalRecords(async()=>({[group]:[{id:"old",build_id:"b",freshness:"historical",source_status:"current",captured_at:"2026-10-20T00:00:00Z"},{id:"stale",build_id:"b",freshness:"requires_recalculation",source_status:"current"}],kits:[],estimates:[]}),"p","project",panel,"b");
    assert.equal(reading.rows[0].historical,true);assert.equal(reading.rows[0].at,"2026-10-20T00:00:00Z");assert.equal(reading.rows[1].source,"依据需重算");
  }
});
const {restoreProjectBuildDraft}=load(path.join(directory,"project-draft-recovery.ts"));
test("legacy recovery retains only verified project drafts and the exact unknown command without POST", async () => {
  const pending={stage:"execute",command:{command_id:"original",idempotency_key:"original-key",payload:{build_id:"b",confirmation_token:"original-token"}}};
  const saved={buildId:"b",drafts:{b:{reason:"ours"},other:{reason:"foreign"}},prepared:{},pending};
  const data=new Map([["legacy",JSON.stringify(saved)]]), storage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)}, calls=[];
  const next=await restoreProjectBuildDraft(storage,"new","legacy",v=>v,async(route,body)=>{calls.push({route,body});return {items:[{id:"b",name:"Our Build",project_id:"project"}]};},"p","project",()=>true);
  assert.deepEqual(next.pending,pending);assert.deepEqual(Object.keys(next.drafts),["b"]);assert.equal(calls[0].body,undefined);assert.deepEqual(JSON.parse(data.get("legacy")),saved);
  const again=await restoreProjectBuildDraft(storage,"new","legacy",v=>v,async()=>{throw new Error("must not remigrate");},"p","project",()=>true);assert.deepEqual(again,next);
});
test("incomplete legacy scope or cancelled reads never create a replacement local request", async () => {
  const saved={buildId:"b",drafts:{b:{}},prepared:{},pending:null},data=new Map([["legacy",JSON.stringify(saved)]]),storage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};
  await assert.rejects(restoreProjectBuildDraft(storage,"new","legacy",v=>v,async()=>({items:[],unavailable_count:1}),"p","project",()=>true),/尚未读全/);assert.equal(data.has("new"),false);
  await restoreProjectBuildDraft(storage,"new","legacy",v=>v,async()=>({items:[]}),"p","project",()=>false);assert.equal(data.has("new"),false);
});
